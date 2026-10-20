"""Exercise Windows argv/path boundaries without requiring WSL on the test host."""

import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path, PureWindowsPath
from unittest.mock import MagicMock, patch

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.mounts import InputMounts
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.transport import DockerTransport, WslDockerTransport, _windows_path
from nipat.paths import ProjectLayout


class WslTransportTests(unittest.TestCase):
    def test_native_is_default_and_preserves_arguments_and_paths(self):
        with patch.dict(os.environ, {}, clear=True):
            transport = DockerTransport.from_environment()
        argv = ["docker", "compose", "-f", r"D:\NIPAT app\compose.yaml"]
        with patch("nipat.execution.transport.subprocess.run") as run:
            self.assertEqual(transport.command(argv, {}), argv)
            self.assertEqual(transport.host_path(argv[-1]), argv[-1])
            self.assertIsNone(transport.ensure_command())
        run.assert_not_called()

    def test_configuration_selects_only_explicit_supported_backend_and_safe_distro(self):
        with patch.dict(os.environ, {
            "NIPAT_BACKEND": "wsl", "NIPAT_WSL_DISTRO": "NIPAT-Test_2.0",
        }):
            self.assertEqual(DockerTransport.from_environment().distro, "NIPAT-Test_2.0")
        with patch.dict(os.environ, {"NIPAT_BACKEND": "remote"}):
            with self.assertRaisesRegex(ValidationError, "NIPAT_BACKEND"):
                DockerTransport.from_environment()
        for invalid in ("", "-name", "name space", "name;command", "a\n", "a" * 65):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                WslDockerTransport(invalid)

    def test_live_path_uses_wslpath_once_and_preserves_special_characters(self):
        transport = WslDockerTransport("NIPAT-Runtime")
        source = r"D:\Caso è, $VALUE & friends\sample.bam"
        translated = "/custom-drive/d/Caso è, $VALUE & friends/sample.bam"
        with patch("nipat.execution.transport._drive_type", return_value=3) as drive, patch(
            "nipat.execution.transport.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, translated + "\n", ""),
        ) as run:
            self.assertEqual(transport.host_path(source), translated)
            self.assertEqual(transport.host_path(source), translated)
        drive.assert_called_once_with("D:\\")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], [
            "wsl.exe", "--distribution", "NIPAT-Runtime", "--user", "root", "--exec",
            "wslpath", "-a", "-u", source,
        ])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_relative_paths_are_canonicalized_before_crossing_bridge(self):
        transport = WslDockerTransport("NIPAT-Runtime", dry_run=True)
        with patch(
            "nipat.execution.transport._resolve_relative_windows_path",
            return_value=r"C:\cases\previous\..\sample è.tsv",
        ) as resolve, patch("nipat.execution.transport._drive_type", return_value=3):
            self.assertEqual(transport.host_path(r".\sample è.tsv"), "/mnt/c/cases/sample è.tsv")
        resolve.assert_called_once_with(r".\sample è.tsv")

    def test_unc_device_control_characters_and_network_drives_fail_without_wsl(self):
        with patch("nipat.execution.transport.subprocess.run") as run:
            for path in (r"\\server\share\file", r"\\?\C:\file", "//server/share/file", "C:\\bad\nfile"):
                with self.subTest(path=path), self.assertRaises(ValidationError):
                    WslDockerTransport("NIPAT-Runtime").host_path(path)
            for drive_type in (0, 2, 4, 5):
                with patch("nipat.execution.transport._drive_type", return_value=drive_type):
                    with self.assertRaisesRegex(ValidationError, "disco locale fisso"):
                        WslDockerTransport("NIPAT-Runtime").host_path(r"Z:\sample.bam")
        run.assert_not_called()

    def test_dry_run_is_explicit_and_never_launches_wsl(self):
        transport = WslDockerTransport("NIPAT-Runtime", dry_run=True)
        with patch("nipat.execution.transport._drive_type", return_value=3), patch(
            "nipat.execution.transport.subprocess.run"
        ) as run:
            self.assertEqual(transport.host_path(r"C:\A $B & è,c\file.txt"), "/mnt/c/A $B & è,c/file.txt")
        self.assertEqual(transport.metadata["path_mapping"], "planned_default_mnt")
        run.assert_not_called()

    def test_bridge_environment_is_allowlisted_and_scientific_argv_is_opaque(self):
        transport = WslDockerTransport("NIPAT-Runtime", dry_run=True)
        scientific = ["docker", "run", "image", "Rscript", "-e", 'cat("$x; &")', r"C:\keep\opaque"]
        with patch("nipat.execution.transport._drive_type", return_value=3):
            command = transport.command(scientific, {
                "NIPAT_DATA_DIR": r"D:\Dati è & $var, test", "NIPAT_RUNTIME_IMAGE": "sha256:123",
                "NIPAT_UID": "1001", "DOCKER_HOST": "tcp://remote:2375",
                "DOCKER_CONTEXT": "external", "PRIVATE_TOKEN": "secret", "WSLENV": "PRIVATE_TOKEN",
            })
        self.assertEqual(command[:8], [
            "wsl.exe", "--distribution", "NIPAT-Runtime", "--user", "root", "--exec", "env", "-i",
        ])
        self.assertEqual(command[-len(scientific):], scientific)
        self.assertIn("NIPAT_DATA_DIR=/mnt/d/Dati è & $var, test", command)
        self.assertIn("NIPAT_RUNTIME_IMAGE=sha256:123", command)
        self.assertIn("DOCKER_HOST=unix:///var/run/docker.sock", command)
        self.assertIn("NIPAT_UID=0", command)
        self.assertFalse(any("secret" in value or "remote:2375" in value for value in command))

    def test_failed_path_translation_is_actionable(self):
        with patch("nipat.execution.transport._drive_type", return_value=3), patch(
            "nipat.execution.transport.subprocess.run",
            return_value=subprocess.CompletedProcess([], 1, "", "not mounted"),
        ):
            with self.assertRaisesRegex(RuntimeExecutionError, "not mounted"):
                WslDockerTransport("NIPAT-Runtime").host_path(r"D:\sample.bam")


class WslRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        project = root / "application"
        (project / "scientific").mkdir(parents=True)
        script = project / "scientific" / "test.R"
        script.write_text("# fixture\n", encoding="utf-8")
        digest = hashlib.sha256(script.read_bytes()).hexdigest()
        (project / "scientific" / "SHA256SUMS").write_text(f"{digest}  test.R\n")
        (project / "compose.yaml").write_text("services: {}\n")
        self.layout = ProjectLayout(project, root, root / "data", root / "runs", project / "compose.yaml")
        self.source = root / "original è $VAR & comma,.txt"
        self.source.write_text("original data", encoding="utf-8")
        self.calls = []
        self.image = "sha256:" + "a" * 64
        # The files remain real temporary fixtures; only the host-OS path boundary
        # is adapted so the same tests can run on Linux CI and Windows.
        def simulated_windows_path(path):
            value = str(path)
            if value.startswith(str(root)):
                relative = Path(path).relative_to(root).parts
                return PureWindowsPath(r"D:\NIPAT test è $var & comma,").joinpath(*relative)
            return _windows_path(path)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"NIPAT_BACKEND": "wsl", "NIPAT_WSL_DISTRO": "NIPAT-Test"}).start()
        patch("nipat.execution.transport._windows_path", side_effect=simulated_windows_path).start()
        patch("nipat.execution.transport._drive_type", return_value=3).start()
        patch("nipat.execution.tracking.platform.platform", return_value="Windows-test-fixture").start()
        self.subprocess_run = patch("nipat.execution.runner.subprocess.run", side_effect=self.execute).start()
        self.runner = DockerComposeRunner(self.layout)
        self.stdout = io.StringIO()

    def execute(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        self.assertEqual(argv[:6], ["wsl.exe", "--distribution", "NIPAT-Test", "--user", "root", "--exec"])
        self.assertNotIn("shell", kwargs)
        if argv[6] == "wslpath":
            path = PureWindowsPath(argv[-1])
            output = "/actual-mount/" + path.drive[0].lower() + "/" + "/".join(path.parts[1:]) + "\n"
        elif argv[-2:] == ["/usr/local/bin/nipat-engine", "ensure"]:
            output = "engine ready\n"
        else:
            docker = argv[argv.index("docker") + 1:]
            if docker[0] == "info":
                output = "linux\n"
            elif docker[:2] == ["compose", "version"]:
                output = "Docker Compose v2\n"
            elif docker[-3:] == ["config", "--format", "json"]:
                output = '{"services":{"scientific":{"image":"runtime:tag"}}}'
            elif docker[:2] == ["image", "inspect"]:
                output = json.dumps({"id": self.image, "os": "linux", "architecture": "amd64"})
            elif docker[0] == "run":
                output = "R version fixture\nsamtools fixture\n"
            elif docker[:2] == ["rm", "--force"] or docker[-2:] == ["build", "scientific"]:
                output = ""
            else:
                raise AssertionError(f"Unexpected command: {argv}")
        return subprocess.CompletedProcess(argv, 0, output, "")

    def process(self):
        process = MagicMock()
        process.stdout = io.StringIO("scientific output\n")
        process.wait.return_value = 0
        process.poll.return_value = 0
        return process

    def ensure_calls(self):
        return [argv for argv, _ in self.calls if argv[-2:] == ["/usr/local/bin/nipat-engine", "ensure"]]

    def test_doctor_needs_only_wsl_and_ensures_engine_before_docker(self):
        with redirect_stdout(self.stdout), patch(
            "nipat.execution.runner.shutil.which", return_value="wsl.exe"
        ) as which:
            self.runner.doctor(check_runtime=True)
        which.assert_called_once_with("wsl.exe")
        self.assertEqual(len(self.ensure_calls()), 1)
        self.assertEqual(self.calls[0][0][-2:], ["/usr/local/bin/nipat-engine", "ensure"])
        self.assertEqual(self.calls[0][1]["timeout"], 240)
        self.assertTrue(self.layout.runs_dir.is_dir())

    def test_complete_run_records_actual_argv_original_inputs_and_translated_mounts(self):
        mounts = InputMounts(self.layout)
        target = mounts.bind_file(self.source, target="/workspace/inputs/Mother caso è $X.txt")
        run = self.layout.new_run_dir("test", "wsl-record")
        scientific = ["Rscript", "-e", 'cat("$input & comma,")', str(target)]
        with redirect_stdout(self.stdout), patch(
            "nipat.execution.runner.subprocess.Popen", return_value=self.process()
        ) as popen:
            with self.runner.record_run(run, workflow="test", inputs=[self.source], parameters={}, mounts=mounts):
                self.runner.run(scientific)
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(record["transport"]["wsl_distro"], "NIPAT-Test")
        self.assertEqual(record["runtime"]["backend"], "wsl")
        self.assertEqual(record["commands"][0]["argv"], popen.call_args.args[0])
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-len(scientific):], scientific)
        compose_files = [argv[index + 1] for index, value in enumerate(argv) if value == "-f"]
        self.assertEqual(len(compose_files), 2)
        self.assertTrue(all(value.startswith("/actual-mount/d/") for value in compose_files))
        self.assertIn("NIPAT_RUNTIME_IMAGE=" + self.image, argv)
        self.assertEqual(record["input_mounts"][0]["host_path"], str(self.source))
        override = json.loads((run / "work" / "input-mounts.json").read_text(encoding="utf-8"))
        volume = override["services"]["scientific"]["volumes"][0]
        self.assertTrue(volume["source"].startswith("/actual-mount/d/"))
        self.assertIn("$$VAR & comma,", volume["source"])
        self.assertEqual(volume["target"], str(target).replace("$", "$$"))
        self.assertTrue(volume["read_only"])
        self.assertFalse(volume["bind"]["create_host_path"])
        self.assertEqual(len(self.ensure_calls()), 1)
        self.assertIsNone(self.runner._input_mounts_file)

    def test_each_analysis_rechecks_engine_even_when_wizard_reuses_runner(self):
        with redirect_stdout(self.stdout), patch(
            "nipat.execution.runner.subprocess.Popen", side_effect=lambda *args, **kwargs: self.process()
        ):
            for name in ("first", "after-wsl-stop"):
                run = self.layout.new_run_dir("test", name)
                with self.runner.record_run(run, workflow="test", inputs=[], parameters={}):
                    self.runner.run(["Rscript", "first-stage.R"])
                    self.runner.run(["Rscript", "second-stage.R"])
        self.assertEqual(len(self.ensure_calls()), 2)

    def test_interruption_removes_only_named_container_using_same_backend(self):
        process = MagicMock()
        process.stdout.__iter__.side_effect = KeyboardInterrupt()
        process.poll.return_value = 130
        run = self.layout.new_run_dir("test", "interrupted")
        with redirect_stdout(self.stdout), patch(
            "nipat.execution.runner.subprocess.Popen", return_value=process
        ), self.assertRaises(KeyboardInterrupt):
            with self.runner.record_run(run, workflow="test", inputs=[], parameters={}):
                self.runner.run(["Rscript", "test.R"])
        record = json.loads((run / "run.json").read_text())
        stage = record["commands"][0]
        self.assertEqual(record["status"], "interrupted")
        cleanup = stage["container_cleanup"]
        self.assertEqual(cleanup["status"], "removed")
        self.assertEqual(cleanup["argv"][-4:], ["docker", "rm", "--force", stage["container_name"]])
        self.assertEqual(cleanup["argv"][:4], ["wsl.exe", "--distribution", "NIPAT-Test", "--user"])

    def test_timed_out_probe_cleans_up_its_exact_container(self):
        self.runner._ensure_backend()
        name = "nipat-probe-test"
        original_execute = self.execute
        def timeout_probe(argv, **kwargs):
            if name in argv and "run" in argv:
                raise subprocess.TimeoutExpired(argv, 90)
            return original_execute(argv, **kwargs)
        with redirect_stdout(self.stdout), patch(
            "nipat.execution.runner.subprocess.run", side_effect=timeout_probe
        ), self.assertRaisesRegex(RuntimeExecutionError, "90 secondi"):
            self.runner._capture(["docker", "run", "--name", name, "image", "Rscript"], container_name=name)
        self.assertEqual(self.calls[-1][0][-4:], ["docker", "rm", "--force", name])

    def test_dry_run_writes_planned_evidence_without_starting_any_process(self):
        runner = DockerComposeRunner(self.layout, dry_run=True)
        run = self.layout.new_run_dir("test", "planned")
        mounts = InputMounts(self.layout)
        target = mounts.bind_file(self.source)
        with redirect_stdout(self.stdout), patch("nipat.execution.runner.subprocess.Popen") as popen:
            with runner.record_run(run, workflow="test", inputs=[self.source], parameters={}, mounts=mounts):
                runner.run(["Rscript", "test.R", target])
        popen.assert_not_called()
        self.subprocess_run.assert_not_called()
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "planned")
        self.assertEqual(record["transport"]["path_mapping"], "planned_default_mnt")


if __name__ == "__main__":
    unittest.main()
