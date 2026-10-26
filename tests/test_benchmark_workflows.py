import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_workflows.py"
spec = importlib.util.spec_from_file_location("benchmark_workflows", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkReportTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
