"""The execution policy is visible, bounded, and independent of scientific inputs."""

import io
from contextlib import redirect_stderr
import unittest

import test_cli_validation as cli_cases
import test_client_reliability as client_cases
import test_wizard_settings as settings_cases

from nipat.cli import build_parser, main
from nipat.errors import ValidationError
from nipat.execution.options import ExecutionOptions
from nipat.preferences import Preferences, PreferencesStore


class ParallelPolicyTests(unittest.TestCase):
    def test_new_and_existing_preferences_use_automatic_policy(self):
        for preferences in (Preferences(), Preferences.from_dict({"schema_version": 1}),
                            Preferences(workflows={"1": {"parallel": "1"}})):
            with self.subTest(preferences=preferences):
                options = preferences.execution_options()
                self.assertEqual(options.execution_mode, "auto")
                self.assertIsNone(options.max_workers)
                self.assertEqual((options.dnp_block_mib, options.dnp_block_loci), (32, 64))

    def test_workers_and_block_sizes_require_bounded_positive_integers(self):
        for field, maximum in (("max_workers", 1024), ("dnp_block_mib", 4096),
                               ("dnp_block_loci", 1_000_000)):
            for value in (True, False, 1.0, "2", 0, -1, maximum + 1):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    ExecutionOptions(**{field: value})
            self.assertEqual(getattr(ExecutionOptions(**{field: maximum}), field), maximum)

    def test_modes_are_explicit_and_serial_keeps_a_reusable_worker_cap(self):
        for value in (True, None, "parallel", "manual", "", 1):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ExecutionOptions(execution_mode=value)
        self.assertEqual(ExecutionOptions(execution_mode="serial", max_workers=8).max_workers, 8)

    def test_parallel_policy_does_not_replace_container_limits(self):
        options = ExecutionOptions(cpus=3.5, memory_mb=4096, pids_limit=64,
                                   max_workers=8, dnp_block_mib=16, dnp_block_loci=32)
        self.assertEqual(options.compose_limits(), {
            "cpus": 3.5, "mem_limit": 4096 * 1024**2,
            "memswap_limit": 4096 * 1024**2, "pids_limit": 64,
        })
        self.assertEqual(options.as_dict()["max_workers"], 8)

    def test_persistent_defaults_and_explicit_overrides_keep_separate_values(self):
        preferences = Preferences(execution={"execution_mode": "auto", "max_workers": 4,
                                            "dnp_block_mib": 16, "dnp_block_loci": 32})
        loaded = Preferences.from_dict(preferences.to_dict())
        effective = loaded.execution_options({"execution_mode": "serial", "dnp_block_mib": 64})
        self.assertEqual((effective.execution_mode, effective.max_workers,
                          effective.dnp_block_mib, effective.dnp_block_loci), ("serial", 4, 64, 32))
        self.assertEqual(loaded.execution, preferences.execution)


class ParallelCliTests(unittest.TestCase):
    setUp = client_cases.ClientRoutingTests.setUp

    def test_all_four_workflows_receive_the_global_execution_policy(self):
        commands = [
            ["dnp-call", "--bam", "sample.bam", "--reference", "ref.fa", "--panel", "panel.txt"],
            ["snp-call", "--pileup", "pileup.txt", "--panel", "panel.txt"],
            ["contamination", "--input", "sample.txt", "--panel", "panel.txt"],
            ["cpi", "--input-dir", "samples", "--pairs", "A:A", "--popfreq", "pop.tsv"],
        ]
        for command in commands:
            with self.subTest(command=command[0]):
                self.assertEqual(main(["--execution-mode", "auto", "--max-workers", "4",
                                       "--dnp-block-mib", "16", "--dnp-block-loci", "32", *command]), 0)
                options = self.runner_factory.call_args.kwargs["options"]
                self.assertEqual(options, ExecutionOptions(max_workers=4, dnp_block_mib=16, dnp_block_loci=32))

    def test_serial_mode_is_not_changed_by_legacy_parallel_flag(self):
        self.assertEqual(main(["--execution-mode", "serial", "dnp-call", "--bam", "sample.bam",
                               "--reference", "ref.fa", "--panel", "panel.txt", "--parallel"]), 0)
        self.assertEqual(self.runner_factory.call_args.kwargs["options"].execution_mode, "serial")
        self.assertTrue(self.workflows.return_value.dnp_call.call_args.kwargs["parallel"])

    def test_unrelated_commands_cannot_silently_ignore_parallel_flags(self):
        for flags in (["--execution-mode", "serial"], ["--max-workers", "2"],
                      ["--dnp-block-mib", "32"], ["--dnp-block-loci", "64"]):
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main([*flags, "doctor"])
            self.assertEqual(caught.exception.code, 2)
        self.runner_factory.assert_not_called()

    def test_parser_leaves_unspecified_values_available_for_saved_preferences(self):
        args = build_parser().parse_args(["wizard"])
        self.assertTrue(all(getattr(args, key) is None for key in (
            "execution_mode", "max_workers", "dnp_block_mib", "dnp_block_loci")))


