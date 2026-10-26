import io
import json
import os
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from string import Formatter
import tempfile
import unittest
from unittest.mock import Mock, patch

from nipat.cli import main
from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.options import ExecutionOptions
from nipat.i18n import MESSAGES, translate
from nipat.paths import ProjectLayout
from nipat.preferences import Preferences, PreferencesStore
from nipat.recovery_ui import recovery_lines, show_incomplete_runs
from nipat.terminal import Terminal
import test_cli_validation as cli_cases
import test_wizard_settings as settings_cases
import test_installation_client as maintenance_cases


class FailedRunTests(unittest.TestCase):
    setUp = cli_cases.WizardTests.setUp
    file = cli_cases.WizardTests.file
    invoke = cli_cases.WizardTests.invoke
    snp_answers = cli_cases.WizardTests.snp_answers

    def test_failed_run_is_latest_after_a_success(self):
        failed = self.layout.new_run_dir("snp-call", "failed")
        self.workflows.runner.last_run_dir = None
        runs = iter([self.run, failed])

        def execute(**_kwargs):
            path = next(runs)
            self.workflows.runner.last_run_dir = path
            if path == failed:
                raise RuntimeExecutionError("scientific failure")
            return path

        self.workflows.snp_call.side_effect = execute
        with patch("nipat.wizard.show_results") as show:
            status, messages = self.invoke(self.snp_answers() + ["1"] +
                                           self.snp_answers() + ["1", "0", "6", "0"])
        self.assertEqual(status, 2)
        self.assertEqual([call.args[1] for call in show.call_args_list], [self.run, failed])
        self.assertIn("eventuali risultati parziali", messages)

    def test_first_failure_after_run_creation_remains_consultable(self):
        self.workflows.runner.last_run_dir = None

        def fail(**_kwargs):
            self.workflows.runner.last_run_dir = self.run
            raise RuntimeExecutionError("scientific failure")

        self.workflows.snp_call.side_effect = fail
        with patch("nipat.wizard.show_results") as show:
            status, _ = self.invoke(self.snp_answers() + ["1", "0", "6", "0"])
        self.assertEqual(status, 2)
        show.assert_called_once()
        self.assertEqual(show.call_args.args[1], self.run)

    def test_failure_before_run_creation_does_not_adopt_stale_path(self):
        self.workflows.runner.last_run_dir = self.run
        self.workflows.snp_call.side_effect = ValidationError("invalid input")
        with patch("nipat.wizard.show_results") as show:
            status, messages = self.invoke(self.snp_answers() + ["1", "0", "6", "0"])
        self.assertEqual(status, 2)
        show.assert_not_called()
        self.assertIn("Nessuna esecuzione registrata", messages)


class StorageParityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "app"
        self.project.mkdir()
        self.layout = ProjectLayout(self.project, self.root, self.root / "data",
                                    self.root / "runs", self.project / "compose.yaml")
        self.record = self.project / ".runtime" / "install-layout.json"
        self.record.parent.mkdir()
        self.installation = {
            "schema_version": 1, "installation_channel": "desktop",
            "app_dir": str(self.project), "runtime_dir": str(self.root / "runtime"),
            "cache_dir": str(self.root / "cache"),
            "data_dir": str(self.layout.data_dir), "runs_dir": str(self.layout.runs_dir),
        }
        self.record.write_text(json.dumps(self.installation), encoding="utf-8")

    def test_same_reserved_policy_applies_to_cli_and_guided_directories(self):
        for role in ("runtime_dir", "cache_dir"):
            for field in ("data_dir", "runs_dir"):
                destination = Path(self.installation[role]) / "research"
                with self.subTest(role=role, field=field):
                    with self.assertRaisesRegex(ValidationError, "riservata"):
                        replace(self.layout, **{field: destination}).new_run_dir("snp-call")
                    with self.assertRaisesRegex(ValidationError, "riservata"):
                        Preferences(**{field: destination}).effective_layout(self.layout)
                    self.assertFalse(destination.exists())

    def test_direct_discovery_rejects_reserved_location_without_creating_it(self):
        target = self.root / "cache" / "analyses"
        with patch.dict(os.environ, {"NIPAT_PROJECT_DIR": str(self.project),
                                    "NIPAT_WORKSPACE_DIR": str(self.root),
                                    "NIPAT_DATA_DIR": str(self.layout.data_dir)}):
            with self.assertRaisesRegex(ValidationError, "riservata"):
                ProjectLayout.discover(runs_dir=target)
        self.assertFalse(target.exists())

    def test_invalid_record_cannot_waive_cli_destination_policy(self):
        original = self.record.read_bytes()
        for content in (b"{", b'{"schema_version":1,"schema_version":1}',
                        json.dumps({**self.installation, "runtime_dir": "relative"}).encode()):
            with self.subTest(content=content):
                self.record.write_bytes(content)
                with self.assertRaisesRegex(ValidationError, "setup NIPAT"):
                    self.layout.new_run_dir("snp-call")
                self.assertFalse(self.layout.runs_dir.exists())
        self.record.write_bytes(original)
        run = self.layout.new_run_dir("snp-call", "safe")
        self.assertTrue(run.is_dir())


