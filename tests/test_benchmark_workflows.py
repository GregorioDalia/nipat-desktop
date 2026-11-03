import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_workflows.py"
spec = importlib.util.spec_from_file_location("benchmark_workflows", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkReportTests(unittest.TestCase):
    def _workflow(self, run, *, log="steps/dnp/command.log", start="2026-11-03T10:00:00+00:00",
                  finish="2026-11-03T10:00:12.250000+00:00"):
        workflow = run / "output" / "workflow"
        workflow.mkdir(parents=True)
        state = {"schema_version": 1, "steps": [
            {"id": "dnp", "workflow": "dnp-call", "status": "succeeded", "log": log,
             "started_utc": start, "finished_utc": finish},
            {"id": "contamination", "workflow": "contamination", "status": "succeeded",
             "started_utc": "2026-11-03T10:00:13Z", "finished_utc": "2026-11-03T10:00:15Z"},
        ]}
        (workflow / "workflow-state.json").write_text(json.dumps(state), encoding="utf-8")
        return workflow

    def test_real_failed_child_keeps_partial_run_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = root / "run"
            script = (
                "import json,pathlib,sys; p=pathlib.Path(sys.argv[1]);p.mkdir();"
                "(p/'run.json').write_text(json.dumps({'status':'failed','runtime':{'image_id':'fixture'}}));"
                "(p/'execution.log').write_text('Peak RAM (MB): 12.5\\n');"
                "(p/'partial.txt').write_text('preserve');sys.exit(7)"
            )
            result = benchmark.run_case([sys.executable, "-c", script, str(run)], run, root / "command.log")
            self.assertEqual(result["returncode"], 7)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["r_reported_peak_ram_mb"], 12.5)
            self.assertGreater(result["wall_seconds"], 0)
            self.assertGreater(result["run_files_bytes"], 0)
            self.assertEqual((run / "partial.txt").read_text(), "preserve")

    def test_case_does_not_replace_existing_command_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            log = root / "command.log"
            log.write_text("previous evidence")
            with self.assertRaises(FileExistsError):
                benchmark.run_case([sys.executable, "-c", "raise SystemExit(0)"], root / "run", log)
            self.assertEqual(log.read_text(), "previous evidence")

    def test_invalid_run_record_remains_reportable_after_child_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = root / "run"
            script = (
                "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.mkdir();"
                "(p/'run.json').write_text('{partial');sys.exit(3)"
            )
            result = benchmark.run_case([sys.executable, "-c", script, str(run)], run, root / "command.log")
            self.assertEqual(result["returncode"], 3)
            self.assertEqual(result["status"], "invalid_record")
            self.assertTrue(result["record_error"])
            self.assertEqual((run / "run.json").read_text(), "{partial")

    def test_automatic_workflow_reads_dnp_log_and_preserves_resource_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = root / "run"
            workflow = self._workflow(run)
            log = workflow / "steps" / "dnp" / "command.log"
            log.parent.mkdir(parents=True)
            log.write_text("Peak RAM (MB): 134.5\nPeak RAM usage (MB): 140.25\n", encoding="utf-8")
            snapshot = {"backend": "lima", "host": {"memory_mib": 16384},
                        "runtime": {"effective": {"memory_mib": 8192}}}
            (run / "run.json").write_text(json.dumps({
                "status": "succeeded", "resource_snapshot": snapshot,
                "execution_options": {"memory_mb": 4096},
            }), encoding="utf-8")
            (run / "execution.log").write_text("Workflow step dnp: dnp-call\n", encoding="utf-8")
            result = benchmark.run_case([sys.executable, "-c", "pass"], run, root / "command.log")
            self.assertEqual(result["r_reported_peak_ram_mb"], 140.25)
            self.assertEqual(result["resource_snapshot"], snapshot)
            self.assertEqual(result["execution_options"], {"memory_mb": 4096})
            self.assertIsNone(result["workflow_evidence_error"])
            self.assertEqual([step["duration_seconds"] for step in result["workflow_steps"]], [12.25, 2])
            self.assertEqual(result["workflow_steps"][0]["r_reported_peak_ram_mb"], 140.25)
            self.assertIn("preparation", result["workflow_steps"][0]["duration_scope"])
            self.assertEqual(log.read_text(encoding="utf-8"),
                             "Peak RAM (MB): 134.5\nPeak RAM usage (MB): 140.25\n")

    def test_missing_step_log_and_unfinished_timing_remain_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder) / "run"
            self._workflow(run, finish=None)
            steps, error = benchmark._workflow_evidence(run)
            self.assertIsNone(error)
            self.assertIsNone(steps[0]["r_reported_peak_ram_mb"])
            self.assertIsNone(steps[0]["duration_seconds"])
            self.assertTrue(steps[0]["log_error"])

    def test_missing_plan_state_is_distinct_from_a_standalone_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = root / "run"
            run.mkdir()
            (run / "run.json").write_text(json.dumps({
                "status": "failed", "workflow": "dnp-contamination",
            }), encoding="utf-8")
            result = benchmark.run_case([sys.executable, "-c", "pass"], run, root / "command.log")
            self.assertEqual(result["workflow_steps"], [])
            self.assertIn("unavailable", result["workflow_evidence_error"])
            self.assertEqual(benchmark._workflow_evidence(run), ([], None))

    def test_step_log_cannot_escape_workflow_or_read_absolute_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root / "outside.log"
            outside.write_text("Peak RAM (MB): 999\n", encoding="utf-8")
            for number, path in enumerate(("../../../outside.log", "../execution.log",
                                           str(outside.resolve()), "C:\\outside.log")):
                with self.subTest(path=path):
                    run = root / str(number)
                    self._workflow(run, log=path)
                    steps, error = benchmark._workflow_evidence(run)
                    self.assertIsNone(error)
                    self.assertIsNone(steps[0]["r_reported_peak_ram_mb"])
                    self.assertTrue(steps[0]["log_error"])

    def test_linked_workflow_state_is_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = self._workflow(root / "outside")
            run = root / "run"
            (run / "output").mkdir(parents=True)
            try:
                (run / "output" / "workflow").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Creating symbolic links is unavailable on this platform")
            steps, error = benchmark._workflow_evidence(run)
            self.assertEqual(steps, [])
            self.assertIn("Linked", error)

    def test_malformed_workflow_state_remains_reportable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for number, content in enumerate(("{partial", "[]", '{"schema_version":1,"steps":[null]}')):
                with self.subTest(content=content):
                    run = root / str(number)
                    workflow = self._workflow(run)
                    (workflow / "workflow-state.json").write_text(content, encoding="utf-8")
                    steps, error = benchmark._workflow_evidence(run)
                    self.assertEqual(steps, [])
                    self.assertTrue(error)

    def test_invalid_or_clock_reversed_step_times_are_not_invented(self):
        for start, finish in ((None, None), ("invalid", "invalid"),
                              ("2026-11-03T10:00:00", "2026-11-03T10:00:10"),
                              ("2026-11-03T10:00:10Z", "2026-11-03T10:00:00Z")):
            with self.subTest(start=start, finish=finish):
                self.assertIsNone(benchmark._step_seconds({"started_utc": start, "finished_utc": finish}))


if __name__ == "__main__":
    unittest.main()
