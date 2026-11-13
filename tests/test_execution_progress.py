"""Progress is bounded, meaningful and live while the scientific stdout is quiet."""
from contextlib import redirect_stdout
from dataclasses import replace
import io
from itertools import chain, repeat
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from nipat.errors import RuntimeExecutionError
from nipat.execution.options import ExecutionOptions
from nipat.execution.progress import ProgressObserver, ProgressRenderer, ProgressSnapshot
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.transport import DockerTransport
from nipat.paths import ProjectLayout
from nipat_scientific.progress import INTERFACE, MAX_LINE_BYTES


def event(sequence=1, **changes):
    return dict(schema_version=1, interface=INTERFACE, source_id="a" * 32 + "-10-" + "b" * 12,
                sequence=sequence, event="progress", workflow="dnp-call", step_id="dnp",
                phase="dnp-processing", sample_ids=["sample_0001"], completed=2, total=10,
                unit="loci") | changes


class ProgressReaderTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.now = 10.0
        self.observer = ProgressObserver(self.root, lambda _: None, clock=lambda: self.now)
        self.path = self.root / "source.jsonl"

    def append(self, value):
        with self.path.open("ab") as stream:
            stream.write((json.dumps(value) + "\n").encode())

    def test_partial_last_line_and_duplicate_or_invalid_events(self):
        encoded = json.dumps(event()).encode()
        self.path.write_bytes(b"not-json\n" + encoded[:30])
        self.observer.poll()
        self.assertIsNone(self.observer.snapshot().phase)
        with self.path.open("ab") as stream:
            stream.write(encoded[30:] + b"\n")
        self.observer.poll()
        self.assertEqual(self.observer.snapshot().completed, 2)
        for value in (event(completed=9), event(2, event=[]), event(3, total=1),
                      event(4, sample_ids=["evil\x1b[2J"]), event(4, completed=1), event(4, total=11)):
            self.append(value)
        self.observer.poll()
        self.assertEqual(self.observer.snapshot().completed, 2)
        self.append(event(5, completed=7))
        self.observer.poll()
        self.now = 19.0
        self.assertEqual(self.observer.snapshot().elapsed_seconds, 9.0)
        self.assertEqual(self.observer.snapshot().last_event_age_seconds, 9.0)
        self.assertEqual(self.observer.snapshot().completed, 7)

    def test_oversized_truncated_line_is_discarded_until_its_newline(self):
        self.path.write_bytes(b"x" * (MAX_LINE_BYTES + 2))
        self.observer.poll()
        self.assertLessEqual(len(self.observer.readers[self.path][1]), MAX_LINE_BYTES)
        with self.path.open("ab") as stream:
            stream.write(b"tail\n" + json.dumps(event()).encode() + b"\n")
        self.observer.poll()
        self.assertEqual(self.observer.snapshot().completed, 2)

    def test_read_budget_and_symlinks_are_bounded(self):
        self.path.write_bytes(b"x" * 1000)
        outside = self.root / "outside.txt"
        outside.write_text(json.dumps(event()) + "\n")
        try:
            (self.root / "linked.jsonl").symlink_to(outside)
        except OSError:
            self.skipTest("Creating symbolic links is unavailable on this platform")
        with patch("nipat.execution.progress.MAX_TOTAL_BYTES", 40):
            for _ in range(3):
                self.observer.poll()
        self.assertEqual(self.observer.bytes_read, 40)
        self.assertIsNone(self.observer.snapshot().phase)

    def test_child_end_returns_to_actual_parent_phase(self):
        self.append(event(1, event="start", phase="r-execution"))
        self.append(event(2))
        self.append(event(3, event="end", outcome="succeeded"))
        self.observer.poll()
        self.assertEqual(self.observer.snapshot().phase, "r-execution")
        self.assertFalse(self.observer.snapshot().phase_finished)

    def test_quiet_heartbeat_survives_bad_callback_and_joins_on_cancel(self):
        received, ready = [], threading.Event()
        # Advance the injected clock after construction, independently of host
        # timer resolution; the observer and callback still use a real thread.
        timestamps = chain([10.0], repeat(19.0))
        def callback(state):
            received.append(state)
            if len(received) >= 2:
                ready.set()
            raise ValueError("GUI unavailable")
        observer = ProgressObserver(self.root, callback, interval=.01,
                                    clock=lambda: next(timestamps))
        observer.start()
        self.assertTrue(ready.wait(2))
        observer.stop("cancelled")
        self.assertFalse(observer._thread.is_alive())
        self.assertEqual(received[-1].elapsed_seconds, 9.0)
        self.assertEqual(received[-1].status, "cancelled")

    def test_render_actual_counts_throttle_and_sanitize_without_eta(self):
        lines = []
        renderer = ProgressRenderer(lines.append, sample_names={"sample_0001": "ID16\x1b[2J.bam"},
                                    clock=lambda: self.now)
        state = ProgressSnapshot("running", 61, "dnp-processing", ("sample_0001",), 4, 20, "loci")
        renderer(state)
        renderer(state)
        self.assertEqual(len(lines), 1)
        self.now += 15
        renderer(state)
        self.assertEqual(len(lines), 2)
        self.assertIn("4/20 loci", lines[0])
        self.assertIn("01:01", lines[0])
        self.assertNotIn("\x1b", lines[0])
        self.assertNotIn("%", lines[0])
        self.assertNotIn("stim", lines[0])


    def test_workflow_label_and_step_changes_are_immediate_without_internal_ids(self):
        lines = []
        renderer = ProgressRenderer(lines.append, clock=lambda: self.now)
        state = ProgressSnapshot("running", 61, "r-execution", ("sample_0001",),
                                 workflow="dnp-call", step_id="internal_dnp_one")
        for workflow, label in (("dnp-call", "DNPcall"), ("snp-call", "SNPcall"),
                                ("contamination", "Contamination"), ("cpi", "CPI")):
            renderer(replace(state, workflow=workflow))
            self.assertTrue(lines[-1].startswith(label + ": Calcolo R"))
        self.assertEqual(len(lines), 4)
        renderer(replace(state, workflow="cpi", step_id="internal_cpi_two"))
        self.assertEqual(len(lines), 5)
        renderer(replace(state, workflow="cpi", step_id="internal_cpi_two"))
        self.assertEqual(len(lines), 5)
        self.assertTrue(all("internal_" not in line for line in lines))
        self.assertTrue(all("01:01" in line for line in lines))


