import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import chdir, redirect_stdout
from dataclasses import replace
from unittest.mock import Mock, patch

from nipat.cli import DEFAULT_ERR_CONST, main
from nipat.errors import ValidationError
from nipat.paths import ProjectLayout
from nipat.preferences import (
    Preferences, PreferencesStore, _path, _validate_windows_storage_path, preferences_path,
)


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "app"
        self.project.mkdir()
        self.layout = ProjectLayout(self.project, self.root, self.root / "data",
                                    self.root / "runs", self.project / "compose.yaml")
        self.store = PreferencesStore(self.root / "settings" / "preferences.json")

    def write_document(self, document):
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text(json.dumps(document), encoding="utf-8")

    def installed_layout(self):
        record = self.project / ".runtime" / "install-layout.json"
        record.parent.mkdir(exist_ok=True)
        data = {
            "schema_version": 1, "installation_channel": "experimental08",
            "app_dir": str(self.project), "runtime_dir": str(self.root / "managed-runtime"),
            "cache_dir": str(self.root / "managed-cache"),
            "data_dir": str(self.layout.data_dir), "runs_dir": str(self.layout.runs_dir),
        }
        record.write_text(json.dumps(data), encoding="utf-8")
        return record, data

    def test_first_launch_reads_defaults_without_creating_directories(self):
        self.assertEqual(self.store.load(), Preferences())
        self.assertEqual(self.store.load().effective_layout(self.layout), self.layout)
        self.assertFalse(self.store.path.parent.exists())
        self.assertFalse(self.layout.data_dir.exists())
        self.assertFalse(self.layout.runs_dir.exists())

    def test_update_preferences_are_opt_in_and_backward_compatible(self):
        self.write_document({"schema_version": 1, "workflows": {}})
        initial = self.store.load()
        self.assertEqual(initial.update_channel, "testing")
        self.assertFalse(initial.check_updates_on_startup)
        changed = replace(initial, update_channel="stable", check_updates_on_startup=True)
        self.store.save(changed)
        self.assertEqual(PreferencesStore(self.store.path).load(), changed)
        self.store.reset()
        self.assertFalse(self.store.load().check_updates_on_startup)

    def test_invalid_update_preferences_are_not_silently_enabled(self):
        for fields in ({"update_channel": "nightly"}, {"update_channel": None},
                       {"check_updates_on_startup": 1}, {"check_updates_on_startup": "false"}):
            with self.subTest(fields=fields):
                self.write_document({"schema_version": 1, **fields})
                with self.assertRaises(ValidationError):
                    self.store.load()

    def test_preferences_survive_a_new_store_and_working_directory(self):
        panel = self.root / "pannello con spazi é.txt"
        with chdir(self.root):
            prefs = (Preferences().with_directories(data_dir="research-data", runs_dir="results")
                     .with_workflow("1", {"mode": "2", "reference": "genome.fa",
                                          "panel": panel, "parallel": "2"})
                     .with_workflow("4", {"mother_prefix": "", "father_prefix": "Father_",
                                          "popfreq": "popfreq.txt", "cutoff_mode": "2",
                                          "cutoffs": [("A", panel)], "err_const": 0.0}))
            self.store.save(prefs)
        with chdir(self.project):
            loaded = PreferencesStore(self.store.path).load()
            self.assertEqual(loaded, prefs)
            self.assertEqual(loaded.data_dir, self.root / "research-data")
            self.assertEqual(loaded.workflow_defaults("1")["reference"], self.root / "genome.fa")
            self.assertEqual(loaded.workflow_defaults("4")["cutoffs"], [("A", panel)])
            self.assertEqual(loaded.workflow_defaults("4")["mother_prefix"], "")
        # Missing reference files are retained and can be corrected in the form.
        self.assertFalse(panel.exists())
        self.assertFalse(loaded.runs_dir.exists())

    def test_effective_directories_use_saved_values_but_explicit_flags_win(self):
        prefs = Preferences(data_dir=self.root / "saved-data", runs_dir=self.root / "saved-runs")
        selected = prefs.effective_layout(self.layout, {"runs_dir": self.root / "flag-runs"})
        self.assertEqual(selected.data_dir, self.root / "saved-data")
        self.assertEqual(selected.runs_dir, self.root / "flag-runs")
        self.assertEqual(selected.project_dir, self.layout.project_dir)
        self.assertEqual(self.layout.runs_dir, self.root / "runs")
        self.assertFalse(selected.runs_dir.exists())
        reset = prefs.with_directories(runs_dir=None)
        self.assertEqual(reset.effective_layout(self.layout).runs_dir, self.layout.runs_dir)
        self.assertEqual(reset.data_dir, prefs.data_dir)

    def test_configured_overlapping_roots_are_rejected_without_creating_them(self):
        for target in (self.project / "results", self.layout.data_dir / "results", self.root):
            with self.subTest(target=target), self.assertRaises(ValidationError):
                Preferences(runs_dir=target).effective_layout(self.layout)
        self.assertFalse((self.project / "results").exists())

    def test_windows_unc_and_device_destinations_are_rejected_before_resolution(self):
        for value in (r"\\server\share\results", "//server/share/results",
                      r"\\?\C:\results", r"\\.\C:\results"):
            with self.subTest(value=value), patch("nipat.preferences.sys.platform", "win32"), \
                    patch("nipat.preferences.Path.resolve") as resolve, \
                    patch("nipat.execution.transport._drive_type") as drive, \
                    patch("nipat.execution.transport.subprocess.run") as process:
                with self.assertRaisesRegex(ValidationError, "UNC|dispositivo"):
                    _path(value, "runs_dir")
                resolve.assert_not_called()
                drive.assert_not_called()
                process.assert_not_called()

    def test_windows_network_and_removable_drives_are_rejected_before_resolution(self):
        for drive_type in (0, 1, 2, 4, 5, 6):
            with self.subTest(drive_type=drive_type), \
                    patch("nipat.preferences.sys.platform", "win32"), \
                    patch("nipat.preferences.Path.resolve") as resolve, \
                    patch("nipat.execution.transport._drive_type", return_value=drive_type), \
                    patch("nipat.execution.transport.subprocess.run") as process:
                with self.assertRaisesRegex(ValidationError, "disco locale fisso"):
                    _path(r"E:\research\results", "data_dir")
                resolve.assert_not_called()
                process.assert_not_called()

    def test_windows_local_fixed_drive_check_does_not_start_wsl(self):
        with patch("nipat.preferences.sys.platform", "win32"), \
                patch("nipat.execution.transport._drive_type", return_value=3) as drive, \
                patch("nipat.execution.transport.subprocess.run") as process:
            _validate_windows_storage_path(Path(r"D:\research\results"))
        drive.assert_called_once_with("D:\\")
        process.assert_not_called()

    def test_windows_destination_is_checked_again_after_link_resolution(self):
        with patch("nipat.preferences.sys.platform", "win32"), \
                patch("nipat.preferences.Path.resolve", return_value=Path(r"\\server\share\results")), \
                patch("nipat.execution.transport._drive_type", return_value=3), \
                patch("nipat.execution.transport.subprocess.run") as process:
            with self.assertRaisesRegex(ValidationError, "UNC"):
                _path(r"D:\linked-results", "runs_dir")
        process.assert_not_called()

    def test_linux_storage_does_not_use_windows_drive_restrictions(self):
        target = self.root / "mounted-results"
        with patch("nipat.preferences.sys.platform", "linux"), \
                patch("nipat.execution.transport._drive_type") as drive:
            prefs = Preferences(runs_dir=target)
            self.assertEqual(prefs.effective_layout(self.layout).runs_dir, target)
        drive.assert_not_called()
        self.assertFalse(target.exists())

    def test_managed_runtime_and_cache_cannot_hold_research_directories(self):
        record, installation = self.installed_layout()
        original = record.read_bytes()
        for role in ("runtime_dir", "cache_dir"):
            managed = Path(installation[role])
            for target in (managed, managed / "results"):
                for field in ("data_dir", "runs_dir"):
                    with self.subTest(role=role, target=target, field=field):
                        with self.assertRaisesRegex(ValidationError, "riservata"):
                            Preferences(**{field: target}).effective_layout(self.layout)
                        self.assertFalse(target.exists())
        self.assertEqual(record.read_bytes(), original)
        # The same custom selection is rechecked after installer relocation.
        selected = self.root / "custom" / "results"
        prefs = Preferences(runs_dir=selected)
        prefs.effective_layout(self.layout)
        installation["cache_dir"] = str(self.root / "custom")
        record.write_text(json.dumps(installation), encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "riservata"):
            prefs.effective_layout(self.layout)

    def test_invalid_installation_metadata_does_not_disable_reserved_path_check(self):
        record, installation = self.installed_layout()
        for content in ("{invalid", json.dumps({**installation, "installation_channel": "preview-0.5"}),
                        json.dumps({**installation, "app_dir": str(self.root / "other-app")}),
                        json.dumps({**installation, "runtime_dir": "/"}),
                        json.dumps({**installation, "runtime_dir": installation["cache_dir"]})):
            with self.subTest(content=content):
                record.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValidationError, "setup NIPAT"):
                    Preferences().effective_layout(self.layout)

    def test_validation_rejects_unknown_fields_and_unsafe_values_without_saving(self):
        invalid = [
            {"schema_version": True}, {"schema_version": 2},
            {"schema_version": 1, "runtime_image": "other"},
            {"schema_version": 1, "runs_dir": "relative/results"},
            {"schema_version": 1, "data_dir": 42},
            {"schema_version": 1, "workflows": {"9": {}}},
            {"schema_version": 1, "workflows": {"1": {"bam": "sample.bam"}}},
            {"schema_version": 1, "workflows": {"4": {"pairs": "A:A"}}},
            {"schema_version": 1, "workflows": {"1": {"parallel": True}}},
            {"schema_version": 1, "workflows": {"2": {"mode": "3"}}},
            {"schema_version": 1, "workflows": {"4": {"mother_prefix": "../sample"}}},
            {"schema_version": 1, "workflows": {"4": {"err_const": True}}},
            {"schema_version": 1, "workflows": {"4": {"err_const": -1.0}}},
            {"schema_version": 1, "workflows": {"4": {"err_const": float("nan")}}},
            {"schema_version": 1, "workflows": {"4": {"err_const": float("inf")}}},
            {"schema_version": 1, "workflows": {"4": {"cutoffs": []}}},
        ]
        for document in invalid:
            with self.subTest(document=document):
                self.write_document(document)
                original = self.store.path.read_bytes()
                with self.assertRaises(ValidationError):
                    self.store.load()
                with self.assertRaises(ValidationError):
                    self.store.save(Preferences())
                self.assertEqual(self.store.path.read_bytes(), original)

    def test_duplicate_json_keys_and_truncated_documents_require_explicit_reset(self):
        self.store.path.parent.mkdir()
        for content in ('{"schema_version":1,"schema_version":1}', '{"schema_version":'):
            self.store.path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValidationError):
                self.store.load()
            with self.assertRaises(ValidationError):
                self.store.save(Preferences())
            self.assertEqual(self.store.path.read_text(encoding="utf-8"), content)
            self.store.reset()
            self.store.save(Preferences())
            self.assertEqual(self.store.load(), Preferences())

    def test_settings_link_cannot_replace_an_unrelated_file(self):
        target = self.root / "unrelated.json"
        target.write_text(json.dumps(Preferences().to_dict()), encoding="utf-8")
        self.store.path.parent.mkdir()
        try:
            self.store.path.symlink_to(target)
        except OSError:
            self.skipTest("Symbolic links are not available to this test user.")
        original = target.read_bytes()
        with patch.dict(os.environ, {"NIPAT_SETTINGS_FILE": str(self.store.path)}):
            store = PreferencesStore()
            with self.assertRaisesRegex(ValidationError, "collegamento"):
                store.load()
            with self.assertRaises(ValidationError):
                store.save(Preferences(runs_dir=self.root / "new-runs"))
            store.reset()
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(self.store.path.exists())

    def test_atomic_save_failure_keeps_last_saved_defaults(self):
        before = Preferences(runs_dir=self.root / "first")
        self.store.save(before)
        original = self.store.path.read_bytes()
        with patch("nipat.preferences.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(ValidationError, "disk unavailable"):
                self.store.save(Preferences(runs_dir=self.root / "second"))
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(self.store.load(), before)
        self.assertEqual(list(self.store.path.parent.iterdir()), [self.store.path])

    def test_reset_removes_settings_only_and_keeps_research_files(self):
        self.layout.runs_dir.mkdir()
        result = self.layout.runs_dir / "analysis.txt"
        result.write_text("scientific result", encoding="utf-8")
        self.store.save(Preferences(runs_dir=self.layout.runs_dir))
        self.store.reset()
        self.assertFalse(self.store.path.exists())
        self.assertEqual(result.read_text(encoding="utf-8"), "scientific result")
        self.store.reset()  # Already reset is idempotent.

    def test_editing_copies_does_not_change_saved_workflow_defaults(self):
        prefs = Preferences().with_workflow("4", {"cutoffs": [("A", self.root / "panel.txt")]})
        defaults = prefs.workflow_defaults("4")
        defaults["cutoffs"].append(("B", self.root / "other.txt"))
        self.assertEqual(len(prefs.workflow_defaults("4")["cutoffs"]), 1)
        self.assertEqual(prefs.with_workflow("4", {}).workflow_defaults("4"), {})

    def test_native_cutoff_map_resolves_relative_files_before_persistence(self):
        with chdir(self.root):
            prefs = Preferences().with_workflow("4", {"cutoff_mode": "3", "cutoff_map": "A=panel.txt"})
            self.store.save(prefs)
        self.assertEqual(self.store.load().workflow_defaults("4")["cutoff_map"],
                         f"A={self.root / 'panel.txt'}")
        with self.assertRaisesRegex(ValidationError, "duplicata"):
            Preferences().with_workflow("4", {"cutoff_map": "A=a.txt,A=b.txt"})

    def test_platform_user_config_paths_are_isolated_and_do_not_create_files(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root),
                                     "XDG_CONFIG_HOME": str(self.root / "xdg")}, clear=True):
            with patch("nipat.preferences.sys.platform", "win32"):
                self.assertEqual(preferences_path(), self.root / "NIPAT-Experimental08" / "preferences.json")
            with patch("nipat.preferences.sys.platform", "linux"):
                self.assertEqual(preferences_path(), self.root / "xdg" / "nipat-experimental08" / "preferences.json")
        self.assertFalse((self.root / "NIPAT-Experimental08").exists())
        self.assertFalse((self.root / "xdg").exists())
        with patch.dict(os.environ, {"NIPAT_SETTINGS_FILE": str(self.store.path)}, clear=True):
            self.assertEqual(preferences_path(), self.store.path)

    def test_guided_cli_passes_explicit_directory_overrides_to_preferences_layer(self):
        with patch("nipat.cli.ProjectLayout.discover", return_value=self.layout), \
                patch("nipat.cli.DockerComposeRunner"), patch("nipat.cli.Workflows"), \
                patch("nipat.cli.PreferencesStore", return_value=self.store), \
                patch("nipat.cli.run_wizard", return_value=0) as wizard:
            result = main(["--runs-dir", str(self.root / "explicit"), "wizard"])
        self.assertEqual(result, 0)
        self.assertIs(wizard.call_args.kwargs["preferences_store"], self.store)
        self.assertEqual(wizard.call_args.kwargs["directory_overrides"],
                         {"runs_dir": self.root / "explicit"})
        self.assertFalse(self.store.path.parent.exists())

    def test_direct_cli_is_not_affected_by_saved_scientific_preferences(self):
        self.write_document({"schema_version": 1, "workflows": {"4": {"err_const": 0.5}}})
        workflows = Mock()
        with patch.dict(os.environ, {"NIPAT_SETTINGS_FILE": str(self.store.path)}), \
                patch("nipat.cli.ProjectLayout.discover", return_value=self.layout), \
                patch("nipat.cli.DockerComposeRunner"), \
                patch("nipat.cli.Workflows", return_value=workflows), \
                patch("nipat.cli.PreferencesStore") as store, redirect_stdout(io.StringIO()):
            result = main(["cpi", "--input-dir", "samples", "--pairs", "A:A", "--popfreq", "pop.txt"])
        self.assertEqual(result, 0)
        store.assert_not_called()
        self.assertEqual(workflows.cpi.call_args.kwargs["err_const"], DEFAULT_ERR_CONST)
        self.assertEqual(workflows.cpi.call_args.kwargs["mother_prefix"], "Mother")


if __name__ == "__main__":
    unittest.main()
