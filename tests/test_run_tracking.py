import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.tracking import HASH_LIMIT_BYTES, file_evidence
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout


class RunTrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        project = root / "repo"
        scientific = project / "scientific"
        scientific.mkdir(parents=True)
        script = scientific / "test.R"
        script.write_text("# fixture\n", encoding="utf-8")
        digest = hashlib.sha256(script.read_bytes()).hexdigest()
        (scientific / "SHA256SUMS").write_text(f"{digest}  test.R\n", encoding="utf-8")
        data = root / "data"
        data.mkdir()
        self.layout = ProjectLayout(project, root, data, root / "runs", project / "compose.yaml")
        self.runner = DockerComposeRunner(self.layout)
        self.input = data / "input.txt"
        self.input.write_text("original data\n", encoding="utf-8")
        self.output = io.StringIO()
        self.addCleanup(patch.stopall)
        patch("nipat.execution.runner.DockerComposeRunner._prepare_runtime", self.prepare).start()

    @staticmethod
    def prepare(runner):
        runner._image_id = "sha256:" + "1" * 64
        runner._record.data["runtime"] = {"image_id": runner._image_id}

    def popen_factory(self, scripts):
        real_popen = subprocess.Popen
        pending = iter(scripts)

        def fake(command, **kwargs):
            self.assertNotIn("--build", command)
            self.assertEqual(command[command.index("--pull") + 1], "never")
            self.assertEqual(kwargs["env"]["NIPAT_RUNTIME_IMAGE"], "sha256:" + "1" * 64)
            return real_popen([sys.executable, "-c", next(pending)], **kwargs)
        return fake

    def record(self, name):
        return json.loads((self.layout.runs_dir / name / "run.json").read_text())

    def test_success_streams_stdout_stderr_and_keeps_input_evidence(self):
        run = self.layout.new_run_dir("test", "success")
        original = self.input.read_bytes()
        with redirect_stdout(self.output), patch(
            "nipat.execution.runner.subprocess.Popen",
            side_effect=self.popen_factory(["import sys; print('out'); print('err', file=sys.stderr)"]),
        ):
            with self.runner.record_run(run, workflow="test", inputs=[self.input], parameters={"x": 2}):
                self.runner.run(["Rscript", "example.R"])
                self.assertEqual(self.record("success")["status"], "running")
        record = self.record("success")
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(record["commands"][0]["returncode"], 0)
        self.assertEqual(record["parameters"], {"x": 2})
        self.assertEqual(record["inputs"][0]["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(self.input.read_bytes(), original)
        log = (run / "execution.log").read_text()
        for message in ("out\n", "err\n"):
            self.assertIn(message, log)
            self.assertIn(message, self.output.getvalue())
        self.assertIsNotNone(record["finished_at"])
        self.assertFalse((run / "run.json.tmp").exists())

    def bam_inputs(self):
        bam = self.layout.data_dir / "sample.bam"
        reference = self.layout.data_dir / "reference.fa"
        for path in (bam, Path(str(bam) + ".bai"), reference, Path(str(reference) + ".fai")):
            path.write_text("fixture\n", encoding="utf-8")
        panel = self.layout.data_dir / "snp.tsv"
        panel.write_text("pos\tref\talt\nchr1:100\tA\tC\n", encoding="utf-8")
        return bam, reference, panel

    def test_second_snp_command_failure_marks_whole_workflow_failed(self):
        bam, reference, panel = self.bam_inputs()
        with redirect_stdout(self.output), patch(
            "nipat.execution.runner.subprocess.Popen",
            side_effect=self.popen_factory(["print('pileup ready')", "import sys; print('R failed'); sys.exit(7)"]),
        ):
            with self.assertRaisesRegex(RuntimeExecutionError, "codice 7"):
                Workflows(self.layout, self.runner).snp_call(
                    bam=bam, reference=reference, panel=panel, run_name="failed-snp"
                )
        record = self.record("failed-snp")
        self.assertEqual(record["status"], "failed")
        self.assertEqual([c["status"] for c in record["commands"]], ["succeeded", "failed"])
        self.assertEqual([c["returncode"] for c in record["commands"]], [0, 7])
        self.assertIn("R failed", (self.layout.runs_dir / "failed-snp" / "execution.log").read_text())

    def test_dry_run_is_planned_and_launches_no_process(self):
        bam, reference, panel = self.bam_inputs()
        self.runner.dry_run = True
        with redirect_stdout(self.output), patch.object(self.runner, "_prepare_runtime") as prepare, patch(
            "nipat.execution.runner.subprocess.Popen"
        ) as popen:
            Workflows(self.layout, self.runner).snp_call(
                bam=bam, reference=reference, panel=panel, run_name="planned"
            )
        prepare.assert_not_called()
        popen.assert_not_called()
        record = self.record("planned")
        self.assertEqual(record["status"], "planned")
        self.assertEqual([c["status"] for c in record["commands"]], ["planned", "planned"])
        self.assertTrue(all(c["returncode"] is None for c in record["commands"]))

    def test_keyboard_interrupt_is_recorded_and_propagated(self):
        run = self.layout.new_run_dir("test", "interrupted")
        with redirect_stdout(self.output), self.assertRaises(KeyboardInterrupt):
            with self.runner.record_run(run, workflow="test", inputs=[self.input], parameters={}):
                raise KeyboardInterrupt()
        self.assertEqual(self.record("interrupted")["status"], "interrupted")
        self.assertIsNone(self.runner._record)

    def test_interrupt_stops_named_container_even_if_client_already_exited(self):
        run = self.layout.new_run_dir("test", "interrupted-client")
        process = MagicMock()
        process.stdout.__iter__.side_effect = KeyboardInterrupt()
        process.poll.return_value = 130
        with redirect_stdout(self.output), patch(
            "nipat.execution.runner.subprocess.Popen", return_value=process
        ), patch.object(self.runner, "_stop_container", return_value={"status": "removed"}) as stop:
            with self.assertRaises(KeyboardInterrupt):
                with self.runner.record_run(run, workflow="test", inputs=[], parameters={}):
                    self.runner.run(["Rscript", "test.R"])
        stop.assert_called_once()
        self.assertTrue(stop.call_args.args[0].startswith("nipat-run-"))
        self.assertEqual(self.record("interrupted-client")["status"], "interrupted")
        self.assertEqual(self.record("interrupted-client")["commands"][0]["returncode"], 130)

    def test_changed_scientific_source_fails_before_runtime(self):
        run = self.layout.new_run_dir("test", "changed-source")
        (self.layout.project_dir / "scientific" / "test.R").write_text("changed\n")
        with redirect_stdout(self.output), patch.object(self.runner, "_prepare_runtime") as prepare:
            with self.assertRaisesRegex(ValidationError, "modificata"):
                with self.runner.record_run(run, workflow="test", inputs=[self.input], parameters={}):
                    self.fail("Must not enter execution")
        prepare.assert_not_called()
        self.assertEqual(self.record("changed-source")["status"], "failed")

    def test_staging_failure_is_recorded(self):
        panel = self.layout.data_dir / "panel.txt"
        panel.write_text("chr1\t100\t101\tAA\tCC\n")
        self.input.write_text("chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\nchr1\t100\t101\t95\t5\t0\n")
        with redirect_stdout(self.output), patch(
            "nipat.execution.workflows.shutil.copy2", side_effect=OSError("disk full")
        ):
            with self.assertRaisesRegex(OSError, "disk full"):
                Workflows(self.layout, self.runner).contamination(
                    inputs=[self.input], panel=panel, run_name="copy-failed"
                )
        record = self.record("copy-failed")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["commands"], [])

    def test_large_input_hash_policy_is_explicit(self):
        large = self.layout.data_dir / "large.bam"
        with large.open("wb") as handle:
            handle.truncate(HASH_LIMIT_BYTES + 1)
        evidence = file_evidence(large)
        self.assertIsNone(evidence["sha256"])
        self.assertIn("exceeds 16 MiB", evidence["hash_note"])
        self.assertEqual(evidence["size_bytes"], HASH_LIMIT_BYTES + 1)

    def test_existing_record_is_never_overwritten(self):
        run = self.layout.new_run_dir("test", "existing")
        (run / "run.json").write_text('{"status":"running"}')
        with self.assertRaises(FileExistsError):
            with self.runner.record_run(run, workflow="test", inputs=[], parameters={}):
                self.fail("Existing evidence must be preserved")
        self.assertEqual(self.record("existing")["status"], "running")


class RuntimeResolutionTests(unittest.TestCase):
    def test_resolves_requested_image_and_pins_compose_execution(self):
        layout = ProjectLayout(Path("."), Path("."), Path("data"), Path("runs"), Path("compose.yaml"))
        runner = DockerComposeRunner(layout)
        image_id = "sha256:" + "a" * 64
        answers = [
            "linux", '{"services":{"scientific":{"image":"test-runtime:tag"}}}',
            json.dumps({"id": image_id, "os": "linux", "architecture": "amd64"}),
            "R version example\nsamtools example",
        ]
        with patch.object(runner, "_capture", side_effect=answers) as capture:
            runner._prepare_runtime()
        self.assertEqual(runner._environment()["NIPAT_RUNTIME_IMAGE"], image_id)
        self.assertEqual(capture.call_args_list[2].args[0][3], "test-runtime:tag")
        self.assertIn(image_id, capture.call_args_list[3].args[0])
        self.assertIn("--pull=never", capture.call_args_list[3].args[0])

    def test_rejects_windows_container_engine(self):
        layout = ProjectLayout(Path("."), Path("."), Path("data"), Path("runs"), Path("compose.yaml"))
        runner = DockerComposeRunner(layout)
        with patch.object(runner, "_capture", return_value="windows") as capture:
            with self.assertRaisesRegex(RuntimeExecutionError, "container Linux"):
                runner._prepare_runtime()
        self.assertEqual(capture.call_count, 1)


if __name__ == "__main__":
    unittest.main()
