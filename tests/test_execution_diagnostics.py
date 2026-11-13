"""Resource evidence is captured before cleanup and never guesses the cause of 137."""

import io
import json
from contextlib import contextmanager, nullcontext, redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from nipat.errors import RuntimeExecutionError
from nipat.execution.diagnostics import diagnose, inspect_container, settle_oom_observation
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.transport import DockerTransport
from nipat.paths import ProjectLayout


IMAGE = "sha256:" + "b" * 64
CONTAINER = "a" * 64


def payload(name, labels, *, oom=False, code=0, status="exited"):
    return {"id": CONTAINER, "name": "/" + name, "image": IMAGE, "labels": labels,
            "state": {"status": status, "oom_killed": oom, "exit_code": code,
                      "started_at": "2026-11-03T10:00:00Z", "finished_at": "2026-11-03T10:01:00Z"},
            "limits": {"memory_bytes": 512 * 1024 * 1024, "memory_swap_bytes": 512 * 1024 * 1024,
                       "nano_cpus": 1500000000, "cpu_period": 0, "cpu_quota": 0, "pids_limit": None}}


class ExecutionDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        project = self.directory / "project"
        project.mkdir()
        self.layout = ProjectLayout(project, self.directory, self.directory / "data",
                                    self.directory / "runs", project / "compose.yaml")
        self.runner = DockerComposeRunner(self.layout, transport=DockerTransport())
        self.runner._image_id = IMAGE
        self.enterContext(patch("nipat.execution.tracking.platform.platform", return_value="test host"))
        self.enterContext(patch("nipat.execution.diagnostics.time.sleep"))
        self.enterContext(patch.object(self.runner, "_analysis_session", side_effect=lambda: nullcontext()))
        self.enterContext(patch.object(self.runner, "_prepare_runtime", side_effect=self.prepare))
        self.enterContext(patch.object(self.runner, "_describe_bundled_engine"))
        self.enterContext(patch.object(self.runner, "_record_resource_snapshot", side_effect=self.snapshot))
        self.log = io.StringIO()

    def prepare(self):
        self.runner._image_id = IMAGE
        self.runner._record.data["runtime"] = {"image_id": IMAGE}

    def snapshot(self):
        self.runner._record.data["resource_snapshot"] = {
            "backend": "native", "runtime": {"effective": {"memory_mib": 4096, "cpus": 4}},
        }

    def process(self, code=0, *, interrupt=False):
        process = MagicMock()
        process.stdout = io.StringIO("scientific output\n")
        if interrupt:
            process.stdout = MagicMock()
            process.stdout.__iter__.side_effect = KeyboardInterrupt
        process.wait.return_value = process.poll.return_value = code
        return process

    def run_case(self, code, *, oom=False, missing=False, mismatched=False, interrupt=False,
                 cleanup_failure=False, run_name="case"):
        run = self.layout.new_run_dir("test", run_name)
        process = self.process(code, interrupt=interrupt)
        operations = []
        launched = []

        def start(argv, **kwargs):
            launched.extend(argv)
            self.assertNotIn("--rm", argv)
            return process

        def execute(argv, **kwargs):
            operations.append(list(argv))
            if argv[:3] == ["docker", "container", "inspect"]:
                self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                self.assertLessEqual(kwargs["timeout"], 20)
                if missing:
                    return subprocess.CompletedProcess(argv, 1, "", "Error: No such container")
                labels = dict(item.split("=", 1) for index, item in enumerate(launched)
                              if index and launched[index - 1] == "--label")
                if mismatched:
                    labels["org.nipat.execution-token"] = "unrelated"
                value = payload(argv[3], labels, oom=oom, code=code,
                                status="running" if interrupt else "exited")
                return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")
            self.assertEqual(argv, ["docker", "rm", "--force", "--volumes", CONTAINER])
            if cleanup_failure:
                return subprocess.CompletedProcess(argv, 1, "", "runtime unavailable during cleanup")
            return subprocess.CompletedProcess(argv, 0, CONTAINER, "")

        error = None
        with redirect_stdout(self.log), patch("nipat.execution.runner.subprocess.Popen", side_effect=start), patch(
            "nipat.execution.diagnostics.subprocess.run", side_effect=execute,
        ):
            try:
                with self.runner.record_run(run, workflow="snp-call", inputs=[], parameters={},
                                             bundled_workflow="snp-call"):
                    self.runner.run(["python3", "engine"])
            except (RuntimeExecutionError, KeyboardInterrupt) as exc:
                error = exc
        record = json.loads((run / "run.json").read_text())
        return run, record, error, operations

    def test_success_preserves_measured_limits_and_removes_only_verified_container(self):
        run, record, error, operations = self.run_case(0)
        self.assertIsNone(error)
        self.assertEqual(record["status"], "succeeded")
        stage = record["commands"][0]
        self.assertEqual(stage["container_diagnostics"]["state"]["oom_killed"], False)
        self.assertEqual(stage["container_diagnostics"]["limits"]["memory_bytes"], 512 * 1024 * 1024)
        self.assertEqual(stage["container_diagnostics"]["diagnosis"]["kind"], "completed")
        self.assertEqual(stage["container_cleanup"]["status"], "removed")
        self.assertEqual(operations[0][:3], ["docker", "container", "inspect"])
        self.assertEqual(operations[-1], ["docker", "rm", "--force", "--volumes", CONTAINER])
        self.assertTrue((run / "run-report.html").is_file())
        self.assertEqual(record["resource_snapshot"]["runtime"]["effective"]["memory_mib"], 4096)

    def test_oom_has_explicit_docker_evidence_and_preserves_failure_code(self):
        _, record, error, _ = self.run_case(137, oom=True)
        self.assertIsInstance(error, RuntimeExecutionError)
        self.assertIn("memoria insufficiente", str(error))
        stage = record["commands"][0]
        self.assertEqual(stage["returncode"], 137)
        self.assertEqual(stage["container_diagnostics"]["diagnosis"]["kind"], "oom_confirmed")
        self.assertEqual(stage["container_cleanup"]["status"], "removed")

    def test_137_without_oom_flag_is_not_reported_as_confirmed_memory_failure(self):
        with patch("nipat.execution.diagnostics.time.monotonic", return_value=10.0):
            _, record, error, operations = self.run_case(137)
        self.assertIn("non e confermata", str(error))
        self.assertEqual(record["commands"][0]["container_diagnostics"]["diagnosis"]["kind"],
                         "sigkill_unconfirmed")
        self.assertEqual(sum(argv[:3] == ["docker", "container", "inspect"] for argv in operations), 6)

    def test_delayed_oom_flag_is_retained_before_cleanup_and_error_reporting(self):
        def delayed(runner, name, labels, *, timeout):
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 2)
            return {"availability": "available", "owned": True, "container_id": CONTAINER,
                    "state": {"status": "exited", "oom_killed": True, "exit_code": 137}}
        with patch("nipat.execution.diagnostics.inspect_container", side_effect=delayed) as refreshed:
            _, record, error, operations = self.run_case(137)
        self.assertEqual(refreshed.call_count, 1)
        self.assertIn("memoria insufficiente", str(error))
        stage = record["commands"][0]
        self.assertEqual(stage["returncode"], 137)
        self.assertEqual(stage["container_diagnostics"]["diagnosis"]["kind"], "oom_confirmed")
        self.assertEqual(stage["container_cleanup"]["status"], "removed")
        self.assertEqual(operations[-1], ["docker", "rm", "--force", "--volumes", CONTAINER])

    def test_failed_or_replaced_reinspection_preserves_original_identity_for_cleanup(self):
        for number, updated in enumerate((
            {"availability": "unavailable", "owned": False},
            {"availability": "identity_mismatch", "owned": False},
            {"availability": "available", "owned": True, "container_id": "c" * 64,
             "state": {"status": "exited", "oom_killed": True}},
        )):
            with self.subTest(updated=updated), patch(
                "nipat.execution.diagnostics.inspect_container", return_value=updated,
            ) as refreshed:
                _, record, error, operations = self.run_case(137, run_name=f"reinspection-{number}")
            self.assertEqual(refreshed.call_count, 1)
            self.assertIn("non e confermata", str(error))
            stage = record["commands"][0]
            self.assertEqual(stage["container_diagnostics"]["container_id"], CONTAINER)
            self.assertEqual(stage["container_diagnostics"]["diagnosis"]["kind"], "sigkill_unconfirmed")
            self.assertEqual(stage["container_cleanup"]["status"], "removed")
            self.assertEqual(operations[-1], ["docker", "rm", "--force", "--volumes", CONTAINER])

    def test_oom_settle_budget_includes_inspection_and_skips_unrelated_outcomes(self):
        original = {"availability": "available", "owned": True, "container_id": CONTAINER,
                    "state": {"status": "exited", "oom_killed": False}}
        for observation, code in ((original, 0), (original, 17),
                                   ({**original, "state": {"status": "running", "oom_killed": False}}, 137),
                                   ({**original, "state": {"status": "exited", "oom_killed": True}}, 137)):
            with self.subTest(observation=observation, code=code), patch(
                "nipat.execution.diagnostics.inspect_container",
            ) as refreshed:
                self.assertIs(settle_oom_observation(self.runner, "name", {}, observation, code), observation)
                refreshed.assert_not_called()
        with patch("nipat.execution.diagnostics.time.monotonic", side_effect=[10.0, 10.0, 10.2, 12.1]), patch(
            "nipat.execution.diagnostics.inspect_container", return_value=original,
        ) as refreshed:
            self.assertIs(settle_oom_observation(self.runner, "name", {}, original, -9), original)
            self.assertEqual(refreshed.call_count, 1)
            self.assertAlmostEqual(refreshed.call_args.kwargs["timeout"], 1.8)

    def test_cleanup_failure_preserves_confirmed_oom_evidence_and_original_error(self):
        _, record, error, operations = self.run_case(137, oom=True, cleanup_failure=True)
        self.assertIn("memoria insufficiente", str(error))
        self.assertEqual(record["status"], "failed")
        stage = record["commands"][0]
        self.assertEqual(stage["returncode"], 137)
        self.assertEqual(stage["container_diagnostics"]["diagnosis"]["kind"], "oom_confirmed")
        self.assertEqual(stage["container_cleanup"]["status"], "not_confirmed")
        self.assertEqual(operations[-1], ["docker", "rm", "--force", "--volumes", CONTAINER])

    def test_missing_container_records_unknown_cause_without_reusing_its_name(self):
        _, record, error, operations = self.run_case(137, missing=True)
        self.assertIn("non e confermata", str(error))
        stage = record["commands"][0]
        self.assertEqual(stage["container_diagnostics"]["availability"], "absent")
        self.assertEqual(stage["container_cleanup"]["status"], "absent")
        self.assertEqual(len(operations), 1)

    def test_replaced_unowned_container_is_not_stopped_or_removed(self):
        _, record, _, operations = self.run_case(7, mismatched=True)
        stage = record["commands"][0]
        self.assertEqual(stage["container_diagnostics"]["availability"], "identity_mismatch")
        self.assertEqual(stage["container_cleanup"]["status"], "not_confirmed")
        self.assertEqual(len(operations), 1)

    def test_cancellation_keeps_snapshot_without_calling_it_an_oom(self):
        _, record, error, operations = self.run_case(130, interrupt=True)
        self.assertIsInstance(error, KeyboardInterrupt)
        self.assertEqual(record["status"], "interrupted")
        stage = record["commands"][0]
        self.assertEqual(stage["container_diagnostics"]["diagnosis"]["kind"], "interrupted")
        self.assertEqual(stage["container_diagnostics"]["state"]["status"], "running")
        self.assertEqual(operations[-1], ["docker", "rm", "--force", "--volumes", CONTAINER])

    def test_inspection_rejects_untrusted_or_incomplete_data(self):
        name, labels = "nipat-run-" + "c" * 32, {"org.nipat.execution-token": "d" * 32}
        for alteration in ("image", "token", "boolean", "invalid-json"):
            with self.subTest(alteration=alteration):
                value = payload(name, labels.copy())
                if alteration == "image":
                    value["image"] = "sha256:" + "f" * 64
                elif alteration == "token":
                    value["labels"]["org.nipat.execution-token"] = "other"
                elif alteration == "boolean":
                    value["state"]["oom_killed"] = "false"
                raw = "invalid" if alteration == "invalid-json" else json.dumps(value)
                with patch("nipat.execution.diagnostics.subprocess.run", return_value=
                           subprocess.CompletedProcess([], 0, raw, "")):
                    observation = inspect_container(self.runner, name, labels)
                self.assertFalse(observation["owned"])
                self.assertNotIn("container_id", observation)
                self.assertNotEqual(diagnose(observation, 137, interrupted=False)["kind"], "oom_confirmed")

    def test_extra_docker_fields_and_unrelated_labels_are_not_persisted(self):
        name, labels = "nipat-run-" + "c" * 32, {"org.nipat.execution-token": "d" * 32}
        value = payload(name, {**labels, "secret": "do-not-store"})
        value.update(env=["TOKEN=do-not-store"], mounts=["/private/unrelated"])
        value["state"]["unexpected"] = "do-not-store"
        with patch("nipat.execution.diagnostics.subprocess.run", return_value=
                   subprocess.CompletedProcess([], 0, json.dumps(value), "")):
            observation = inspect_container(self.runner, name, labels)
        self.assertTrue(observation["owned"])
        self.assertNotIn("do-not-store", json.dumps(observation))
        self.assertNotIn("/private/unrelated", json.dumps(observation))

    def test_report_failure_does_not_replace_scientific_success(self):
        with patch("nipat.run_report.write_run_report", side_effect=OSError("cannot write report")):
            _, record, error, _ = self.run_case(0)
        self.assertIsNone(error)
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(record["report_error"]["type"], "OSError")
        self.assertIn("Resoconto leggibile non creato", self.log.getvalue())

    def test_report_failure_keeps_the_original_scientific_error(self):
        with patch("nipat.run_report.write_run_report", side_effect=OSError("cannot write report")):
            _, record, error, _ = self.run_case(137, oom=True)
        self.assertIsInstance(error, RuntimeExecutionError)
        self.assertIn("memoria insufficiente", str(error))
        self.assertEqual(record["error"]["type"], "RuntimeExecutionError")
        self.assertEqual(record["report_error"]["type"], "OSError")

    def test_resource_probe_failure_is_unknown_and_does_not_abort_computation(self):
        with patch.object(self.runner, "_record_resource_snapshot", side_effect=lambda:
                          DockerComposeRunner._record_resource_snapshot(self.runner)), patch(
            "nipat.resources.ResourceManager.snapshot", side_effect=OSError("probe unavailable"),
        ):
            _, record, error, _ = self.run_case(0)
        self.assertIsNone(error)
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(record["resource_snapshot"], {"available": False, "reason": "OSError"})

    def test_resource_session_covers_prepare_cleanup_and_final_report_on_failure(self):
        from nipat.run_report import write_run_report
        active = 0
        observed = []
        original_stop = self.runner._stop_container

        @contextmanager
        def session(layout):
            nonlocal active
            self.assertEqual(layout, self.layout)
            active += 1
            try:
                yield
            finally:
                active -= 1

        def prepare():
            self.assertGreater(active, 0)
            observed.append("prepare")
            self.prepare()

        def stop(identifier):
            self.assertGreater(active, 0)
            observed.append("cleanup")
            return original_stop(identifier)

        def report(run):
            self.assertGreater(active, 0)
            observed.append("report")
            return write_run_report(run)

        with patch.object(self.runner, "_analysis_session", side_effect=lambda:
                          DockerComposeRunner._analysis_session(self.runner)), patch(
            "nipat.resources.analysis_session", side_effect=session,
        ), patch.object(self.runner, "_prepare_runtime", side_effect=prepare), patch.object(
            self.runner, "_stop_container", side_effect=stop,
        ), patch("nipat.run_report.write_run_report", side_effect=report):
            _, record, error, _ = self.run_case(137)
        self.assertIsInstance(error, RuntimeExecutionError)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(observed, ["prepare", "cleanup", "report"])
        self.assertEqual(active, 0)

    def test_dry_run_starts_no_resource_session_observation_or_runtime_process(self):
        self.runner.dry_run = True
        run = self.layout.new_run_dir("test", "dry")
        # Exercise the real dry-run guard rather than the setup's session stub.
        with patch.object(self.runner, "_analysis_session",
                          side_effect=lambda: DockerComposeRunner._analysis_session(self.runner)), patch(
            "nipat.resources.analysis_session",
        ) as session, patch("nipat.execution.runner.inspect_container") as observation, patch(
            "nipat.execution.runner.subprocess.Popen",
        ) as process, redirect_stdout(self.log):
            with self.runner.record_run(run, workflow="snp-call", inputs=[], parameters={},
                                         bundled_workflow="snp-call"):
                self.runner.run(["python3", "engine"])
        session.assert_not_called()
        observation.assert_not_called()
        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
