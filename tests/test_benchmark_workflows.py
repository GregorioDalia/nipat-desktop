import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_workflows.py"
spec = importlib.util.spec_from_file_location("benchmark_workflows", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkReportTests(unittest.TestCase):
    def test_new_rss_label_preserves_old_logs_and_does_not_mistake_mean_for_maximum(self):
        log = ("Peak RAM (MB): 12.5\nPeak RAM usage (MB): 20.25\n"
               "Maximum observed R-process RSS (MiB): 30.75\n"
               "Average per-sample maximum observed R-process RSS (MiB): 999.0\n")
        self.assertEqual(benchmark._reported_ram(log), [12.5, 20.25, 30.75])

    def test_benchmark_passes_recorded_parallel_and_block_settings_to_each_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "benchmark"
            with mock.patch.object(benchmark, "_select_bams", return_value=([root / "one.bam"], None)), \
                    mock.patch.object(benchmark, "run_case", return_value={
                        "returncode": 0, "interrupted": False, "status": "succeeded"}) as run:
                code = benchmark.main(["--bamlist", str(root / "bams.txt"),
                    "--reference", str(root / "ref.fa"), "--panel", str(root / "panel.txt"),
                    "--output-dir", str(output), "--sample-counts", "1", "--repeats", "2",
                    "--execution-mode", "serial", "--max-workers", "3",
                    "--dnp-block-mib", "16", "--dnp-block-loci", "32", "--performance-diagnostics"])
            self.assertEqual(code, 0)
            self.assertEqual(run.call_count, 2)
            for call in run.call_args_list:
                command = call.args[0]
                for flag, expected in (("--execution-mode", "serial"), ("--max-workers", "3"),
                                       ("--dnp-block-mib", "16"), ("--dnp-block-loci", "32")):
                    self.assertEqual(command[command.index(flag) + 1], expected)
                    self.assertLess(command.index(flag), command.index("workflow"))
                self.assertIn("--performance-diagnostics", command)
            options = json.loads((output / "benchmark.json").read_text())["options"]
            self.assertEqual(options["execution_mode"], "serial")
            self.assertEqual(options["max_workers"], 3)
            self.assertEqual(options["dnp_block_mib"], 16)
            self.assertEqual(options["dnp_block_loci"], 32)

    def test_invalid_parallel_limit_does_not_create_benchmark_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "benchmark"
            code = benchmark.main(["--bamlist", str(root / "bams.txt"),
                "--reference", str(root / "ref.fa"), "--panel", str(root / "panel.txt"),
                "--output-dir", str(output), "--max-workers", "0"])
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())

    def test_performance_requested_but_missing_is_not_zero_usage(self):
        with tempfile.TemporaryDirectory() as folder:
            value = benchmark._performance_evidence(Path(folder), requested=True)
            self.assertIsNone(value["host"])
            self.assertIsNone(value["engine"])
            self.assertEqual(set(value["errors"]), {"host", "engine"})
            self.assertEqual(benchmark._performance_evidence(Path(folder), requested=False),
                             {"requested": False, "host": None, "engine": None, "errors": {}})

    def test_performance_reads_bounded_summaries_and_rejects_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            engine = root / "performance" / "engine"
            engine.mkdir(parents=True)
            (engine.parent / "summary.json").write_text('{"samples":3}', encoding="utf-8")
            (engine / "summary.json").write_text('{"status":"partial"}', encoding="utf-8")
            value = benchmark._performance_evidence(root, requested=True)
            self.assertEqual(value["host"], {"samples": 3})
            self.assertEqual(value["engine"], {"status": "partial"})
            (engine / "summary.json").write_bytes(b" " * (1024 * 1024 + 1))
            value = benchmark._performance_evidence(root, requested=True)
            self.assertIsNone(value["engine"])
            self.assertEqual(value["errors"], {"engine": "ValueError"})
            (engine / "summary.json").unlink()
            try:
                (engine / "summary.json").symlink_to(engine.parent / "summary.json")
            except OSError:
                return  # Some Windows accounts cannot create symlinks.
            self.assertEqual(benchmark._performance_evidence(root, requested=True)["errors"],
                             {"engine": "ValueError"})

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