class DirectInputErrorsTests(unittest.TestCase):
    def test_malformed_snp_panels_fail_cleanly_before_run_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            pileup = root / "input.pileup"
            pileup.write_text("chr1\t2\tC\t1\t.\tI\tread1\n", encoding="utf-8")
            panel = root / "panel.tsv"
            malformed = [
                "pos\tref\talt\nchr1:2\tC\tG\n".encode("utf-16"),
                b"pos\tref\talt\nchr1:2\tC\t\xff\n",
                ("pos\tref\talt\nchr1:2\t" + "A" * 140000 + "\tG\n").encode(),
            ]
            for content in malformed:
                with self.subTest(size=len(content)):
                    panel.write_bytes(content)
                    stderr = io.StringIO()
                    with redirect_stderr(stderr), redirect_stdout(io.StringIO()), \
                            patch.dict(os.environ, {"NIPAT_BACKEND": "docker"}):
                        result = main(["--dry-run", "--data-dir", str(root / "data"),
                                       "--runs-dir", str(root / "runs"), "snp-call",
                                       "--pileup", str(pileup), "--panel", str(panel)])
                    self.assertEqual(result, 2)
                    self.assertIn("Errore:", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())
                    self.assertFalse((root / "runs").exists())


class ExecutionPreferencesTests(unittest.TestCase):
    def test_legacy_settings_keep_unlimited_resources_and_auto_hashes(self):
        value = Preferences.from_dict({"schema_version": 1, "workflows": {}})
        self.assertEqual(value.execution_options(), ExecutionOptions())

    def test_execution_preferences_roundtrip_and_explicit_flags_win(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = PreferencesStore(Path(temporary) / "preferences.json")
            settings = Preferences(execution={"input_hashes": "full", "cpus": 2.0,
                                              "memory_mb": 4096, "pids_limit": 128})
            store.save(settings)
            self.assertEqual(store.load(), settings)
            actual = store.load().execution_options({"input_hashes": "auto", "cpus": 1.0})
            self.assertEqual(actual, ExecutionOptions(input_hashes="auto", cpus=1.0,
                                                      memory_mb=4096, pids_limit=128))

    def test_unknown_execution_keys_are_not_ignored(self):
        with self.assertRaises(ValidationError):
            Preferences(execution={"privileged": True})


class RecoveryPresentationTests(unittest.TestCase):
    def report(self):
        return {"run_dir": "/research/runs/case", "run_name": "case", "recorded_status": "running",
                "backend_matches": True, "containers": [{"container_name": "nipat-run-test",
                    "state": "running", "owned": True}], "stop_requested": False}

    def test_catalogs_have_identical_keys_and_format_fields(self):
        self.assertEqual(MESSAGES["it"].keys(), MESSAGES["en"].keys())
        for key in MESSAGES["it"]:
            def fields(language):
                return {name for _, name, _, _ in Formatter().parse(MESSAGES[language][key]) if name}
            self.assertEqual(fields("it"), fields("en"), key)
        self.assertNotEqual(translate("recovery_title", "it"), translate("recovery_title", "en"))

    def test_localization_does_not_mutate_runtime_report(self):
        report = self.report()
        before = json.dumps(report, sort_keys=True)
        self.assertNotEqual(recovery_lines(report, language="it"), recovery_lines(report, language="en"))
        self.assertEqual(json.dumps(report, sort_keys=True), before)

    def test_dry_run_recovery_never_queries_or_stops_runtime(self):
        runner = Mock()
        ui = Terminal(read=Mock(), write=Mock(), cancel_to_menu=True)
        show_incomplete_runs(ui, runner, dry_run=True)
        runner.incomplete_runs.assert_not_called()
        runner.reconcile_run.assert_not_called()

    def test_inspection_and_default_no_do_not_stop_a_container(self):
        runner = Mock()
        runner.incomplete_runs.return_value = [self.report()]
        ui = Terminal(read=Mock(side_effect=["1", "0", "0"]), write=Mock(), cancel_to_menu=True)
        show_incomplete_runs(ui, runner)
        runner.reconcile_run.assert_not_called()

    def test_verified_stop_requires_explicit_selection(self):
        runner = Mock()
        runner.incomplete_runs.side_effect = [[self.report()], []]
        runner.reconcile_run.return_value = {**self.report(), "stop_requested": True}
        ui = Terminal(read=Mock(side_effect=["1", "1"]), write=Mock(), cancel_to_menu=True)
        show_incomplete_runs(ui, runner)
        runner.reconcile_run.assert_called_once_with(Path("/research/runs/case"), stop=True)

    def test_unverified_container_cannot_be_selected_for_stopping(self):
        report = self.report()
        report["containers"][0]["owned"] = False
        runner = Mock()
        runner.incomplete_runs.return_value = [report]
        ui = Terminal(read=Mock(side_effect=["1", "0"]), write=Mock(), cancel_to_menu=True)
        show_incomplete_runs(ui, runner)
        runner.reconcile_run.assert_not_called()

    def test_unreadable_record_diagnostic_is_visible(self):
        report = {**self.report(), "containers": [], "error": "Invalid run.json"}
        self.assertIn("Invalid run.json", "\n".join(recovery_lines(report)))

    def test_restarting_and_paused_owned_containers_can_be_stopped(self):
        for state in ("restarting", "paused"):
            with self.subTest(state=state):
                report = self.report()
                report["containers"][0]["state"] = state
                runner = Mock()
                runner.incomplete_runs.side_effect = [[report], []]
                runner.reconcile_run.return_value = {**report, "stop_requested": True}
                ui = Terminal(read=Mock(side_effect=["1", "1"]), write=Mock(), cancel_to_menu=True)
                show_incomplete_runs(ui, runner)
                runner.reconcile_run.assert_called_once_with(Path(report["run_dir"]), stop=True)


class ClientRoutingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.layout = ProjectLayout(root / "app", root, root / "data", root / "runs",
                                    root / "app" / "compose.yaml")
        self.layout.project_dir.mkdir()
        self.runner = Mock()
        self.runner_factory = self.enterContext(patch("nipat.cli.DockerComposeRunner", return_value=self.runner))
        self.enterContext(patch("nipat.cli.ProjectLayout.discover", return_value=self.layout))
        self.enterContext(patch("nipat.cli.activity_session", return_value=nullcontext()))
        self.workflows = self.enterContext(patch("nipat.cli.Workflows"))
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(io.StringIO()))

    def test_direct_analysis_uses_explicit_options_without_loading_guided_defaults(self):
        with patch("nipat.cli.PreferencesStore") as store:
            result = main(["--input-hashes", "full", "--cpus", "2", "--memory-mb", "4096",
                           "--pids-limit", "256", "snp-call", "--pileup", "input.txt", "--panel", "panel.tsv"])
        self.assertEqual(result, 0)
        store.assert_not_called()
        self.assertEqual(self.runner_factory.call_args.kwargs["options"],
                         ExecutionOptions("full", 2.0, 4096, 256))
        self.assertEqual(self.workflows.return_value.snp_call.call_args.kwargs["panel"], Path("panel.tsv"))

    def test_non_analysis_does_not_silently_ignore_execution_options(self):
        for command in (["self-test"], ["doctor"], ["runs", "inspect"], ["installation", "inspect"]):
            with self.subTest(command=command), self.assertRaises(SystemExit) as caught:
                main(["--cpus", "2", *command])
            self.assertEqual(caught.exception.code, 2)
        self.runner_factory.assert_not_called()

    def test_recovery_json_is_identical_in_both_languages(self):
        report = RecoveryPresentationTests().report()
        self.runner.reconcile_run.return_value = report
        payloads = []
        for language in ("it", "en"):
            self.output.seek(0)
            self.output.truncate()
            result = main(["runs", "inspect", "--run", report["run_dir"], "--json", "--lang", language])
            self.assertEqual(result, 0)
            payloads.append(json.loads(self.output.getvalue()))
        self.assertEqual(payloads, [[report], [report]])
        self.runner.reconcile_run.assert_called_with(Path(report["run_dir"]), stop=False)

    def test_declining_stop_never_requests_runtime_mutation(self):
        with patch("nipat.terminal.Terminal.prompt", return_value=""):
            self.assertEqual(main(["runs", "stop", "--run", "case"]), 0)
        self.runner.reconcile_run.assert_not_called()

    def test_unconfirmed_stop_returns_error_and_preserves_diagnostic_json(self):
        report = RecoveryPresentationTests().report()
        report["containers"][0]["cleanup"] = {"status": "not_confirmed", "reason": "runtime unavailable"}
        self.runner.reconcile_run.return_value = report
        result = main(["runs", "stop", "--run", report["run_dir"], "--yes", "--json"])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(self.output.getvalue()), [report])
        self.runner.reconcile_run.assert_called_once_with(Path(report["run_dir"]), stop=True)

    def test_cli_maintenance_handoff_requires_explicit_confirmation(self):
        with patch("nipat.installation.installation_inventory", return_value=maintenance_cases.inventory()), \
                patch("nipat.installation.start_maintenance", return_value=Path("result.json")) as start, \
                patch("nipat.terminal.Terminal.prompt", return_value=""):
            self.assertEqual(main(["installation", "cleanup", "--target", "old"]), 0)
            start.assert_not_called()
            self.assertEqual(main(["installation", "cleanup", "--target", "old", "--yes"]), 85)
        start.assert_called_once_with(self.layout.project_dir, "cleanup", "old")

    def test_cli_cannot_force_cleanup_of_protected_component(self):
        with patch("nipat.installation.installation_inventory", return_value=maintenance_cases.inventory()), \
                patch("nipat.installation.start_maintenance") as start:
            self.assertEqual(main(["installation", "cleanup", "--target", "active", "--yes"]), 2)
        start.assert_not_called()