class QuietRunnerProgressTests(unittest.TestCase):
    def test_quiet_stdout_progress_without_diagnostics_stops_after_cleanup_on_all_outcomes(self):
        for code, interrupted in ((0, False), (17, False), (130, True)):
            with self.subTest(code=code, interrupted=interrupted), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                project = root / "project"
                project.mkdir()
                run = root / "runs" / "case"
                run.mkdir(parents=True)
                layout = ProjectLayout(project, root, root / "data", root / "runs", project / "compose.yaml")
                snapshots, ready, observers, order = [], threading.Event(), [], []
                # Windows may complete both callbacks within one monotonic
                # timer tick. Keep real heartbeat scheduling but control time.
                timestamps = chain([10.0], repeat(19.0))
                def callback(snapshot):
                    snapshots.append(snapshot)
                    if len(snapshots) >= 2:
                        ready.set()
                    if snapshot.status != "running":
                        order.append("progress-stopped")
                def factory(*args):
                    observer = ProgressObserver(*args, interval=.01,
                                                clock=lambda: next(timestamps))
                    observers.append(observer)
                    return observer
                class QuietStream(io.StringIO):
                    def __next__(self):
                        if not ready.wait(2):
                            raise AssertionError("Progress blocked by quiet stdout")
                        if interrupted:
                            raise KeyboardInterrupt
                        raise StopIteration
                runner = DockerComposeRunner(layout, transport=DockerTransport(),
                    options=ExecutionOptions(performance_diagnostics=False), progress_callback=callback)
                runner._record = MagicMock()
                runner._record.run_dir = run
                runner._record.data = {"commands": [], "run_id": "case", "parameters": {}}
                runner._bundled_workflow = "dnp-call"
                process = MagicMock()
                process.stdout = QuietStream()
                process.wait.return_value = process.poll.return_value = code
                owned = {"owned": True, "availability": "available", "container_id": "a" * 64,
                         "state": {"status": "running", "oom_killed": False}}
                with redirect_stdout(io.StringIO()), patch.object(runner, "_ensure_backend"), \
                        patch.object(runner, "_verify_inputs"), \
                        patch("nipat.execution.runner.ProgressObserver", side_effect=factory), \
                        patch("nipat.execution.runner.ContainerPerformanceObserver") as diagnostics, \
                        patch("nipat.execution.runner.inspect_container", return_value=owned), \
                        patch.object(runner, "_stop_container", side_effect=lambda _: order.append("cleanup")), \
                        patch("nipat.execution.runner.subprocess.Popen", return_value=process) as launched:
                    if interrupted:
                        with self.assertRaises(KeyboardInterrupt):
                            runner._run_command(["python3", "engine"])
                    elif code:
                        with self.assertRaises(RuntimeExecutionError):
                            runner._run_command(["python3", "engine"])
                    else:
                        runner._run_command(["python3", "engine"])
                diagnostics.assert_not_called()
                self.assertEqual(order, ["cleanup", "progress-stopped"])
                self.assertFalse(observers[0]._thread.is_alive())
                self.assertEqual(snapshots[-1].status, "cancelled" if interrupted else "failed" if code else "succeeded")
                self.assertEqual(snapshots[-1].elapsed_seconds, 9.0)
                self.assertIn("NIPAT_PROGRESS_DIR=/workspace/runs/case/progress", launched.call_args.args[0])
                self.assertEqual(runner._record.data["commands"][0]["progress"]["directory"], "progress")
