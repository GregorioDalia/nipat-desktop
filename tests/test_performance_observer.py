"""Optional measurements must not change execution, ownership or failure handling."""

from contextlib import nullcontext, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from nipat.errors import RuntimeExecutionError
from nipat.execution.options import ExecutionOptions
from nipat.execution.performance import ContainerPerformanceObserver, parse_stats
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.transport import DockerTransport
from nipat.paths import ProjectLayout


CONTAINER = "a" * 64
IMAGE = "sha256:" + "b" * 64
NAME = "nipat-run-" + "c" * 32
LABELS = {"org.nipat.execution-token": "d" * 32}


def stats(**changes):
    row = {"id": CONTAINER, "cpu_percent": "151.50%", "memory": "12.25MiB / 2GiB",
           "block_io": "2.5MB / 1KiB", "pids": "7"}
    row.update(changes)
    return json.dumps(row)


def owned(status="running"):
    return {"owned": True, "availability": "available", "container_id": CONTAINER,
            "state": {"status": status, "oom_killed": False}}


class ContainerObserverTests(unittest.TestCase):
    def setUp(self):
        # macOS exposes its temporary directory through /var -> /private/var.
        # Production run paths are already canonicalized by ProjectLayout.
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.runner = SimpleNamespace(_transport=DockerTransport(), _environment=lambda: {}, _image_id=IMAGE)
        self.observer = ContainerPerformanceObserver(
            self.runner, NAME, LABELS, self.root / "performance", interval=0.001,
        )

    def collect(self, sample=None, *, inspect=None, fail=None):
        observed = []

        def read():
            observed.append("sample")
            if fail is not None:
                raise fail
            self.observer._stop.set()
            return {**(sample or parse_stats(stats(), CONTAINER)), "observed_at": "2026-11-03T12:00:00Z",
                    "elapsed_seconds": 1.2, "query_seconds": 0.02}

        with patch("nipat.execution.performance.inspect_container", return_value=inspect or owned()) as inspection, patch.object(
            self.observer, "_stats", side_effect=read,
        ):
            self.observer.start()
            self.observer._thread.join(timeout=2)
            self.assertFalse(self.observer._thread.is_alive())
            summary = self.observer.stop()
        return summary, observed, inspection

    def test_cli_metrics_are_normalized_but_described_as_rounded_cache_adjusted_samples(self):
        sample = parse_stats(stats(secret="do-not-store", command="private sample.bam"), CONTAINER)
        self.assertEqual(sample["cpu_percent"], 151.5)
        self.assertEqual(sample["memory_cache_adjusted_bytes"], 12.25 * 1024**2)
        self.assertEqual(sample["memory_limit_bytes"], 2 * 1024**3)
        self.assertEqual(sample["block_io_read_bytes"], 2_500_000)
        self.assertEqual(sample["block_io_write_bytes"], 1024)
        self.assertEqual(sample["unavailable_metrics"], [])
        self.assertNotIn("secret", sample)
        self.assertNotIn("command", sample)
        summary, _, _ = self.collect(sample)
        self.assertEqual(summary["sample_count"], 1)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["sampled_maxima"]["memory_cache_adjusted_bytes"], 12.25 * 1024**2)
        self.assertIn("not kernel memory.peak", " ".join(summary["measurement_notes"]))
        self.assertNotIn("do-not-store", (self.observer.directory / "container-samples.jsonl").read_text())
        self.assertEqual(json.loads((self.observer.directory / "summary.json").read_text()), summary)

    def test_absent_metrics_are_not_replaced_with_zero(self):
        row = parse_stats(stats(memory="-- / --", cpu_percent="NaN%", pids="N/A"), CONTAINER)
        self.assertNotIn("memory_cache_adjusted_bytes", row)
        self.assertNotIn("cpu_percent", row)
        self.assertNotIn("pids", row)
        self.assertIn("memory_limit_bytes", row["unavailable_metrics"])
        self.assertEqual(row["block_io_read_bytes"], 2_500_000)

    def test_malformed_or_wrong_container_responses_are_rejected(self):
        for raw in ("not json", "[]", stats(id="wrong"), "x" * 20000,
                    stats(memory="?", cpu_percent="?", block_io="?", pids="?")):
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                parse_stats(raw, CONTAINER)

    def test_failed_identity_never_samples_an_unowned_container(self):
        summary, observed, inspection = self.collect(inspect={
            "owned": False, "availability": "identity_mismatch",
        })
        self.assertEqual(observed, [])
        self.assertEqual(summary["status"], "unavailable")
        self.assertEqual(summary["reason"], "ownership_not_verified")
        self.assertEqual(inspection.call_args.args[1:], (NAME, LABELS))

    def test_created_container_is_waited_for_before_first_sample(self):
        sample = {**parse_stats(stats(), CONTAINER), "observed_at": "2026-11-03T12:00:00Z"}

        def read():
            self.observer._stop.set()
            return sample

        with patch("nipat.execution.performance.inspect_container", side_effect=[
            owned("created"), owned("running"),
        ]) as inspection, patch.object(self.observer, "_stats", side_effect=read):
            self.observer.start()
            self.observer._thread.join(timeout=2)
            summary = self.observer.stop()
        self.assertEqual(inspection.call_count, 2)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["sample_count"], 1)

    def test_short_finished_run_has_explicit_unavailable_evidence(self):
        summary, observed, _ = self.collect(inspect=owned("exited"))
        self.assertEqual(observed, [])
        self.assertEqual(summary["sample_count"], 0)
        self.assertEqual(summary["status"], "unavailable")
        self.assertEqual(summary["reason"], "container_not_running_at_first_observation")

    def test_repeated_timeout_finishes_without_hiding_evidence(self):
        summary, observed, _ = self.collect(fail=subprocess.TimeoutExpired("docker stats", 5))
        self.assertEqual(len(observed), 3)
        self.assertEqual(summary["status"], "unavailable")
        self.assertEqual(summary["reason"], "repeated_observation_failures")
        self.assertEqual(summary["observation_failures"], {"TimeoutExpired": 3})

    def test_file_limit_is_enforced_without_a_partial_json_line(self):
        self.observer._max_bytes = 16
        summary, _, _ = self.collect()
        self.assertEqual(summary["reason"], "output_limit_reached")
        self.assertEqual((self.observer.directory / "container-samples.jsonl").stat().st_size, 0)
        self.assertEqual(summary["sample_count"], 0)

    def test_existing_evidence_is_not_overwritten(self):
        self.observer.directory.mkdir()
        target = self.observer.directory / "container-samples.jsonl"
        target.write_text("preserve")
        with self.assertRaises(FileExistsError):
            self.observer.start()
        self.assertEqual(target.read_text(), "preserve")
        self.assertIsNone(self.observer._thread)

    def test_linked_destination_is_rejected_before_writing_evidence(self):
        target = self.root / "elsewhere"
        target.mkdir()
        alias = self.root / "linked"
        try:
            alias.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symbolic links is unavailable on this platform")
        self.observer.directory = alias / "performance"
        with self.assertRaisesRegex(ValueError, "contains a symlink"):
            self.observer.start()
        self.assertEqual(list(target.iterdir()), [])
        self.assertIsNone(self.observer._thread)

    def test_stop_interrupts_startup_wait_and_is_bounded(self):
        with patch("nipat.execution.performance.inspect_container", return_value={
            "owned": False, "availability": "absent",
        }):
            self.observer.start()
            summary = self.observer.stop()
        self.assertFalse(self.observer._thread.is_alive())
        self.assertEqual(summary["status"], "unavailable")
        self.assertEqual(summary["sample_count"], 0)

    def test_stopped_container_zero_row_is_not_reported_as_live_zero_ram(self):
        self.observer._identifier = CONTAINER
        raw = stats(memory="0B / 0B", cpu_percent="0.00%", pids="0")
        with patch("nipat.execution.performance.subprocess.run", return_value=
                   subprocess.CompletedProcess([], 0, raw, "")), self.assertRaises(ValueError):
            self.observer._stats()

    def collect_responses(self, responses, observations):
        """Exercise the real parser and collection loop around a container exit."""
        with patch("nipat.execution.performance.inspect_container", side_effect=observations), patch(
            "nipat.execution.performance.subprocess.run", side_effect=[
                subprocess.CompletedProcess([], 0, raw, "") for raw in responses
            ],
        ):
            self.observer.start()
            self.observer._thread.join(timeout=2)
            self.assertFalse(self.observer._thread.is_alive())
            return self.observer.stop()

    def test_exit_during_first_stats_query_is_unavailable_without_a_collection_failure(self):
        zero = stats(memory="0B / 0B", cpu_percent="0.00%", pids="0")
        summary = self.collect_responses([zero] * 3, [owned(), owned("exited")])
        self.assertEqual(summary["status"], "unavailable")
        self.assertEqual(summary["reason"], "container_stopped_during_sample")
        self.assertEqual(summary["sample_count"], 0)
        self.assertEqual(summary["observation_failures"], {})

    def test_exit_after_valid_samples_does_not_turn_a_complete_collection_partial(self):
        zero = stats(memory="0B / 0B", cpu_percent="0.00%", pids="0")
        summary = self.collect_responses([stats()] + [zero] * 3, [owned(), owned("exited")])
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["reason"], "container_stopped_during_sample")
        self.assertEqual(summary["sample_count"], 1)
        self.assertEqual(summary["observation_failures"], {})
        self.assertEqual(summary["sampled_maxima"]["pids"], 7)

    def test_zero_row_from_still_running_container_remains_a_reported_failure(self):
        zero = stats(memory="0B / 0B", cpu_percent="0.00%", pids="0")
        summary = self.collect_responses([zero] * 3, [owned()] * 4)
        self.assertEqual(summary["reason"], "repeated_observation_failures")
        self.assertEqual(summary["observation_failures"], {"ValueError": 3})
        self.assertEqual(summary["failure_reasons"], {"zero_metrics_while_running": 3})
        self.assertEqual(summary["sample_count"], 0)

    def test_exit_confirmation_rejects_a_replacement_container_with_the_same_name(self):
        zero = stats(memory="0B / 0B", cpu_percent="0.00%", pids="0")
        replacement = {**owned("exited"), "container_id": "f" * 64}
        summary = self.collect_responses([zero] * 3, [owned(), replacement])
        self.assertEqual(summary["reason"], "ownership_not_verified")
        self.assertEqual(summary["failure_reasons"], {"ownership_not_verified": 1})
        self.assertEqual(summary["sample_count"], 0)

    def test_malformed_stats_are_not_hidden_by_a_container_exit(self):
        summary = self.collect_responses(["not JSON; private sample.bam"] * 3, [owned()])
        self.assertEqual(summary["reason"], "repeated_observation_failures")
        self.assertEqual(summary["failure_reasons"], {"invalid_stats_json": 3})
        self.assertEqual(summary["observation_failures"], {"ValueError": 3})
        self.assertNotIn("private sample.bam", json.dumps(summary))

    def test_unavailable_exit_confirmation_does_not_suppress_zero_row_failures(self):
        zero = stats(memory="0B / 0B", cpu_percent="0.00%", pids="0")
        absent = {"owned": False, "availability": "absent"}
        summary = self.collect_responses([zero] * 3, [owned()] + [absent] * 3)
        self.assertEqual(summary["reason"], "repeated_observation_failures")
        self.assertEqual(summary["failure_reasons"], {"terminal_state_not_confirmed": 3})

    def test_shutdown_preserves_any_prior_real_collection_failure(self):
        zero = stats(memory="0B / 0B", cpu_percent="0.00%", pids="0")
        summary = self.collect_responses(
            ["invalid", stats(), zero], [owned(), owned("exited")],
        )
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["sample_count"], 1)
        self.assertEqual(summary["failure_reasons"], {"invalid_stats_json": 1})

    def test_startup_wait_does_not_skip_a_short_running_container(self):
        self.observer._interval = 2.0
        waited = []

        def inspection(*args):
            elapsed = sum(waited)
            return owned("created" if not waited else "running" if elapsed < 0.5 else "exited")

        def read():
            self.observer._stop.set()
            return {**parse_stats(stats(), CONTAINER), "observed_at": "2026-11-03T12:00:00Z"}

        with patch("nipat.execution.performance.inspect_container", side_effect=inspection), patch.object(
            self.observer._stop, "wait", side_effect=lambda seconds: waited.append(seconds) or False,
        ), patch.object(self.observer, "_stats", side_effect=read):
            self.observer.start()
            self.observer._thread.join(timeout=2)
            self.assertFalse(self.observer._thread.is_alive())
            summary = self.observer.stop()
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["sample_count"], 1)

    def test_stats_addresses_verified_id_with_bounded_timeout_and_no_stdin(self):
        self.observer._identifier = CONTAINER
        with patch("nipat.execution.performance.subprocess.run", return_value=
                   subprocess.CompletedProcess([], 0, stats(), "")) as process:
            row = self.observer._stats()
        argv = process.call_args.args[0]
        self.assertEqual(argv[-1], CONTAINER)
        self.assertNotIn(NAME, argv)
        self.assertIn("--no-trunc", argv)
        self.assertEqual(process.call_args.kwargs["timeout"], 5)
        self.assertEqual(process.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertGreaterEqual(row["query_seconds"], 0)


class RunnerObserverTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        project = self.root / "project"
        project.mkdir()
        self.layout = ProjectLayout(project, self.root, self.root / "data", self.root / "runs",
                                    project / "compose.yaml")
        self.runner = DockerComposeRunner(self.layout, transport=DockerTransport(),
                                          options=ExecutionOptions(performance_diagnostics=True))
        self.enterContext(patch("nipat.execution.tracking.platform.platform", return_value="test host"))
        self.enterContext(patch.object(self.runner, "_analysis_session", side_effect=lambda: nullcontext()))
        self.enterContext(patch.object(self.runner, "_prepare_runtime", side_effect=self.prepare))
        self.enterContext(patch.object(self.runner, "_describe_bundled_engine"))
        self.enterContext(patch.object(self.runner, "_record_resource_snapshot"))

    def prepare(self):
        self.runner._image_id = IMAGE
        self.runner._record.data["runtime"] = {"image_id": IMAGE}

    def run_case(self, *, code=0, interrupt=False, monitor_error=False, enabled=True, dry_run=False):
        self.runner.options = ExecutionOptions(performance_diagnostics=enabled)
        self.runner.dry_run = dry_run
        run = self.layout.new_run_dir("test", "case")
        process = MagicMock()
        process.stdout = io.StringIO("analysis output\n")
        if interrupt:
            process.stdout = MagicMock()
            process.stdout.__iter__.side_effect = KeyboardInterrupt
        process.wait.return_value = process.poll.return_value = code
        observer = MagicMock()
        observer.stop.return_value = {"status": "completed", "sample_count": 3}
        if monitor_error:
            observer.stop.side_effect = OSError("report unavailable")
        events = []
        observer.stop.side_effect = (OSError("report unavailable") if monitor_error else
                                     lambda: (events.append("stop") or {"status": "completed", "sample_count": 3}))
        error = None
        with redirect_stdout(io.StringIO()), patch("nipat.execution.runner.subprocess.Popen", return_value=process) as launched, patch(
            "nipat.execution.runner.ContainerPerformanceObserver", return_value=observer,
        ) as factory, patch("nipat.execution.runner.inspect_container", return_value=owned()), patch.object(
            self.runner, "_stop_container", side_effect=lambda _: events.append("remove") or {"status": "removed"},
        ):
            try:
                with self.runner.record_run(run, workflow="dnp-call", inputs=[], parameters={},
                                             bundled_workflow="dnp-call"):
                    self.runner.run(["python3", "engine"])
            except (RuntimeExecutionError, KeyboardInterrupt) as exc:
                error = exc
        return json.loads((run / "run.json").read_text()), error, events, factory, launched

    def test_opt_in_requires_engine_capability_but_off_accepts_previous_engines(self):
        self.runner._image_id = IMAGE
        self.runner._record = None
        metadata = {"preparation": {"file_sha256": {}}}
        cases = [metadata, {**metadata, "performance_diagnostics": {
            "interface": "performance-diagnostics-v1", "schema_version": 1,
        }}]
        for description in cases:
            with self.subTest(description=description), patch.object(
                self.runner, "_capture", return_value=json.dumps(description),
            ), patch.object(self.runner, "_validate_engine_description", return_value=description):
                self.runner.options = ExecutionOptions(performance_diagnostics=True)
                with self.assertRaisesRegex(RuntimeExecutionError, "diagnostica prestazioni"):
                    DockerComposeRunner._describe_bundled_engine(self.runner)
                self.runner.options = ExecutionOptions(performance_diagnostics=False)
                self.assertEqual(DockerComposeRunner._describe_bundled_engine(self.runner), description)
        description = {"performance_diagnostics": {
            "interface": "performance-diagnostics-v1", "schema_version": 1,
        }, "preparation": {"file_sha256": {"lib/nipat_scientific/performance.py": "d" * 64}}}
        with patch.object(self.runner, "_capture", return_value=json.dumps(description)), patch.object(
            self.runner, "_validate_engine_description", return_value=description,
        ):
            self.runner.options = ExecutionOptions(performance_diagnostics=True)
            self.assertEqual(DockerComposeRunner._describe_bundled_engine(self.runner), description)

    def test_opt_in_stops_external_observer_before_container_cleanup(self):
        record, error, events, factory, launched = self.run_case()
        self.assertIsNone(error)
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(events, ["stop", "remove"])
        self.assertEqual(record["commands"][0]["performance_diagnostics"]["summary"], "performance/summary.json")
        self.assertEqual(factory.return_value.start.call_count, 1)
        argv = launched.call_args.args[0]
        self.assertTrue(any(part.startswith("NIPAT_PERFORMANCE_DIR=/workspace/runs/case/performance/engine")
                            for part in argv))

    def test_failure_and_cancellation_still_stop_the_observer(self):
        for interrupt, code in ((False, 137), (True, 130)):
            with self.subTest(interrupt=interrupt):
                # Every run needs a fresh directory even after interruption.
                self.layout = ProjectLayout(self.layout.project_dir, self.root,
                                            self.root / "data", self.root / str(code), self.layout.compose_file)
                self.runner.layout = self.layout
                record, error, events, _, _ = self.run_case(code=code, interrupt=interrupt)
                self.assertIsNotNone(error)
                self.assertEqual(events, ["stop", "remove"])
                self.assertEqual(record["status"], "interrupted" if interrupt else "failed")

    def test_optional_monitor_failure_cannot_replace_success_or_scientific_failure(self):
        for code in (0, 137):
            with self.subTest(code=code):
                self.layout = ProjectLayout(self.layout.project_dir, self.root,
                                            self.root / "data", self.root / str(code), self.layout.compose_file)
                self.runner.layout = self.layout
                record, error, events, _, _ = self.run_case(code=code, monitor_error=True)
                self.assertEqual(record["status"], "succeeded" if code == 0 else "failed")
                self.assertEqual(record["commands"][0]["performance_diagnostics"]["status"], "partial")
                self.assertEqual(events, ["remove"])
                if code:
                    self.assertIsInstance(error, RuntimeExecutionError)
                    self.assertIn("137", str(error))
                else:
                    self.assertIsNone(error)

    def test_disabled_and_dry_run_never_start_a_collector(self):
        for enabled, dry in ((False, False), (True, True)):
            with self.subTest(enabled=enabled, dry_run=dry):
                self.layout = ProjectLayout(self.layout.project_dir, self.root, self.root / "data",
                                            self.root / str(enabled), self.layout.compose_file)
                self.runner.layout = self.layout
                record, error, _, factory, launched = self.run_case(enabled=enabled, dry_run=dry)
                self.assertIsNone(error)
                factory.assert_not_called()
                if dry:
                    launched.assert_not_called()
                else:
                    self.assertFalse(any(part.startswith("NIPAT_PERFORMANCE_DIR=")
                                         for part in launched.call_args.args[0]))
                self.assertNotIn("performance_diagnostics", record["commands"][0])


if __name__ == "__main__":
    unittest.main()
