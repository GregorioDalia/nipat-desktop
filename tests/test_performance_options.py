"""Diagnostic opt-in never becomes a scientific parameter or a saved default."""

import io
from contextlib import redirect_stderr
from pathlib import Path
import unittest
from unittest.mock import patch

import test_cli_validation as cli_cases
import test_client_reliability as client_cases
import test_workflow_wizard as workflow_cases

from nipat.cli import build_parser, main
from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.options import ExecutionOptions
from nipat.preferences import Preferences, PreferencesStore


class PerformanceOptionsTests(unittest.TestCase):
    def test_off_by_default_and_not_a_container_resource_limit(self):
        self.assertFalse(ExecutionOptions().performance_diagnostics)
        self.assertIsNone(build_parser().parse_args(["wizard"]).performance_diagnostics)
        options = ExecutionOptions(cpus=2, memory_mb=512, performance_diagnostics=True)
        self.assertEqual(options.compose_limits(), ExecutionOptions(cpus=2, memory_mb=512).compose_limits())
        self.assertTrue(options.as_dict()["performance_diagnostics"])

    def test_only_boolean_opt_in_is_accepted(self):
        for value in (1, 0, "true", "false", None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ExecutionOptions(performance_diagnostics=value)

    def test_diagnostics_cannot_be_stored_as_a_persistent_preference(self):
        for value in (True, False):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Preferences(execution={"performance_diagnostics": value})


class DiagnosticCliTests(unittest.TestCase):
    setUp = client_cases.ClientRoutingTests.setUp

    def test_direct_analysis_receives_opt_in_without_scientific_argument_changes(self):
        result = main(["--performance-diagnostics", "snp-call", "--pileup", "input.txt", "--panel", "panel.tsv"])
        self.assertEqual(result, 0)
        self.assertTrue(self.runner_factory.call_args.kwargs["options"].performance_diagnostics)
        self.assertEqual(self.workflows.return_value.snp_call.call_args.kwargs, {
            "bam": None, "pileup": Path("input.txt"), "reference": None,
            "panel": Path("panel.tsv"), "run_name": None,
        })

    def test_non_analysis_commands_cannot_silently_ignore_diagnostics(self):
        for command in (["doctor"], ["self-test"], ["resources", "inspect"],
                        ["parameters", "dnp-call"], ["build-runtime"], ["runs", "inspect"]):
            with self.subTest(command=command), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(["--performance-diagnostics", *command])
            self.assertEqual(caught.exception.code, 2)
        self.runner_factory.assert_not_called()

    def test_wizard_receives_one_run_request(self):
        with patch("nipat.cli.run_wizard", return_value=0) as wizard:
            self.assertEqual(main(["--performance-diagnostics", "wizard"]), 0)
        self.assertEqual(wizard.call_args.kwargs["execution_overrides"], {"performance_diagnostics": True})


class DiagnosticWizardTests(unittest.TestCase):
    setUp = cli_cases.WizardTests.setUp
    file = cli_cases.WizardTests.file
    invoke = cli_cases.WizardTests.invoke
    snp_answers = cli_cases.WizardTests.snp_answers

    def capture_analyses(self, effects=None):
        observed = []
        effects = iter(effects or [])

        def execute(**arguments):
            observed.append((self.workflows.runner.options.performance_diagnostics, arguments))
            effect = next(effects, None)
            if effect is not None:
                raise effect
            return self.run

        self.workflows.snp_call.side_effect = execute
        return observed

    def test_review_opt_in_is_only_for_the_selected_analysis(self):
        observed = self.capture_analyses()
        store = PreferencesStore(self.root / "preferences.json")
        store.save(Preferences(execution={"memory_mb": 512}))
        original = store.path.read_bytes()
        answers = self.snp_answers("profiled") + ["3", "0"]
        answers += self.snp_answers("normal") + ["1", "0", "0"]
        status, messages = self.invoke(answers, preferences_store=store)
        self.assertEqual(status, 0)
        self.assertEqual([value for value, _ in observed], [True, False])
        self.assertEqual(observed[0][1] | {"run_name": "normal"}, observed[1][1])
        self.assertNotIn("performance_diagnostics", observed[0][1])
        self.assertFalse(self.workflows.runner.options.performance_diagnostics)
        self.assertEqual(self.workflows.runner.options.memory_mb, 512)
        self.assertEqual(store.path.read_bytes(), original)
        self.assertIn("non invia dati", messages)

    def test_explicit_cli_opt_in_is_visible_and_consumed_after_one_run(self):
        observed = self.capture_analyses()
        answers = self.snp_answers("profiled") + ["1", "0"]
        answers += self.snp_answers("normal") + ["1", "0", "0"]
        status, messages = self.invoke(answers, execution_overrides={"performance_diagnostics": True})
        self.assertEqual(status, 0)
        self.assertEqual([value for value, _ in observed], [True, False])
        self.assertIn("Avvia analisi con diagnostica prestazioni", messages)
        self.assertIn("Avvia analisi senza diagnostica", messages)
        self.assertFalse(self.workflows.runner.options.performance_diagnostics)

    def test_cli_opt_in_can_be_overridden_with_normal_execution(self):
        observed = self.capture_analyses()
        self.invoke(self.snp_answers() + ["3", "0", "0"],
                    execution_overrides={"performance_diagnostics": True})
        self.assertEqual([value for value, _ in observed], [False])

    def test_failed_analysis_does_not_enable_diagnostics_for_retry(self):
        observed = self.capture_analyses([RuntimeExecutionError("test error")])
        status, _ = self.invoke(self.snp_answers() + ["3", "1", "0", "0"])
        self.assertEqual(status, 2)
        self.assertEqual([value for value, _ in observed], [True, False])
        self.assertFalse(self.workflows.runner.options.performance_diagnostics)

    def test_interrupted_analysis_resets_opt_in_before_returning_to_menu(self):
        observed = self.capture_analyses([KeyboardInterrupt()])
        answers = self.snp_answers() + ["3"] + self.snp_answers() + ["1", "0", "0"]
        self.invoke(answers)
        self.assertEqual([value for value, _ in observed], [True, False])
        self.assertFalse(self.workflows.runner.options.performance_diagnostics)

    def test_cancelling_review_clears_pending_cli_opt_in(self):
        observed = self.capture_analyses()
        answers = self.snp_answers() + ["0"] + self.snp_answers() + ["1", "0", "0"]
        self.invoke(answers, execution_overrides={"performance_diagnostics": True})
        self.assertEqual([value for value, _ in observed], [False])

    def test_field_correction_does_not_start_diagnostics_or_change_arguments(self):
        observed = self.capture_analyses()
        self.invoke(self.snp_answers("before") + ["2", "5", "after", "3", "0", "0"])
        self.assertEqual(len(observed), 1)
        self.assertTrue(observed[0][0])
        self.assertEqual(observed[0][1]["run_name"], "after")

    def test_settings_save_does_not_add_diagnostic_default(self):
        store = PreferencesStore(self.root / "preferences.json")
        status, _ = self.invoke(["5", "9", "9", "0", "0"], preferences_store=store)
        self.assertEqual(status, 0)
        self.assertNotIn("performance_diagnostics", store.load().execution)


class DiagnosticWorkflowWizardTests(unittest.TestCase):
    setUp = workflow_cases.WorkflowWizardTests.setUp
    file = workflow_cases.WorkflowWizardTests.file
    invoke = workflow_cases.WorkflowWizardTests.invoke
    inputs = workflow_cases.WorkflowWizardTests.inputs
    cpi_inputs = workflow_cases.WorkflowWizardTests.cpi_inputs

    def test_all_automatic_workflows_accept_explicit_diagnostic_confirmation(self):
        cases = [
            (self.inputs(), "dnp_contamination"),
            (self.cpi_inputs(preset="2"), "dnp_cpi"),
            (self.cpi_inputs(preset="3"), "dnp_cpi"),
            (["W", "4", "1", self.bam, "", self.reference, self.snp_panel, "snp-chain"], "snp_batch"),
        ]
        for answers, method in cases:
            with self.subTest(preset=answers[1]):
                observed = []

                def execute(**arguments):
                    observed.append((self.workflows.runner.options.performance_diagnostics, arguments))
                    return self.run

                getattr(self.workflows, method).side_effect = execute
                status, output = self.invoke(answers + ["3", "0", "0"])
                self.assertEqual(status, 0)
                self.assertEqual(len(observed), 1)
                self.assertTrue(observed[0][0])
                self.assertNotIn("performance_diagnostics", observed[0][1])
                self.assertFalse(self.workflows.runner.options.performance_diagnostics)
                self.assertIn("Diagnostica prestazioni attiva", output)


if __name__ == "__main__":
    unittest.main()
