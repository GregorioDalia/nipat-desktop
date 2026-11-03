import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from nipat.activity import activity_session, _authorized_setup_child, windows_activity_path
from nipat.errors import NipatError


class ActivityTests(unittest.TestCase):
    def test_source_checkout_has_no_linux_package_lease(self):
        with tempfile.TemporaryDirectory() as directory, patch('nipat.activity.sys.platform', 'linux'):
            with activity_session(project_dir=Path(directory)):
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_windows_lease_is_shared_noninheritable_and_released_on_failure(self):
        kernel = MagicMock()
        kernel.CreateFileW.return_value = 123
        with tempfile.TemporaryDirectory() as directory, patch('nipat.activity.sys.platform', 'win32'), \
                patch('nipat.activity._authorized_setup_child', return_value=False), \
                patch('nipat.activity._windows_kernel', return_value=kernel), \
                patch.dict(os.environ, {'LOCALAPPDATA': str(Path(directory).resolve())}):
            with self.assertRaisesRegex(RuntimeError, 'analysis failed'):
                with activity_session(project_dir=Path(directory)):
                    raise RuntimeError('analysis failed')
            args = kernel.CreateFileW.call_args.args
            self.assertEqual(args[1:5], (0x80000000, 3, None, 4))
            kernel.CloseHandle.assert_called_once_with(123)

    def test_missing_or_stale_setup_token_does_not_bypass_lease(self):
        with patch.dict(os.environ, {'NIPAT_SETUP_ACTIVITY_TOKEN': '123:' + 'a' * 32}), \
                patch('nipat.activity._windows_ancestors', return_value={456}):
            self.assertFalse(_authorized_setup_child())
        with patch.dict(os.environ, {'NIPAT_SETUP_ACTIVITY_TOKEN': 'forged'}):
            self.assertFalse(_authorized_setup_child())

    def test_live_ancestor_and_event_are_both_required(self):
        kernel = MagicMock()
        kernel.OpenEventW.return_value = 0
        with patch.dict(os.environ, {'NIPAT_SETUP_ACTIVITY_TOKEN': '123:' + 'a' * 32}), \
                patch('nipat.activity._windows_ancestors', return_value={123}), \
                patch('nipat.activity._windows_kernel', return_value=kernel):
            self.assertFalse(_authorized_setup_child())
            kernel.OpenEventW.return_value = 321
            self.assertTrue(_authorized_setup_child())
            kernel.CloseHandle.assert_called_once_with(321)

    @unittest.skipUnless(sys.platform == 'win32', 'requires Windows kernel sharing semantics')
    def test_actual_second_process_blocks_exclusive_update_until_session_exits(self):
        import ctypes
        from nipat.activity import _windows_kernel
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOCALAPPDATA': directory}):
            script = ('import sys; from pathlib import Path; from nipat.activity import activity_session; '
                      'ctx=activity_session(project_dir=Path.cwd()); ctx.__enter__(); '
                      'print("ready", flush=True); sys.stdin.readline(); ctx.__exit__(None,None,None)')
            child = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                kernel = _windows_kernel()
                lock = str(windows_activity_path())
                handle = kernel.CreateFileW(lock, 0xC0000000, 0, None, 4, 0x80, None)
                self.assertEqual(handle, ctypes.c_void_p(-1).value)
                child.communicate('\n', timeout=10)
                handle = kernel.CreateFileW(lock, 0xC0000000, 0, None, 4, 0x80, None)
                self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
                kernel.CloseHandle(handle)
            finally:
                if child.poll() is None:
                    child.terminate(); child.wait(timeout=10)
