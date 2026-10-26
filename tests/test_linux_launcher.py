"""Preparation safeguards for the packaged native Linux launcher."""
from contextlib import nullcontext
import hashlib
import importlib.util
import io
import json
import os
import select
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nipat_linux_launcher", PROJECT / "installer/linux/launch.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
SOURCE_ID = "sha256:" + "a" * 64
LOADED_ID = "sha256:" + "b" * 64


class LinuxLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / "app"
        self.data = self.root / "private data" / launcher.DIRECTORY
        self.state = self.root / "private state" / launcher.DIRECTORY
        self.distribution = self.app / ".distribution"
        self.distribution.mkdir(parents=True)
        self.source = self.app / "source.txt"
        self.source.write_bytes(b"immutable-source")
        self.archive = self.distribution / "scientific.tar.gz"
        self.archive.write_bytes(b"verified-export")
        self.manifest = {
            "schema_version": 1, "version": "0.6.0", "release_tag": "v0.6.0",
            "installation_profile": {"channel": "desktop"},
            "source_commit": "a" * 40, "runtime_image": SOURCE_ID,
            "source_sha256": {"source.txt": launcher.digest(self.source)},
            "assets": {"scientific_image": {
                "file": self.archive.name, "size": self.archive.stat().st_size,
                "sha256": launcher.digest(self.archive),
            }},
        }
        self.manifest_path = self.distribution / "installer-manifest.json"
        self.write_manifest()
        self.environment = launcher.clean_environment(self.app, self.data, self.state, {})

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def preparation(self, *, cli_status=0, force=False, present=True, docker_output=None):
        result = subprocess.CompletedProcess([], 0,
            docker_output or "Loaded image ID: " + LOADED_ID + "\n", "")
        with patch.object(launcher, "setup_lock", return_value=nullcontext()), \
                patch.object(launcher, "verify_daemon"), \
                patch.object(launcher, "docker", return_value=result) as load, \
                patch.object(launcher, "image_present", return_value=present), \
                patch.object(launcher, "run_cli", return_value=cli_status) as cli, \
                patch("sys.stdout", new_callable=io.StringIO):
            image = launcher.ensure_ready(self.app, self.data, self.state, self.environment, force=force)
        return image, load, cli

    def test_same_archive_may_resolve_to_different_local_immutable_id(self):
        image, load, cli = self.preparation()
        self.assertEqual(image, LOADED_ID)
        self.assertNotEqual(image, SOURCE_ID)
        self.assertEqual(load.call_args.args[0], ["image", "load", "--input", str(self.archive)])
        self.assertEqual([call.args[1] for call in cli.call_args_list],
                         [["doctor", "--runtime"], ["self-test"]])
        self.assertTrue(all(call.args[2]["NIPAT_RUNTIME_IMAGE"] == LOADED_ID
                            for call in cli.call_args_list))
        record = json.loads((self.state / "state.json").read_text())
        self.assertEqual(record["phase"], "ready")
        self.assertEqual(record["source_runtime_image"], SOURCE_ID)
        self.assertEqual(record["resolved_runtime_image"], LOADED_ID)
        self.assertEqual(record["runtime_archive_sha256"], launcher.digest(self.archive))

    def test_normal_launch_reuses_verified_binding_without_loading(self):
        self.preparation()
        _, load, cli = self.preparation()
        load.assert_not_called()
        cli.assert_not_called()

    def test_desktop_state_and_data_are_separate_from_preview(self):
        inherited = {"XDG_DATA_HOME": str(self.root / "private data"),
                     "XDG_STATE_HOME": str(self.root / "private state")}
        previous = []
        for base in inherited.values():
            marker = Path(base) / "nipat-05-preview" / "preserved.txt"
            marker.parent.mkdir(parents=True)
            marker.write_bytes(b"previous installation")
            previous.append(marker)
        data, state = launcher.user_paths(inherited)
        self.assertEqual(data, self.data)
        self.assertEqual(state, self.state)
        self.assertEqual(data.name, "nipat-desktop")
        self.preparation()
        self.assertTrue(all(marker.read_bytes() == b"previous installation" for marker in previous))
        self.assertEqual(json.loads((state / "state.json").read_text())["channel"], "desktop")

    def test_preview_ready_record_cannot_be_reused_by_desktop(self):
        self.preparation()
        state_path = self.state / "state.json"
        record = json.loads(state_path.read_text())
        record["channel"] = "preview-0.5"
        state_path.write_text(json.dumps(record))
        _, load, cli = self.preparation()
        self.assertEqual(load.call_count, 1)
        self.assertEqual(cli.call_count, 2)
        self.assertEqual(json.loads(state_path.read_text())["channel"], "desktop")

    def test_removed_cached_image_is_loaded_and_verified_again(self):
        self.preparation()
        result = subprocess.CompletedProcess([], 0, "Loaded image ID: " + LOADED_ID, "")
        with patch.object(launcher, "setup_lock", return_value=nullcontext()), \
                patch.object(launcher, "verify_daemon"), \
                patch.object(launcher, "docker", return_value=result) as load, \
                patch.object(launcher, "image_present", side_effect=[False, True]), \
                patch.object(launcher, "run_cli", return_value=0) as cli, \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(launcher.ensure_ready(self.app, self.data, self.state, self.environment), LOADED_ID)
        self.assertEqual(load.call_count, 1)
        self.assertEqual(cli.call_count, 2)

    def test_daemon_access_failure_prevents_checks_and_loading(self):
        with patch.object(launcher, "setup_lock", return_value=nullcontext()), \
                patch.object(launcher, "verify_daemon", side_effect=launcher.SetupError("no access")), \
                patch.object(launcher, "docker") as load, \
                patch.object(launcher, "run_cli") as cli:
            with self.assertRaisesRegex(launcher.SetupError, "no access"):
                launcher.ensure_ready(self.app, self.data, self.state, self.environment)
        load.assert_not_called()
        cli.assert_not_called()

    def test_explicit_setup_rechecks_archive_and_runs_checks(self):
        self.preparation()
        _, load, cli = self.preparation(force=True)
        self.assertEqual(load.call_count, 1)
        self.assertEqual(cli.call_count, 2)

    def test_changed_manifest_reprepares_before_execution(self):
        self.preparation()
        self.manifest["source_commit"] = "c" * 40
        self.write_manifest()
        _, load, cli = self.preparation()
        self.assertEqual(load.call_count, 1)
        self.assertEqual(cli.call_count, 2)
        self.assertEqual(json.loads((self.state / "state.json").read_text())["source_commit"], "c" * 40)

    def test_failure_is_not_ready_and_retry_is_complete(self):
        with self.assertRaises(launcher.SetupError):
            self.preparation(cli_status=2)
        self.assertEqual(json.loads((self.state / "state.json").read_text())["phase"], "failed")
        _, load, cli = self.preparation()
        self.assertEqual(load.call_count, 1)
        self.assertEqual(cli.call_count, 2)
        self.assertEqual(json.loads((self.state / "state.json").read_text())["phase"], "ready")

    def test_corrupt_archive_is_rejected_before_docker_load(self):
        self.archive.write_bytes(b"changed-archive")
        with patch.object(launcher, "setup_lock", return_value=nullcontext()), \
                patch.object(launcher, "verify_daemon"), patch.object(launcher, "docker") as docker, \
                patch.object(launcher, "run_cli") as cli, patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(launcher.SetupError, "non integro"):
                launcher.ensure_ready(self.app, self.data, self.state, self.environment)
        docker.assert_not_called()
        cli.assert_not_called()
        self.assertEqual(json.loads((self.state / "state.json").read_text())["phase"], "failed")

    def test_modified_application_is_rejected_before_loading(self):
        self.source.write_bytes(b"modified")
        with patch.object(launcher, "setup_lock", return_value=nullcontext()), \
                patch.object(launcher, "verify_daemon"), patch.object(launcher, "docker") as docker, \
                patch("sys.stdout", new_callable=io.StringIO):
            with self.assertRaisesRegex(launcher.SetupError, "modificato"):
                launcher.ensure_ready(self.app, self.data, self.state, self.environment)
        docker.assert_not_called()

    def test_environment_does_not_inherit_docker_or_application_overrides(self):
        inherited = {
            "NIPAT_BACKEND": "wsl", "NIPAT_WSL_DISTRO": "unexpected",
            "NIPAT_RUNTIME_IMAGE": "arbitrary:tag", "NIPAT_DATA_DIR": "/private/other",
            "NIPAT_UID": "0", "DOCKER_HOST": "tcp://remote:2375", "DOCKER_CONTEXT": "remote",
            "DOCKER_CONFIG": "/private/config", "DOCKER_TLS_VERIFY": "1",
            "COMPOSE_FILE": "malicious.yaml", "COMPOSE_PROJECT_NAME": "unexpected",
            "PYTHONPATH": "/private/injected", "PYTHONHOME": "/private/python",
            "PATH": "/private/bin", "HOME": "/home/user", "TERM": "xterm",
        }
        result = launcher.clean_environment(self.app, self.data, self.state, inherited)
        self.assertEqual(inherited["DOCKER_CONTEXT"], "remote")
        self.assertEqual(result["DOCKER_HOST"], launcher.SOCKET)
        self.assertEqual(result["DOCKER_CONFIG"], str(self.state / "docker-config"))
        self.assertEqual(result["NIPAT_BACKEND"], "native")
        self.assertEqual(result["NIPAT_DATA_DIR"], str(self.data / "data"))
        for key in ("NIPAT_UID", "NIPAT_RUNTIME_IMAGE", "NIPAT_WSL_DISTRO", "DOCKER_CONTEXT",
                    "DOCKER_TLS_VERIFY", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "PYTHONPATH", "PYTHONHOME"):
            self.assertNotIn(key, result)
        self.assertEqual(result["TERM"], "xterm")
        self.assertEqual(result["PATH"], "/usr/bin:/bin")

    def test_relative_xdg_directory_is_not_accepted(self):
        for key in ("XDG_DATA_HOME", "XDG_STATE_HOME"):
            with self.subTest(key=key), self.assertRaisesRegex(launcher.SetupError, "assoluto"):
                launcher.user_paths({key: "relative"})

    def test_manifest_rejects_path_traversal_and_wrong_channel(self):
        cases = [
            ("asset", "../outside.tar.gz"), ("source", "../outside"),
            ("source", "/outside"), ("source", "foo/../outside"),
            ("source", "foo\\outside"), ("channel", "stable"), ("channel", "preview-0.5"),
        ]
        original = json.dumps(self.manifest)
        for kind, value in cases:
            self.manifest = json.loads(original)
            if kind == "asset":
                self.manifest["assets"]["scientific_image"]["file"] = value
            elif kind == "source":
                self.manifest["source_sha256"] = {value: "a" * 64}
            else:
                self.manifest["installation_profile"]["channel"] = value
            self.write_manifest()
            with self.subTest(kind=kind, value=value), self.assertRaises(launcher.SetupError):
                launcher.load_manifest(self.app)

    def test_manifest_rejects_other_release_families(self):
        for version in ("0.4.1", "0.5.0a1", "0.8.0", "1.0.0", "0.7.0dev1", "0.7.0a"):
            self.manifest.update(version=version, release_tag="v" + version)
            self.write_manifest()
            with self.subTest(version=version), self.assertRaises(launcher.SetupError):
                launcher.load_manifest(self.app)

    def test_manifest_accepts_supported_desktop_series_with_exact_tag(self):
        for version in ("0.6.0", "0.6.1rc2", "0.7.0a1", "0.7.0b2", "0.7.0rc1", "0.7.0"):
            self.manifest.update(version=version, release_tag="v" + version)
            self.write_manifest()
            with self.subTest(version=version):
                actual, _ = launcher.load_manifest(self.app)
                self.assertEqual(actual["version"], version)
                self.manifest["release_tag"] = "v0.6.0" if version != "0.6.0" else "v0.7.0"
                self.write_manifest()
                with self.assertRaises(launcher.SetupError):
                    launcher.load_manifest(self.app)

    def test_receipt_requires_one_untagged_loaded_id(self):
        self.assertEqual(launcher.loaded_image("progress\nLoaded image ID: " + LOADED_ID), LOADED_ID)
        for output in ("", "Loaded image: arbitrary:tag", "Loaded image ID: sha256:bad",
                       "Loaded image ID: " + LOADED_ID + "\nLoaded image ID: " + LOADED_ID,
                       "Error loading image\nLoaded image ID: " + LOADED_ID):
            with self.subTest(output=output), self.assertRaises(launcher.SetupError):
                launcher.loaded_image(output)

    def test_daemon_rejects_rootless_userns_and_wrong_platform(self):
        cases = [
            {"OSType": "linux", "Architecture": "x86_64", "SecurityOptions": ["name=rootless"]},
            {"OSType": "linux", "Architecture": "x86_64", "SecurityOptions": ["name=userns"]},
            {"OSType": "windows", "Architecture": "x86_64", "SecurityOptions": []},
            {"OSType": "linux", "Architecture": "aarch64", "SecurityOptions": []},
        ]
        for info in cases:
            result = subprocess.CompletedProcess([], 0, json.dumps(info), "")
            with self.subTest(info=info), patch.object(launcher, "docker", return_value=result) as docker:
                with self.assertRaises(launcher.SetupError):
                    launcher.verify_daemon(self.environment)
                self.assertEqual(docker.call_count, 1)

    def test_image_inspection_cannot_accept_another_image_or_tag(self):
        for output, identifier in ((SOURCE_ID + " linux amd64", LOADED_ID),
                                   (LOADED_ID + " linux arm64", LOADED_ID), ("", "arbitrary:tag"),
                                   ("", None)):
            with patch.object(launcher, "docker", return_value=subprocess.CompletedProcess([], 0, output, "")):
                self.assertFalse(launcher.image_present(identifier, self.environment))

    def test_docker_uses_fixed_local_endpoint_and_no_shell(self):
        completed = subprocess.CompletedProcess([], 0, "ok", "")
        with patch.object(launcher.subprocess, "run", return_value=completed) as run:
            launcher.docker(["image", "inspect", LOADED_ID], self.environment)
        self.assertEqual(run.call_args.args[0][:3], ["/usr/bin/docker", "--host", launcher.SOCKET])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_help_and_version_never_prepare_or_create_user_directories(self):
        with patch.object(launcher, "run_cli", return_value=0) as cli, \
                patch.object(launcher, "ensure_ready") as prepare, \
                patch.object(launcher, "require_host") as host, \
                patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "unused-data"),
                                        "XDG_STATE_HOME": str(self.root / "unused-state")}):
            self.assertEqual(launcher.main(["--help"]), 0)
            self.assertEqual(launcher.main(["--version"]), 0)
        self.assertEqual(cli.call_count, 2)
        prepare.assert_not_called()
        host.assert_not_called()
        self.assertFalse((self.root / "unused-data").exists())
        self.assertFalse((self.root / "unused-state").exists())

    def test_dry_run_does_not_prepare_or_call_docker(self):
        with patch.object(launcher, "require_host"), \
                patch.object(launcher, "load_manifest", return_value=(self.manifest, "c" * 64)), \
                patch.object(launcher, "run_cli", return_value=0) as cli, \
                patch.object(launcher, "ensure_ready") as prepare, \
                patch.object(launcher, "docker") as docker:
            self.assertEqual(launcher.main(["--dry-run", "wizard"]), 0)
        prepare.assert_not_called()
        docker.assert_not_called()
        self.assertEqual(cli.call_args.args[1], ["--dry-run", "wizard"])
        self.assertEqual(cli.call_args.args[2]["NIPAT_RUNTIME_IMAGE"], SOURCE_ID)
        self.assertFalse(self.state.exists())

    def test_cli_arguments_remain_separate_and_python_is_isolated(self):
        arguments = ["contamination", "--input", "/a space/a;$(touch bad).txt"]
        command = launcher.cli_command(self.app, arguments)
        self.assertEqual(command[-len(arguments):], arguments)
        self.assertEqual(command[1:4], ["-I", "-B", "-c"])
        self.assertEqual(command[5], str(self.app / "src"))

    def test_desktop_keeps_errors_visible_without_pausing_direct_cli(self):
        with patch.object(launcher, "launch", return_value=1) as launch, \
                patch.object(launcher.sys.stdin, "isatty", return_value=True), \
                patch("builtins.input", return_value="") as prompt:
            self.assertEqual(launcher.main(["--desktop"]), 1)
            launch.assert_called_once_with([])
            prompt.assert_called_once()
            prompt.reset_mock()
            self.assertEqual(launcher.main(["doctor"]), 1)
            prompt.assert_not_called()

    def test_update_handoff_exits_without_desktop_pause(self):
        with patch.object(launcher, "launch", return_value=85), \
                patch.object(launcher.sys.stdin, "isatty", return_value=True), \
                patch("builtins.input") as prompt:
            self.assertEqual(launcher.main(["--desktop"]), 0)
        prompt.assert_not_called()

    def test_child_receives_real_launcher_pid_not_inherited_value(self):
        environment = launcher.clean_environment(self.app, self.data, self.state,
                                                   {"NIPAT_LAUNCHER_PID": "1"})
        self.assertEqual(environment["NIPAT_LAUNCHER_PID"], str(os.getpid()))

    @unittest.skipUnless(sys.platform == "linux", "Linux file locking")
    def test_concurrent_setup_fails_without_modifying_existing_state(self):
        self.state.mkdir(parents=True)
        marker = self.state / "state.json"
        marker.write_text('{"phase":"preparing"}')
        with launcher.setup_lock(self.state):
            with self.assertRaisesRegex(launcher.SetupError, "altra finestra"):
                with launcher.setup_lock(self.state):
                    self.fail("concurrent setup acquired lock")
        self.assertEqual(marker.read_text(), '{"phase":"preparing"}')

    @unittest.skipUnless(sys.platform == "linux", "Linux file permissions")
    def test_state_log_and_lock_are_private(self):
        self.preparation()
        with launcher.setup_lock(self.state):
            pass
        for name in ("state.json", "setup.log", "setup.lock"):
            self.assertEqual((self.state / name).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)

    @unittest.skipUnless(sys.platform == "linux", "Linux identity")
    def test_root_execution_is_rejected(self):
        with patch.object(launcher.platform, "machine", return_value="x86_64"), \
                patch.object(launcher.platform, "freedesktop_os_release", return_value={"ID": "ubuntu", "VERSION_ID": "24.04"}), \
                patch.object(launcher.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(launcher.SetupError, "senza sudo"):
                launcher.require_host()


@unittest.skipUnless(sys.platform == "linux", "Linux foreground process-group signals")
class LinuxLauncherSignalTests(unittest.TestCase):
    def test_actual_launcher_preserves_wizard_after_ctrl_c_at_menu_and_field(self):
        import pty
        with tempfile.TemporaryDirectory() as directory:
            script = (
                "import importlib.util, pathlib, os; "
                f"p=pathlib.Path({str(PROJECT)!r}); "
                "s=importlib.util.spec_from_file_location('launcher',p/'installer/linux/launch.py'); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                f"root=pathlib.Path({directory!r}); "
                "e=m.clean_environment(p,root/'data',root/'state',dict(os.environ,TERM='dumb')); "
                "code=m.run_cli(p,['--dry-run','wizard'],e); "
                "print('CLIENT_RETURNED',code,flush=True); raise SystemExit(code)"
            )
            child, descriptor = pty.fork()
            if child == 0:
                os.execv(sys.executable, [sys.executable, "-c", script])
            status = None
            output = bytearray()

            def until(marker):
                recent = bytearray()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if select.select([descriptor], [], [], .1)[0]:
                        try:
                            chunk = os.read(descriptor, 65536)
                        except OSError:
                            break
                        if not chunk:
                            break
                        recent.extend(chunk)
                        output.extend(chunk)
                        if marker in recent:
                            return
                self.fail(f"Launcher did not show {marker!r}: {output!r}")

            try:
                until(b"Scelta:")
                os.write(descriptor, b"\x03")
                until(b"Menu principale. Per uscire scegliere 0.")
                os.write(descriptor, b"1\n1\n")
                until(b"Percorso del primo BAM:")
                os.write(descriptor, b"\x03")
                until(b"Operazione annullata. Ritorno al menu principale.")
                os.write(descriptor, b"0\n")
                until(b"CLIENT_RETURNED 0")
                _, status = os.waitpid(child, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                self.assertFalse((Path(directory) / "data/runs").exists())
            finally:
                if status is None:
                    try:
                        os.killpg(child, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    os.waitpid(child, 0)
                os.close(descriptor)


if __name__ == "__main__":
    unittest.main()
