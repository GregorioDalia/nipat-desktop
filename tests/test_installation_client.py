"""Maintenance never changes installed components before deliberate handoff."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from nipat.errors import NipatError
from nipat.installation import (
    installation_inventory, maintenance_selection, show_installation, start_maintenance,
)
from nipat.terminal import Terminal


def inventory():
    return {
        "schema_version": 1, "platform": "windows",
        "runtimes": [
            {"id": "active", "name": "active", "path": "/runtime/current", "size_bytes": 20,
             "active": True, "retained": True, "removable": False, "reason": "Attivo"},
            {"id": "old", "name": "old", "path": "/runtime/old", "size_bytes": 10,
             "active": False, "retained": False, "removable": True, "reason": "Precedente"},
        ],
        "cache": [], "backups": [], "warnings": [],
        "recovery": {"id": "current-installation", "recoverable": True, "reason": "Verificato"},
    }


class InstallationClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()

    def test_linux_inspection_never_launches_or_prunes_runtime(self):
        with patch("nipat.installation.sys.platform", "linux"), patch("nipat.installation.subprocess.run") as run:
            result = installation_inventory(self.project)
        self.assertEqual(result["platform"], "linux")
        self.assertFalse(result["recovery"]["recoverable"])
        run.assert_not_called()

    def test_inventory_requires_structured_verified_contract(self):
        for value in (inventory(), {**inventory(), "cache": [{"id": "arbitrary"}]}):
            with self.subTest(value=value), patch("nipat.installation.sys.platform", "win32"), \
                    patch("nipat.installation._command", return_value=["worker"]), \
                    patch("nipat.installation.subprocess.run", return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps(value).encode("utf-8"), b"")):
                if value == inventory():
                    self.assertEqual(installation_inventory(self.project), value)
                else:
                    with self.assertRaises(NipatError):
                        installation_inventory(self.project)

    def test_active_foreign_or_ambiguous_target_cannot_be_removed(self):
        for target in ("active", "foreign"):
            with self.subTest(target=target), self.assertRaises(NipatError):
                maintenance_selection(inventory(), "cleanup", target)
        duplicate = inventory()
        duplicate["cache"] = [dict(duplicate["runtimes"][1])]
        with self.assertRaises(NipatError):
            maintenance_selection(duplicate, "cleanup", "old")
        with self.assertRaises(NipatError):
            maintenance_selection(inventory(), "recover", "previous-version")

    def test_dry_run_menu_never_queries_inventory(self):
        ui = Terminal(read=Mock(), write=Mock())
        with patch("nipat.installation.installation_inventory") as inspect:
            self.assertFalse(show_installation(ui, self.project, dry_run=True))
        inspect.assert_not_called()

    def test_menu_default_confirmation_does_not_start_worker(self):
        ui = Terminal(read=Mock(side_effect=["1", "", "0"]), write=Mock())
        with patch("nipat.installation.installation_inventory", return_value=inventory()), \
                patch("nipat.installation.start_maintenance") as start:
            self.assertFalse(show_installation(ui, self.project))
        start.assert_not_called()

    def test_menu_starts_only_selected_confirmed_operation(self):
        ui = Terminal(read=Mock(side_effect=["1", "1"]), write=Mock())
        with patch("nipat.installation.installation_inventory", return_value=inventory()), \
                patch("nipat.installation.start_maintenance", return_value=self.project / "result.json") as start:
            self.assertTrue(show_installation(ui, self.project))
        start.assert_called_once_with(self.project, "cleanup", "old")

    def worker(self, *, acknowledgement=None):
        process = Mock()
        process.poll.return_value = None

        def create(command, **kwargs):
            self.assertIs(kwargs["shell"], False)
            ready = Path(command[command.index("-ReadyFile") + 1])
            if acknowledgement is not None:
                ready.write_text(json.dumps(acknowledgement), encoding="utf-8")
            return process

        self.enterContext(patch("nipat.installation._command", return_value=["worker"]))
        self.enterContext(patch("nipat.installation.installation_inventory", return_value=inventory()))
        launch = self.enterContext(patch("nipat.installation.subprocess.Popen", side_effect=create))
        return process, launch

    def test_matching_acknowledgement_hands_off_without_claiming_completion(self):
        process, launch = self.worker(acknowledgement={"schema_version": 1,
            "status": "waiting-for-client", "operation": "cleanup", "target_id": "old"})
        result = start_maintenance(self.project, "cleanup", "old")
        self.assertEqual(result.name, "result.json")
        self.assertFalse(result.exists())
        self.assertTrue((result.parent / "ready.json").is_file())
        self.assertIn("-WaitForProcessId", launch.call_args.args[0])
        process.terminate.assert_not_called()

    def test_wrong_target_acknowledgement_cancels_waiting_worker(self):
        process, _ = self.worker(acknowledgement={"schema_version": 1,
            "status": "waiting-for-client", "operation": "cleanup", "target_id": "active"})
        with self.assertRaisesRegex(NipatError, "non valida"):
            start_maintenance(self.project, "cleanup", "old")
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=10)
        markers = list((self.project / ".runtime" / "maintenance").glob("*/cancelled.json"))
        self.assertEqual(len(markers), 1)

    def test_timeout_cancels_waiter_even_if_cancellation_marker_cannot_be_written(self):
        process, _ = self.worker()
        with patch("nipat.installation.time.monotonic", side_effect=[0, 121]), \
                patch.object(Path, "write_text", side_effect=OSError("disk full")), \
                self.assertRaisesRegex(NipatError, "non ha confermato"):
            start_maintenance(self.project, "cleanup", "old")
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=10)

    def test_target_is_revalidated_before_worker_launch(self):
        process, launch = self.worker()
        updated = inventory()
        updated["runtimes"][1]["removable"] = False
        with patch("nipat.installation.installation_inventory", return_value=updated), \
                self.assertRaises(NipatError):
            start_maintenance(self.project, "cleanup", "old")
        launch.assert_not_called()
        process.terminate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
