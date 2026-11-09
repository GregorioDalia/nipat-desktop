"""Foreground POSIX signal checks; these do not qualify a macOS guest VM."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import select
import signal
import sys
import tempfile
import time
import unittest


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mac_launcher_signals", PROJECT / "installer/macos/launch.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


@unittest.skipUnless(sys.platform in {"linux", "darwin"}, "POSIX foreground process-group signals")
class MacLauncherSignalTests(unittest.TestCase):
    def test_restores_signal_handler_after_child_exit_and_spawn_failure(self):
        previous = signal.getsignal(signal.SIGINT)
        self.assertEqual(launcher.run_foreground(
            [sys.executable, "-c", "raise SystemExit(17)"], env=dict(os.environ)), 17)
        self.assertIs(signal.getsignal(signal.SIGINT), previous)
        with self.assertRaises(OSError):
            launcher.run_foreground(["/nonexistent/nipat-child"], env=dict(os.environ))
        self.assertIs(signal.getsignal(signal.SIGINT), previous)

    def test_cli_survives_terminal_ctrl_c_until_explicit_exit(self):
        import fcntl
        import pty

        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "activity.lock"
            lock_path.touch()
            script = (
                "import importlib.util, pathlib, os, sys, fcntl; "
                f"p=pathlib.Path({str(PROJECT)!r}); "
                "s=importlib.util.spec_from_file_location('launcher',p/'installer/macos/launch.py'); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                f"root=pathlib.Path({directory!r}); "
                "lease=(root/'activity.lock').open('rb'); "
                "fcntl.flock(lease,fcntl.LOCK_SH); "
                "env=m.environment(p,p.parent,dict(os.environ,TERM='dumb')); "
                "env.update(NIPAT_DATA_DIR=str(root/'data'),NIPAT_RUNS_DIR=str(root/'runs')); "
                "command=[sys.executable,'-I','-B','-c',m.CLI_CODE,str(p/'src'),'--dry-run','wizard']; "
                "code=m.run_foreground(command,env=env); "
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

            def require_lease():
                # A separate file description must remain unable to start a
                # package transaction while the foreground client is alive.
                with lock_path.open("rb") as stream:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

            try:
                until(b"Scelta:")
                require_lease()
                os.write(descriptor, b"\x03")
                until(b"Menu principale. Per uscire scegliere 0.")
                # Give the supervisor the normal subprocess interrupt grace
                # period before requiring a still-live interactive session.
                time.sleep(.4)
                require_lease()
                os.write(descriptor, b"1\n1\n")
                until(b"Percorso del primo BAM:")
                os.write(descriptor, b"\x03")
                until(b"Operazione annullata. Ritorno al menu principale.")
                require_lease()
                os.write(descriptor, b"0\n")
                until(b"CLIENT_RETURNED 0")
                _, status = os.waitpid(child, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                with lock_path.open("rb") as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertFalse((Path(directory) / "runs").exists())
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
