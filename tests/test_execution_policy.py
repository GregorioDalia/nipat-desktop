import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.options import ExecutionOptions
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.tracking import HASH_LIMIT_BYTES, file_evidence, verify_input_evidence
from nipat.execution.transport import DockerTransport
from nipat.paths import ProjectLayout


class ExecutionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("nipat.execution.tracking.platform.platform", return_value="test-host"))
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(self.temp)
        self.project = root / "project"
        self.project.mkdir()
        self.layout = ProjectLayout(self.project, root, root / "data", root / "runs",
                                    self.project / "compose.yaml")
        self.runner = DockerComposeRunner(self.layout, transport=DockerTransport(), dry_run=True)

    def test_options_reject_invalid_budgets(self):
        for options in ({"cpus": float("nan")}, {"cpus": True}, {"cpus": 0},
                        {"memory_mb": -1}, {"memory_mb": 128.5}, {"pids_limit": 0},
                        {"input_hashes": "cached"}, {"input_hashes": []}, {"cpus": 10 ** 500}):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                ExecutionOptions(**options)

    def test_optional_budgets_are_preserved_in_compose_and_run_record(self):
        options = ExecutionOptions(input_hashes="full", cpus=1.5, memory_mb=512, pids_limit=256)
        self.runner.options = options
        run = self.layout.new_run_dir("test", "budget")
        with redirect_stdout(io.StringIO()), self.runner.record_run(
            run, workflow="snp-call", inputs=[], parameters={}, bundled_workflow="snp-call",
        ):
            self.runner.run(["python3", "engine"])
        record = json.loads((run / "run.json").read_text())
        compose = json.loads((run / "work" / "engine-compose.json").read_text())
        service = compose["services"]["scientific"]
        self.assertEqual(service["cpus"], 1.5)
        self.assertEqual(service["mem_limit"], 512 * 1024 * 1024)
        self.assertEqual(service["memswap_limit"], service["mem_limit"])
        self.assertEqual(service["pids_limit"], 256)
        self.assertEqual(record["execution_options"], options.as_dict())
        self.assertIsNone(record["input_hash_limit_bytes"])
        self.assertEqual(len(record["run_id"]), 32)
        command = record["commands"][0]["argv"]
        self.assertIn("org.nipat.run-id=" + record["run_id"], command)
        self.assertIn("org.nipat.product=nipat-desktop", command)

    def test_large_inputs_full_mode_really_hashes_and_reports_progress(self):
        path = Path(self.temp) / "large.bam"
        with path.open("wb") as handle:
            handle.truncate(HASH_LIMIT_BYTES + 7)
        progress = Mock()
        evidence = file_evidence(path, mode="full", progress=progress)
        self.assertEqual(evidence["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(progress.call_args.args, (path, path.stat().st_size, path.stat().st_size))
        self.assertGreater(progress.call_count, 2)
        self.assertIsNone(file_evidence(path)["sha256"])

    def test_input_changed_during_checksum_is_rejected(self):
        path = Path(self.temp) / "changed.txt"
        path.write_bytes(b"a" * (1024 * 1024 + 1))
        changed = False

        def modify(_path, completed, _total):
            nonlocal changed
            if completed and not changed:
                changed = True
                with path.open("ab") as handle:
                    handle.write(b"b")

        with self.assertRaisesRegex(ValidationError, "durante"):
            file_evidence(path, mode="full", progress=modify)

    def test_full_content_verification_does_not_trust_matching_metadata(self):
        path = Path(self.temp) / "changed.txt"
        path.write_text("AAAA")
        original = file_evidence(path, mode="full")
        path.write_text("BBBB")
        now = file_evidence(path, mode="full")
        expected = {**now, "sha256": original["sha256"]}
        with self.assertRaisesRegex(ValidationError, "Contenuto"):
            verify_input_evidence(expected)

    def test_checksum_can_be_cancelled(self):
        path = Path(self.temp) / "input.txt"
        path.write_text("input")
        with self.assertRaises(KeyboardInterrupt):
            file_evidence(path, mode="full", progress=Mock(side_effect=KeyboardInterrupt))

    def test_cancelled_full_checksum_keeps_interrupted_run_and_starts_no_process(self):
        path = Path(self.temp) / "input.txt"
        path.write_text("input")
        run = self.layout.new_run_dir("test", "checksum-cancelled")
        self.runner.options = ExecutionOptions(input_hashes="full")
        with redirect_stdout(io.StringIO()), patch.object(
            self.runner, "_hash_progress", side_effect=KeyboardInterrupt,
        ), patch("nipat.execution.runner.subprocess.Popen") as process:
            with self.assertRaises(KeyboardInterrupt):
                with self.runner.record_run(run, workflow="snp-call", inputs=[path], parameters={},
                                             bundled_workflow="snp-call"):
                    self.fail("Cancelled provenance must not enter scientific execution")
        process.assert_not_called()
        record = json.loads((run / "run.json").read_text())
        self.assertEqual(record["status"], "interrupted")
        self.assertIsNotNone(record["finished_at"])

    def test_modified_input_prevents_process_launch(self):
        path = Path(self.temp) / "input.txt"
        path.write_text("original")
        run = self.layout.new_run_dir("test", "changed-before")
        with redirect_stdout(io.StringIO()), patch("nipat.execution.runner.subprocess.Popen") as process:
            with self.assertRaisesRegex(ValidationError, "Input modificato"):
                with self.runner.record_run(run, workflow="snp-call", inputs=[path], parameters={},
                                             bundled_workflow="snp-call"):
                    path.write_text("different")
                    self.runner.run(["python3", "engine"])
        process.assert_not_called()
        self.assertEqual(json.loads((run / "run.json").read_text())["status"], "failed")

    def test_modified_input_after_execution_is_not_reported_as_success(self):
        path = Path(self.temp) / "input.txt"
        path.write_text("original")
        run = self.layout.new_run_dir("test", "changed-after")
        with redirect_stdout(io.StringIO()), self.assertRaises(ValidationError):
            with self.runner.record_run(run, workflow="snp-call", inputs=[path], parameters={},
                                         bundled_workflow="snp-call"):
                path.write_text("different")
        record = json.loads((run / "run.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertIn("ValidationError", record["error"]["type"])

    def test_failed_exited_client_still_stops_container_preserving_exit_code(self):
        for cleanup_status in ("removed", "absent", "not_confirmed"):
            with self.subTest(cleanup_status=cleanup_status):
                self.runner.dry_run = False
                process = Mock()
                process.stdout = io.StringIO("client disconnected\n")
                process.wait.return_value = process.poll.return_value = 7
                with redirect_stdout(io.StringIO()), patch(
                    "nipat.execution.runner.subprocess.Popen", return_value=process,
                ), patch.object(self.runner, "_stop_container", return_value={
                    "status": cleanup_status,
                }) as stop:
                    with self.assertRaisesRegex(RuntimeExecutionError, "codice 7"):
                        self.runner.run(["python3", "engine"])
                stop.assert_called_once()
                self.assertRegex(stop.call_args.args[0], r"^nipat-run-[0-9a-f]{32}$")


if __name__ == "__main__":
    unittest.main()