class GuidedExecutionTests(unittest.TestCase):
    setUp = settings_cases.WizardSettingsTests.setUp
    file = settings_cases.WizardSettingsTests.file
    invoke = settings_cases.WizardSettingsTests.invoke

    def test_resources_apply_after_save_without_changing_scientific_defaults(self):
        scientific = {"1": {"parallel": "2"}}
        self.store.save(Preferences(workflows=scientific))
        status, _ = self.invoke(["5", "9", "1", "2", "2", "2", "3", "2048", "4", "128", "9", "0", "0"])
        self.assertEqual(status, 0)
        self.assertEqual(self.store.load().workflows, scientific)
        self.assertEqual(self.workflows.runner.options, ExecutionOptions("full", 2.0, 2048, 128))
        self.workflows.dnp_call.assert_not_called()

    def test_unsaved_resource_edit_is_discarded(self):
        self.store.save(Preferences(execution={"cpus": 1.0}))
        original = self.store.path.read_bytes()
        self.invoke(["5", "9", "2", "4", "0", "0", "0"])
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(self.workflows.runner.options, ExecutionOptions(cpus=1.0))

    def test_guide_handoff_exits_only_after_worker_acknowledgement(self):
        with patch("nipat.wizard.show_installation", return_value=True) as maintenance:
            status, _ = self.invoke(["7", "8"])
        self.assertEqual(status, 85)
        maintenance.assert_called_once_with(unittest.mock.ANY, self.layout.project_dir, dry_run=False)


if __name__ == "__main__":
    unittest.main()