class ParallelWizardTests(unittest.TestCase):
    setUp = cli_cases.WizardTests.setUp
    file = cli_cases.WizardTests.file
    invoke = cli_cases.WizardTests.invoke
    snp_answers = cli_cases.WizardTests.snp_answers

    def test_review_override_is_visible_and_does_not_leak_to_the_next_analysis(self):
        store = PreferencesStore(self.root / "preferences.json")
        store.save(Preferences(execution={"max_workers": 4, "dnp_block_mib": 16}))
        original = store.path.read_bytes()
        observed = []

        def execute(**arguments):
            observed.append((self.workflows.runner.options, arguments))
            return self.run

        self.workflows.snp_call.side_effect = execute
        answers = self.snp_answers("serial") + ["4", "1", "2", "2", "2", "3", "64", "4", "128", "9", "1", "0"]
        answers += self.snp_answers("automatic") + ["1", "0", "0"]
        status, messages = self.invoke(answers, preferences_store=store)
        self.assertEqual(status, 0)
        self.assertEqual(observed[0][0], ExecutionOptions(execution_mode="serial", max_workers=2,
                                                        dnp_block_mib=64, dnp_block_loci=128))
        self.assertEqual(observed[1][0], ExecutionOptions(max_workers=4, dnp_block_mib=16))
        self.assertEqual(store.path.read_bytes(), original)
        self.assertIn("Seriale (un processo di calcolo)", messages)
        self.assertIn("non la RAM occupata", messages)
        self.assertNotIn("execution_mode", observed[0][1])

    def test_cancelling_execution_edit_keeps_saved_values(self):
        observed = []
        self.workflows.snp_call.side_effect = lambda **_: observed.append(self.workflows.runner.options) or self.run
        status, _ = self.invoke(self.snp_answers() + ["4", "2", "3", "0", "1", "0", "0"])
        self.assertEqual(status, 0)
        self.assertEqual(observed, [ExecutionOptions()])

    def test_invalid_worker_count_is_rejected_then_automatic_can_be_restored(self):
        observed = []
        self.workflows.snp_call.side_effect = lambda **_: observed.append(self.workflows.runner.options) or self.run
        status, messages = self.invoke(self.snp_answers() + [
            "4", "2", "0", "2", "2", "2", ":vuoto", "9", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.assertIsNone(observed[0].max_workers)
        self.assertIn("Valore non valido", messages)

    def test_old_dnp_mode_does_not_present_a_second_conflicting_parallel_switch(self):
        store = PreferencesStore(self.root / "preferences.json")
        store.save(Preferences(workflows={"1": {"parallel": "1"}}))
        status, messages = self.invoke(["1", "1", self.bam, "", self.reference,
                                       self.panel, "automatic", "1", "0", "0"], preferences_store=store)
        self.assertEqual(status, 0)
        self.assertIn("Calcolo: Automatico", messages)
        self.assertNotIn("Modalita' di esecuzione", messages)


class ParallelSettingsTests(unittest.TestCase):
    setUp = settings_cases.WizardSettingsTests.setUp
    file = settings_cases.WizardSettingsTests.file
    invoke = settings_cases.WizardSettingsTests.invoke

    def test_settings_save_and_reload_all_four_values(self):
        status, _ = self.invoke(["5", "9", "6", "1", "2", "2", "8", "3", "64", "4", "128",
                                "9", "9", "0", "0"])
        self.assertEqual(status, 0)
        expected = ExecutionOptions(execution_mode="serial", max_workers=8, dnp_block_mib=64, dnp_block_loci=128)
        self.assertEqual(self.store.load().execution_options(), expected)
        self.invoke(["0"])
        self.assertEqual(self.workflows.runner.options, expected)


if __name__ == "__main__":
    unittest.main()
