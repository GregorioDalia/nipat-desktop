"""Linux handoff and package transaction coordination, without installing software."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from nipat import linux_update as update
SPEC = importlib.util.spec_from_file_location("linux_update_builder", PROJECT / "scripts/build_linux_installer.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@unittest.skipUnless(sys.platform == "linux", "Linux update handoff")
class LinuxUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "nipat-desktop_0.6.1_amd64.deb"
        self.package.write_bytes(b"verified package fixture")
        self.checksum = hashlib.sha256(self.package.read_bytes()).hexdigest()
        self.size = self.package.stat().st_size
        self.state = self.root / "activity"
        self.state.mkdir()
        self.lock = self.state / "activity.lock"
        self.lock.touch()
        self.marker = self.state / "update-in-progress"
        self.request = self.root / "request.json"
        self.request.write_text(json.dumps({
            "schema_version": 1, "package": str(self.package), "sha256": self.checksum,
            "size": self.size, "parents": [{"pid": 9876, "start": "1234"}],
        }))

    def test_verified_package_rejects_tampering_symlink_and_hardlink(self):
        update.verify_package(self.package, self.checksum, self.size)
        with self.assertRaises(update.LinuxUpdateError):
            update.verify_package(self.package, "0" * 64, self.size)
        alias = self.root / "alias" / self.package.name
        alias.parent.mkdir()
        alias.symlink_to(self.package)
        with self.assertRaises(update.LinuxUpdateError):
            update.verify_package(alias, self.checksum, self.size)
        alias.unlink()
        os.link(self.package, alias)
        with self.assertRaises(update.LinuxUpdateError):
            update.verify_package(self.package, self.checksum, self.size)

    def test_unsupported_distro_is_rejected(self):
        with patch.object(update.platform, "freedesktop_os_release", return_value={"ID": "debian", "VERSION_ID": "12"}), \
                self.assertRaisesRegex(update.LinuxUpdateError, "Ubuntu 24.04"):
            update.require_supported_host()

    def test_prepare_detached_handoff_retains_no_session_file_descriptors(self):
        def acknowledge(command, **kwargs):
            request = json.loads(Path(command[-1]).read_text())
            ready = Path(command[-1]).parent / "ready.json"
            ready.write_text(json.dumps({"schema_version": 1, "worker_pid": 9876,
                                        "parents": request["parents"]}))
            return Mock(poll=Mock(return_value=None))

        with patch.object(update, "require_supported_host"), \
                patch.object(update.os, "geteuid", return_value=1000), \
                patch.object(update.os, "access", return_value=True), \
                patch.object(update, "LOCK", self.lock), patch.object(update, "MARKER", self.marker), \
                patch.object(update, "_cache_directory", return_value=self.root), \
                patch.object(update, "_process_identity", return_value="123"), \
                patch.dict(os.environ, {"NIPAT_LAUNCHER_PID": "5678"}), \
                patch.object(update.subprocess, "Popen", side_effect=acknowledge) as launch:
            result = update.start_linux_update(self.package, self.checksum, self.size,
                                                parent_pid=1234, project_dir=update.APP)
        self.assertTrue(result)
        command = launch.call_args.args[0]
        self.assertEqual(command[:5], [str(update.TERMINAL), "-e", str(update.PYTHON), "-I", "-B"])
        self.assertTrue(launch.call_args.kwargs["close_fds"])
        self.assertTrue(launch.call_args.kwargs["start_new_session"])
        self.assertNotIn("shell", launch.call_args.kwargs)
        request = json.loads(Path(command[-1]).read_text())
        self.assertEqual(request["parents"], [{"pid": 1234, "start": "123"}, {"pid": 5678, "start": "123"}])
        self.assertTrue(Path(command[-3]).is_file())
        self.assertFalse(Path(command[-3]).is_relative_to(update.APP))

    def test_no_privilege_frontend_leaves_actionable_manual_command(self):
        with patch.object(update, "require_supported_host"), \
                patch.object(update.os, "geteuid", return_value=1000), \
                patch.object(update.os, "access", return_value=False), \
                patch.object(update.subprocess, "Popen") as launch, \
                self.assertRaisesRegex(update.LinuxUpdateError, "sudo apt install"):
            update.start_linux_update(self.package, self.checksum, self.size, project_dir=update.APP)
        launch.assert_not_called()
        self.assertTrue(self.package.is_file())

    def test_failed_terminal_cancels_late_worker_and_keeps_application_open(self):
        with patch.object(update, "require_supported_host"), \
                patch.object(update.os, "geteuid", return_value=1000), \
                patch.object(update.os, "access", return_value=True), \
                patch.object(update, "LOCK", self.lock), patch.object(update, "MARKER", self.marker), \
                patch.object(update, "_cache_directory", return_value=self.root), \
                patch.object(update, "_process_identity", return_value="123"), \
                patch.dict(os.environ, {"NIPAT_LAUNCHER_PID": ""}), \
                patch.object(update.subprocess, "Popen", return_value=Mock(poll=Mock(return_value=1))), \
                self.assertRaisesRegex(update.LinuxUpdateError, "NIPAT rimane aperto"):
            update.start_linux_update(self.package, self.checksum, self.size,
                                      parent_pid=1234, project_dir=update.APP)
        pending = list(self.root.glob("handoff-*/request.json"))
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending[0].with_name("cancel").is_file())
        with patch.object(update, "require_supported_host"), patch.object(update.subprocess, "run") as run:
            self.assertEqual(update.run_handoff(pending[0]), 1)
        run.assert_not_called()

    def test_timeout_and_interrupt_cancel_the_pending_handoff(self):
        for outcome in (False, KeyboardInterrupt()):
            with self.subTest(outcome=type(outcome).__name__):
                self.request.unlink(missing_ok=True)
                with patch.object(update, "require_supported_host"), \
                        patch.object(update.os, "geteuid", return_value=1000), \
                        patch.object(update.os, "access", return_value=True), \
                        patch.object(update, "LOCK", self.lock), patch.object(update, "MARKER", self.marker), \
                        patch.object(update, "_cache_directory", return_value=self.root), \
                        patch.object(update, "_process_identity", return_value="123"), \
                        patch.dict(os.environ, {"NIPAT_LAUNCHER_PID": ""}), \
                        patch.object(update.subprocess, "Popen"), \
                        patch.object(update, "_wait_for_acknowledgement", side_effect=outcome if isinstance(outcome, BaseException) else None,
                                     return_value=False), \
                        self.assertRaises(KeyboardInterrupt if isinstance(outcome, BaseException) else update.LinuxUpdateError):
                    update.start_linux_update(self.package, self.checksum, self.size,
                                              parent_pid=1234, project_dir=update.APP)
                self.assertTrue(all(path.with_name("cancel").exists() for path in self.root.glob("handoff-*/request.json")))

    def test_acknowledgement_deadline_is_bounded(self):
        with patch.object(update.time, "monotonic", side_effect=[0, 16]):
            self.assertFalse(update._wait_for_acknowledgement(self.root, [], Mock()))

    def test_cache_parent_symlink_is_rejected_without_changing_target_permissions(self):
        actual = self.root / "actual"
        actual.mkdir(mode=0o755)
        alias = self.root / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(alias)}), \
                self.assertRaisesRegex(update.LinuxUpdateError, "collegamenti simbolici"):
            update._cache_directory()
        self.assertEqual(list(actual.iterdir()), [])
        self.assertEqual(actual.stat().st_mode & 0o777, 0o755)

    def test_source_checkout_does_not_auto_install_system_package(self):
        with patch.object(update, "require_supported_host"), patch.object(update.os, "geteuid", return_value=1000), \
                self.assertRaisesRegex(update.LinuxUpdateError, "pacchetto installato"):
            update.start_linux_update(self.package, self.checksum, self.size, project_dir=self.root)

    def test_handoff_waits_then_installs_prepares_and_reopens_as_original_user(self):
        completed = subprocess.CompletedProcess([], 0)
        with patch.object(update, "require_supported_host"), \
                patch.object(update, "wait_for_parents") as wait, \
                patch.object(update, "_other_sessions_running", return_value=False), \
                patch.object(update, "MARKER", self.marker), \
                patch.object(update.subprocess, "run", return_value=completed) as run:
            self.assertEqual(update.run_handoff(self.request), 0)
        wait.assert_called_once_with([{"pid": 9876, "start": "1234"}], cancel=self.root / "cancel")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands, [
            [str(update.PKEXEC), str(update.APT), "install", "--", str(self.package)],
            ["/usr/bin/nipat", "--setup"], ["/usr/bin/nipat"],
        ])
        self.assertEqual(json.loads((self.root / "state.json").read_text())["phase"], "ready")

    def test_other_session_prevents_apt_or_any_process_termination(self):
        with patch.object(update, "require_supported_host"), patch.object(update, "wait_for_parents"), \
                patch.object(update, "_other_sessions_running", return_value=True), \
                patch.object(update.subprocess, "run") as run:
            self.assertEqual(update.run_handoff(self.request), 1)
        run.assert_not_called()
        self.assertTrue(self.package.exists())

    def test_failed_apt_or_runtime_never_reopens_wizard(self):
        for results, calls in (([1], 1), ([0, 1], 2)):
            with self.subTest(results=results), \
                    patch.object(update, "require_supported_host"), patch.object(update, "wait_for_parents"), \
                    patch.object(update, "_other_sessions_running", return_value=False), \
                    patch.object(update, "MARKER", self.marker), \
                    patch.object(update.subprocess, "run", side_effect=[subprocess.CompletedProcess([], code) for code in results]) as run:
                self.assertEqual(update.run_handoff(self.request), 1)
                self.assertEqual(run.call_count, calls)
                self.assertEqual(json.loads((self.root / "state.json").read_text())["phase"], "failed")

    def test_reused_pid_does_not_block_handoff(self):
        with patch.object(update, "_process_identity", return_value="different"), \
                patch.object(update.time, "sleep") as sleep:
            update.wait_for_parents([{"pid": 1234, "start": "old"}])
        sleep.assert_not_called()

    def test_shared_session_lock_is_visible_to_handoff(self):
        import fcntl
        with self.lock.open("rb") as stream, patch.object(update, "LOCK", self.lock):
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            self.assertTrue(update._other_sessions_running())
        with patch.object(update, "LOCK", self.lock):
            self.assertFalse(update._other_sessions_running())


@unittest.skipUnless(sys.platform == "linux" and shutil.which("flock"), "Linux package flock coordination")
class PackageCoordinationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / "package-state"
        self.hooks = {}
        for name, raw in builder.maintainer_scripts().items():
            # Only fixture destination/owner are changed; actual transaction and
            # lock operations are executed by /bin/sh in separate processes.
            text = raw.decode().replace("state=/var/lib/nipat-desktop", f"state={self.state}")
            text = text.replace('!= 0 ]', f'!= {os.getuid()} ]')
            path = self.root / name
            path.write_text(text)
            self.hooks[name] = path

    def hook(self, name, argument):
        return subprocess.run(["/bin/sh", str(self.hooks[name]), argument], capture_output=True, text=True)

    def test_preinst_and_configure_guard_full_unpack_interval(self):
        import fcntl
        self.assertEqual(self.hook("preinst", "install").returncode, 0)
        lock = self.state / "activity.lock"
        marker = self.state / "update-in-progress"
        inode = lock.stat().st_ino
        self.assertTrue(marker.exists())
        self.assertEqual(self.hook("postinst", "configure").returncode, 0)
        self.assertFalse(marker.exists())
        with lock.open("rb") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            result = self.hook("preinst", "upgrade")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("wait for analyses", result.stderr)
            self.assertFalse(marker.exists())
        self.assertEqual(self.hook("preinst", "upgrade").returncode, 0)
        self.assertTrue(marker.exists())
        # The old package's postrm upgrade must not reopen launch during unpack.
        self.assertEqual(self.hook("postrm", "upgrade").returncode, 0)
        self.assertTrue(marker.exists())
        self.assertEqual(self.hook("postinst", "configure").returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(lock.stat().st_ino, inode)

    def test_removal_refuses_live_session_and_keeps_lock_inode(self):
        import fcntl
        self.assertEqual(self.hook("preinst", "install").returncode, 0)
        self.assertEqual(self.hook("postinst", "configure").returncode, 0)
        lock = self.state / "activity.lock"
        inode = lock.stat().st_ino
        with lock.open("rb") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            self.assertNotEqual(self.hook("prerm", "remove").returncode, 0)
        self.assertEqual(self.hook("prerm", "remove").returncode, 0)
        self.assertTrue((self.state / "update-in-progress").exists())
        self.assertEqual(self.hook("postrm", "purge").returncode, 0)
        self.assertFalse((self.state / "update-in-progress").exists())
        self.assertEqual(lock.stat().st_ino, inode)

    def test_unsafe_symlink_state_is_never_followed(self):
        victim = self.root / "victim"
        victim.mkdir()
        self.state.symlink_to(victim, target_is_directory=True)
        self.assertNotEqual(self.hook("preinst", "install").returncode, 0)
        self.assertEqual(list(victim.iterdir()), [])

    def test_interrupted_update_remains_blocked_until_configure(self):
        self.assertEqual(self.hook("preinst", "install").returncode, 0)
        self.assertEqual(self.hook("postinst", "abort-upgrade").returncode, 0)
        self.assertTrue((self.state / "update-in-progress").exists())
        self.assertEqual(self.hook("postinst", "configure").returncode, 0)
        self.assertFalse((self.state / "update-in-progress").exists())


if __name__ == "__main__":
    unittest.main()
