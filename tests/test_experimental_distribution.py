"""The portability experiment cannot change the stable installation by accident."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from nipat import __version__
from nipat.activity import windows_activity_path
from nipat.distribution import CHANNEL, WINDOWS_DIRECTORY, is_experimental_version
from nipat.installation import installation_inventory, inventory_lines
from nipat.errors import ValidationError
from nipat.paths import ProjectLayout
from nipat.preferences import Preferences, preferences_path
from nipat.terminal import Terminal
from nipat.storage import validate_managed_directories
from nipat.update_ui import run_updates


class ExperimentalDistributionTests(unittest.TestCase):
    def test_macos_data_cannot_overwrite_runtime_or_application(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = root / "app"
            workspace = root / "workspace"
            with patch.dict(os.environ, {"NIPAT_BACKEND": "lima"}), patch("nipat.storage.Path.home", return_value=root):
                for selected in (workspace, root / ".nipat08" / "lima", workspace / ".runtime", app / "data"):
                    layout = ProjectLayout(app, workspace, selected, root / "results", app / "compose.yaml")
                    with self.subTest(selected=selected), self.assertRaises(ValidationError):
                        validate_managed_directories(layout)
                layout = ProjectLayout(app, workspace, workspace / "data", workspace / "runs", app / "compose.yaml")
                validate_managed_directories(layout)

    def test_installer_and_client_use_same_isolated_identity(self):
        root = Path(__file__).resolve().parents[1]
        profile = json.loads((root / "installer/windows/install-profile.json").read_text())
        self.assertEqual(profile["channel"], CHANNEL)
        self.assertEqual(profile["data_dir_name"], WINDOWS_DIRECTORY)
        self.assertNotEqual(profile["channel"], "desktop")
        self.assertTrue(is_experimental_version(__version__))

    def test_experimental_updater_never_contacts_feed_or_handoff(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            layout = ProjectLayout(root / "app", root, root / "data", root / "runs", root / "compose.yaml")
            client, handoff, read = Mock(), Mock(), Mock()
            messages = []
            ui = Terminal(read=read, write=messages.append)
            for startup in (False, True):
                self.assertFalse(run_updates(ui, layout, Preferences(), client=client,
                                             handoff=handoff, startup=startup,
                                             current_version="0.8.0a1"))
            client.check.assert_not_called()
            client.download.assert_not_called()
            handoff.assert_not_called()
            read.assert_not_called()
            self.assertIn("separata dalla versione stabile", "\n".join(messages))

    def test_windows_preferences_and_lease_never_touch_stable_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stable = root / "NIPAT-Desktop"
            stable.mkdir()
            sentinel = stable / "preferences.json"
            sentinel.write_text('{"stable":true}')
            with patch.dict(os.environ, {"LOCALAPPDATA": folder}, clear=True), \
                    patch("nipat.preferences.sys.platform", "win32"):
                self.assertEqual(preferences_path(), root / WINDOWS_DIRECTORY / "preferences.json")
                self.assertEqual(windows_activity_path(), root / WINDOWS_DIRECTORY / "activity.lock")
            self.assertEqual(sentinel.read_text(), '{"stable":true}')
            self.assertEqual(list(stable.iterdir()), [sentinel])

    def test_macos_preferences_and_inventory_use_macos_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            with patch.dict(os.environ, {}, clear=True), patch("nipat.preferences.sys.platform", "darwin"), \
                    patch("nipat.preferences.Path.home", return_value=home):
                expected = home / "Library/Application Support/NIPAT-Experimental08/preferences.json"
                self.assertEqual(preferences_path(), expected)
                inventory = installation_inventory(home)
            self.assertEqual(inventory["platform"], "macos")
            self.assertIn("Lima", " ".join(inventory_lines(inventory)))
            self.assertNotIn("APT", " ".join(inventory_lines(inventory)))
            self.assertFalse(expected.exists())
