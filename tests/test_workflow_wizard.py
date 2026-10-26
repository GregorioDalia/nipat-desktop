"""Interaction checks for the one-confirmation scientific chain."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from nipat.cli import DEFAULT_ERR_CONST
from nipat.errors import RuntimeExecutionError
from nipat.paths import ProjectLayout
from nipat.preferences import Preferences, PreferencesStore
from nipat.wizard import MAIN_MENU, run_wizard


class WorkflowWizardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        project = self.root / "project"
        project.mkdir()
        self.layout = ProjectLayout(
            project, self.root, self.root / "data", self.root / "runs", project / "compose.yaml",
        )
        self.bam = self.file("sample with spaces.bam", "")
        self.other_mother = self.file("second maternal sample.bam", "")
        self.father = self.file("paternal sample.bam", "")
        self.other_father = self.file("another paternal sample.bam", "")
        self.reference = self.file("reference.fa", ">chr1\nACGT\n")
        self.file("reference.fa.fai", "chr1\t4\t6\t4\t5\n")
        self.panel = self.file("dnp.tsv", "chr1\t2\t3\tCG\tAT\n")
        self.positions = self.file("positions.tsv", "chr\tpos1\tpos2\nchr1\t2\t3\n")
        self.snp_panel = self.file("snps.tsv", "pos\tref\talt\nchr1:2\tC\tG\n")
        self.pileup = self.file("first pileup.txt", "chr1\t2\tC\t1\t.\tI\tread1\n")
        self.other_pileup = self.file("second pileup.txt", "chr1\t2\tC\t1\tG\tI\tread2\n")
        self.popfreq = self.file("population.tsv", "chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\nchr1\t2\t3\t0.5\t0.5\n")
        self.run = self.layout.runs_dir / "complete"
        (self.run / "output").mkdir(parents=True)
        self.workflows = Mock()
        self.workflows.dnp_contamination.return_value = self.run
        self.workflows.dnp_cpi.return_value = self.run
        self.workflows.snp_batch.return_value = self.run

    def file(self, name, contents):
        result = self.root / name
        result.write_text(contents, encoding="utf-8")
        return result

    def invoke(self, answers, **kwargs):
        messages = []
        reader = Mock(side_effect=[str(value) if isinstance(value, Path) else value for value in answers])
        self.reader = reader
        result = run_wizard(
            self.workflows, self.layout, err_const=DEFAULT_ERR_CONST,
            read=reader, write=messages.append, **kwargs,
        )
        return result, "\n".join(messages)

    def inputs(self, *, choice="W", name="chain"):
        return [choice, "1", "1", f'"{self.bam}"', "", self.reference, self.panel, "1", "1", "", name]

    def cpi_inputs(self, *, preset="2", name="cpi-chain"):
        return ["W", preset, "Pair1", self.bam, self.father, "",
                self.reference, self.panel, "1"] + (["1"] if preset == "3" else []) + [
                    self.popfreq, "0", "", "", name,
                ]

    def assert_no_single_analysis(self):
        for name in ("dnp_call", "snp_call", "contamination", "cpi"):
            getattr(self.workflows, name).assert_not_called()

    def test_menu_preserves_existing_numbers_and_single_character_navigation(self):
        keys = [item[0] for item in MAIN_MENU]
        self.assertEqual(set(keys), set("0123456789") | {"W"})
        self.assertTrue(all(len(key) == 1 for key in keys))
        self.assertEqual(dict((key, label) for key, label, _ in MAIN_MENU)["5"], "Configura")

    def test_one_confirmation_dispatches_chain_and_shows_both_result_locations(self):
        status, output = self.invoke(self.inputs() + ["1", "0", "0"])
        self.assertEqual(status, 0)
        self.workflows.dnp_contamination.assert_called_once_with(
            bams=[self.bam], bamlist=None, reference=self.reference, panel=self.panel,
            parallel=False, contamination_panel=None, snp_panel=None, run_name="chain",
        )
        self.assert_no_single_analysis()
        self.assertEqual(output.count("Riepilogo prima dell'avvio"), 1)
        self.assertIn("non sono richieste altre conferme fra le fasi", output)
        self.assertIn(str(self.run / "output" / "workflow" / "steps" / "dnp" / "output"), output)
        self.assertIn(str(self.run / "output" / "workflow" / "steps" / "contamination" / "output"), output)
        self.assertIn("workflow-state.json", output)

    def test_bamlist_parallel_and_distinct_contamination_panel(self):
        bamlist = self.file("bams.txt", '"sample with spaces.bam"\n')
        status, output = self.invoke([
            "w", "1", "2", bamlist, self.reference, self.panel, "2", "2", self.positions,
            "", "", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.workflows.dnp_contamination.assert_called_once_with(
            bams=None, bamlist=bamlist, reference=self.reference, panel=self.panel,
            parallel=True, contamination_panel=self.positions, snp_panel=None, run_name=None,
        )
        self.assertIn("Indicare ora il file di coordinate", output)
        self.assert_no_single_analysis()

    def test_empty_review_cancels_without_any_scientific_dispatch(self):
        status, output = self.invoke(self.inputs() + ["", "0"])
        self.assertEqual(status, 0)
        self.workflows.dnp_contamination.assert_not_called()
        self.assert_no_single_analysis()
        self.assertIn("annullata prima dell'avvio", output)

    def test_empty_first_bam_waits_and_can_be_cancelled_without_error(self):
        status, output = self.invoke(["W", "1", "1", "", "", ":annulla", "0"])
        self.assertEqual(status, 0)
        self.workflows.dnp_contamination.assert_not_called()
        self.assertIn("Invio senza testo mantiene aperto questo passaggio", output)
        self.assertNotIn("[ERRORE]", output)

    def test_review_can_select_another_panel_then_revert_to_dnp_panel(self):
        # Field 6 is the Contamination panel choice; switching back must not leak
        # a hidden, previously collected path into the execution request.
        status, _ = self.invoke(self.inputs() + [
            "2", "6", "2", self.positions,
            "2", "6", "1", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.assertIsNone(self.workflows.dnp_contamination.call_args.kwargs["contamination_panel"])
        self.assertEqual(self.workflows.dnp_contamination.call_count, 1)

    def test_empty_different_panel_waits_until_a_valid_path_is_supplied(self):
        status, output = self.invoke([
            "W", "1", "1", self.bam, "", self.reference, self.panel, "1", "2", "",
            self.positions, "", "", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.assertIn("Nessun valore inserito", output)
        self.assertNotIn("[ERRORE]", output)
        self.assertEqual(self.workflows.dnp_contamination.call_args.kwargs["contamination_panel"], self.positions)

    def test_dry_run_does_not_claim_completed_phases_or_existing_results(self):
        status, output = self.invoke(self.inputs() + ["1", "0", "0"], dry_run=True)
        self.assertEqual(status, 0)
        self.workflows.dnp_contamination.assert_called_once()
        self.assertIn("Esecuzione pianificata", output)
        self.assertIn("senza eseguire il calcolo scientifico", output)
        self.assertNotIn("Esecuzione completata", output)
        self.assertNotIn("Risultati DNPcall:", output)
        self.assertNotIn("Stati delle fasi:", output)

    def test_failure_preserves_form_and_explains_new_run_without_retrying_implicitly(self):
        self.workflows.dnp_contamination.side_effect = RuntimeExecutionError("DNPcall non riuscito")
        status, output = self.invoke(self.inputs() + ["1", "0", "0"])
        self.assertEqual(status, 2)
        self.workflows.dnp_contamination.assert_called_once()
        self.assertIn("Per ripetere il workflow scegliere un nuovo nome", output)
        self.assertIn("I valori inseriti sono conservati", output)
        self.assertNotIn("Esecuzione completata", output)

    def test_help_describes_automatic_and_manual_flows_without_running_anything(self):
        status, output = self.invoke(["7", "4", "0", "0"])
        self.assertEqual(status, 0)
        self.workflows.dnp_contamination.assert_not_called()
        self.workflows.runner.doctor.assert_not_called()
        self.assert_no_single_analysis()
        self.assertIn("Le tabelle passano automaticamente alla seconda fase", output)
        self.assertIn("Le altre combinazioni richiedono la selezione esplicita", output)
        self.assertNotIn("La concatenazione non e' automatica", output)

    def test_submenu_cancel_and_invalid_choice_do_not_collect_or_execute(self):
        status, output = self.invoke(["W", "8", "", "0"])
        self.assertEqual(status, 0)
        self.assertIn("Scegliere un workflow da 1 a 4", output)
        self.workflows.dnp_contamination.assert_not_called()
        self.workflows.dnp_cpi.assert_not_called()

    def test_cpi_chain_uses_explicit_roles_one_confirmation_and_only_selected_steps(self):
        status, output = self.invoke(self.cpi_inputs() + ["1", "0", "0"])
        self.assertEqual(status, 0)
        self.workflows.dnp_cpi.assert_called_once_with(
            pairs=[("Pair1", self.bam, self.father)], reference=self.reference, panel=self.panel,
            parallel=False, popfreq=self.popfreq, err_const=DEFAULT_ERR_CONST,
            cpi_panel=None, cutoffs=None, cutoff_map=None, include_contamination=False,
            contamination_panel=None, snp_panel=None, run_name="cpi-chain",
        )
        self.workflows.dnp_contamination.assert_not_called()
        self.assert_no_single_analysis()
        self.assertEqual(output.count("Riepilogo prima dell'avvio"), 1)
        self.assertIn(f"cfDNA materno: {self.bam}", output)
        self.assertIn(f"Campione paterno: {self.father}", output)
        self.assertIn("Nomi e prefissi dei file CPI sono preparati automaticamente", output)
        self.assertIn("Risultati CPI:", output)
        self.assertNotIn("Risultati Contamination:", output)

    def test_multiple_pairs_can_share_paternal_sample_with_distinct_ids(self):
        status, output = self.invoke([
            "W", "2", "Pair1", self.bam, self.father,
            "Pair2", self.other_mother, self.father, "", self.reference, self.panel, "1",
            self.popfreq, "0", "", "", "", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.assertEqual(self.workflows.dnp_cpi.call_args.kwargs["pairs"], [
            ("Pair1", self.bam, self.father), ("Pair2", self.other_mother, self.father),
        ])
        self.assertIn("Coppia Pair1", output)
        self.assertIn("Coppia Pair2", output)
        self.assertNotIn("[ERRORE]", output)

    def test_full_chain_exposes_numeric_parameter_named_cutoffs_and_other_contamination_panel(self):
        status, output = self.invoke([
            "W", "3", "Pair1", self.bam, self.father, "",
            self.reference, self.panel, "2", "2", self.positions,
            self.popfreq, "2", "selected", self.positions, "", "0.001", "", "full",
            "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        arguments = self.workflows.dnp_cpi.call_args.kwargs
        self.assertTrue(arguments["include_contamination"])
        self.assertTrue(arguments["parallel"])
        self.assertEqual(arguments["contamination_panel"], self.positions)
        self.assertEqual(arguments["cutoffs"], [("selected", self.positions)])
        self.assertIsNone(arguments["cpi_panel"])
        self.assertEqual(arguments["err_const"], 0.001)
        self.assertIn("Contamination non filtra o modifica gli input CPI", output)
        self.assertIn("Risultati Contamination:", output)
        self.assertIn("Risultati CPI:", output)

    def test_edit_pair_preserves_id_and_maternal_role_while_replacing_paternal_bam(self):
        status, output = self.invoke(self.cpi_inputs() + [
            "2", "1",  # Review: edit the pairs field.
            "2", "1",  # Pair management: edit Pair1.
            "", "", self.other_father, "1",  # Keep ID/maternal, replace father, finish pairs.
            "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.assertEqual(self.workflows.dnp_cpi.call_args.kwargs["pairs"],
                         [("Pair1", self.bam, self.other_father)])
        self.assertIn(f"Campione paterno: {self.other_father}", output)

    def test_backtracking_inside_pair_keeps_id_and_explicit_roles(self):
        status, _ = self.invoke([
            "W", "2", "Pair1", self.bam, ":indietro", self.other_mother, self.father, "",
            self.reference, self.panel, "1", self.popfreq, "1", self.positions, "", "", "",
            "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        arguments = self.workflows.dnp_cpi.call_args.kwargs
        self.assertEqual(arguments["pairs"], [("Pair1", self.other_mother, self.father)])
        self.assertEqual(arguments["cpi_panel"], self.positions)

    def test_invalid_id_and_same_bam_in_both_roles_are_corrected_before_dispatch(self):
        status, output = self.invoke([
            "W", "2", "", "123", "Pair1", self.bam, self.bam, self.father, "",
            self.reference, self.panel, "1", self.popfreq, "0", "", "", "",
            "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.assertIn("ID coppia non valido", output)
        self.assertIn("Lo stesso BAM non puo' rappresentare sia", output)
        self.assertEqual(self.workflows.dnp_cpi.call_args.kwargs["pairs"], [("Pair1", self.bam, self.father)])
        self.workflows.dnp_cpi.assert_called_once()

    def test_cancel_during_pair_selection_does_not_execute(self):
        status, output = self.invoke(["W", "2", "Pair1", self.bam, ":annulla", "0"])
        self.assertEqual(status, 0)
        self.workflows.dnp_cpi.assert_not_called()
        self.assertIn("annullata prima dell'avvio", output)

    def test_full_chain_dry_run_does_not_claim_scientific_results(self):
        status, output = self.invoke(self.cpi_inputs(preset="3") + ["1", "0", "0"], dry_run=True)
        self.assertEqual(status, 0)
        self.assertTrue(self.workflows.dnp_cpi.call_args.kwargs["include_contamination"])
        self.assertIn("Esecuzione pianificata", output)
        self.assertNotIn("Esecuzione completata", output)
        self.assertNotIn("Risultati CPI:", output)

    def test_saved_defaults_keep_dnp_and_cpi_panels_separate_and_do_not_set_pairs_or_prefixes(self):
        store = PreferencesStore(self.root / "preferences.json")
        preferences = Preferences().with_workflow("1", {
            "reference": self.reference, "panel": self.panel, "parallel": "2",
        }).with_workflow("4", {
            "popfreq": self.popfreq, "cutoff_mode": "1", "panel": self.positions,
            "err_const": 0.002, "mother_prefix": "CustomMother", "father_prefix": "CustomFather",
        })
        store.save(preferences)
        status, output = self.invoke([
            "W", "2", "Pair1", self.bam, self.father, "",
            "", "", "", "", "", "", "", "", "", "1", "0", "0",
        ], preferences_store=store)
        self.assertEqual(status, 0)
        arguments = self.workflows.dnp_cpi.call_args.kwargs
        self.assertEqual(arguments["panel"], self.panel)
        self.assertEqual(arguments["cpi_panel"], self.positions)
        self.assertEqual(arguments["popfreq"], self.popfreq)
        self.assertEqual(arguments["err_const"], 0.002)
        self.assertTrue(arguments["parallel"])
        self.assertEqual(arguments["pairs"], [("Pair1", self.bam, self.father)])
        self.assertNotIn("CustomMother", output)
        self.assertNotIn("CustomFather", output)

    def test_review_changing_cpi_cutoff_mode_to_all_does_not_reuse_hidden_panel(self):
        status, _ = self.invoke([
            "W", "2", "Pair1", self.bam, self.father, "",
            self.reference, self.panel, "1", self.popfreq, "1", self.positions, "", "", "",
            "2", "6", "0", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        arguments = self.workflows.dnp_cpi.call_args.kwargs
        self.assertIsNone(arguments["cpi_panel"])
        self.assertIsNone(arguments["cutoffs"])
        self.assertIsNone(arguments["cutoff_map"])

    def test_dnp_chain_can_add_independent_snp_with_explicit_panel(self):
        answers = self.inputs()[:-2] + ["2", self.snp_panel, "with-snp", "1", "0", "0"]
        status, output = self.invoke(answers)
        self.assertEqual(status, 0)
        arguments = self.workflows.dnp_contamination.call_args.kwargs
        self.assertEqual(arguments["panel"], self.panel)
        self.assertEqual(arguments["snp_panel"], self.snp_panel)
        self.assertEqual(output.count("Riepilogo prima dell'avvio"), 1)
        self.assertIn("Il pannello DNP non viene riutilizzato", output)
        self.assertIn("non vengono usate da Contamination o CPI", output)
        self.assertIn("Risultati SNPcall per campione:", output)
        self.assert_no_single_analysis()

    def test_each_cpi_preset_can_add_independent_snp_without_changing_pair_roles(self):
        for preset in ("2", "3"):
            with self.subTest(preset=preset):
                self.workflows.reset_mock()
                answers = self.cpi_inputs(preset=preset)[:-2] + [
                    "2", self.snp_panel, "with-snp", "1", "0", "0",
                ]
                status, output = self.invoke(answers)
                self.assertEqual(status, 0)
                arguments = self.workflows.dnp_cpi.call_args.kwargs
                self.assertEqual(arguments["snp_panel"], self.snp_panel)
                self.assertEqual(arguments["pairs"], [("Pair1", self.bam, self.father)])
                self.assertEqual(arguments["include_contamination"], preset == "3")
                self.assertEqual(output.count("Riepilogo prima dell'avvio"), 1)

    def test_review_can_enable_then_disable_snp_without_leaking_hidden_panel(self):
        status, _ = self.invoke(self.inputs() + [
            "2", "7", "2", self.snp_panel,
            "2", "7", "1", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.assertIsNone(self.workflows.dnp_contamination.call_args.kwargs["snp_panel"])
        self.workflows.dnp_contamination.assert_called_once()

    def test_cancel_while_selecting_optional_snp_panel_does_not_execute(self):
        status, _ = self.invoke(self.inputs()[:-2] + ["2", ":annulla", "0"])
        self.assertEqual(status, 0)
        self.workflows.dnp_contamination.assert_not_called()
        self.workflows.snp_batch.assert_not_called()

    def test_snp_batch_bams_use_one_confirmation_and_separate_sample_results(self):
        status, output = self.invoke([
            "W", "4", "1", self.bam, self.father, "", self.reference,
            self.snp_panel, "snp-batch", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.workflows.snp_batch.assert_called_once_with(
            bams=[self.bam, self.father], bamlist=None, pileups=None,
            reference=self.reference, panel=self.snp_panel, run_name="snp-batch",
        )
        self.assertEqual(output.count("Riepilogo prima dell'avvio"), 1)
        self.assertIn("non vengono uniti conteggi di campioni diversi", output)
        self.assertIn("Risultati SNPcall per campione:", output)
        self.assertNotIn("Risultati DNPcall:", output)
        self.assert_no_single_analysis()

    def test_snp_batch_pileups_omit_reference_and_keep_qname_guidance(self):
        status, output = self.invoke([
            "W", "4", "2", self.pileup, self.other_pileup, "", self.snp_panel,
            "snp-pileups", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.workflows.snp_batch.assert_called_once_with(
            bams=None, bamlist=None, pileups=[self.pileup, self.other_pileup],
            reference=None, panel=self.snp_panel, run_name="snp-pileups",
        )
        self.assertIn("QNAME", output)
        self.assertTrue(any("Percorso del primo pileup SNP" in call.args[0]
                            for call in self.reader.call_args_list))
        self.assertIn("Il FASTA e i BAM delle altre modalita' non vengono usati", output)
        self.assert_no_single_analysis()

    def test_snp_batch_accepts_relative_bamlist(self):
        bamlist = self.file("batch-list.txt", '"sample with spaces.bam"\npaternal sample.bam\n')
        status, output = self.invoke([
            "W", "4", "3", bamlist, self.reference, self.snp_panel,
            "", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.workflows.snp_batch.assert_called_once_with(
            bams=None, bamlist=bamlist, pileups=None, reference=self.reference,
            panel=self.snp_panel, run_name=None,
        )
        self.assertIn("relativi alla cartella della lista", output)

    def test_snp_batch_mode_edit_to_pileup_does_not_forward_previous_bam_or_reference(self):
        status, _ = self.invoke([
            "W", "4", "1", self.bam, "", self.reference, self.snp_panel, "",
            "2", "1", "2", self.pileup, "", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        arguments = self.workflows.snp_batch.call_args.kwargs
        self.assertEqual(arguments["pileups"], [self.pileup])
        self.assertIsNone(arguments["bams"])
        self.assertIsNone(arguments["bamlist"])
        self.assertIsNone(arguments["reference"])

    def test_snp_batch_mode_edit_to_bam_does_not_forward_previous_pileups(self):
        status, _ = self.invoke([
            "W", "4", "2", self.pileup, "", self.snp_panel, "",
            "2", "1", "1", self.bam, "", self.reference, "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        arguments = self.workflows.snp_batch.call_args.kwargs
        self.assertEqual(arguments["bams"], [self.bam])
        self.assertEqual(arguments["reference"], self.reference)
        self.assertIsNone(arguments["pileups"])

    def test_snp_batch_rechecks_panel_when_switching_from_pileup_to_bam(self):
        edge_panel = self.file("position-one.tsv", "pos\tref\talt\nchr1:1\tA\tC\n")
        status, output = self.invoke([
            "W", "4", "2", self.pileup, "", edge_panel, "",
            "2", "1", "1", self.bam, "", self.reference, self.snp_panel,
            "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.assertEqual(self.workflows.snp_batch.call_args.kwargs["panel"], self.snp_panel)
        self.assertIn("La lista SNP precedente non e' compatibile", output)

    def test_snp_batch_cancel_and_dry_run_never_claim_scientific_results(self):
        answers = ["W", "4", "2", self.pileup, "", self.snp_panel, ""]
        status, output = self.invoke(answers + ["", "0"])
        self.assertEqual(status, 0)
        self.workflows.snp_batch.assert_not_called()
        self.assertIn("annullata prima dell'avvio", output)
        status, output = self.invoke(answers + ["1", "0", "0"], dry_run=True)
        self.assertEqual(status, 0)
        self.workflows.snp_batch.assert_called_once()
        self.assertIn("Esecuzione pianificata", output)
        self.assertNotIn("Risultati SNPcall per campione:", output)
        self.assertNotIn("Esecuzione completata", output)

    def test_snp_batch_saved_defaults_preserve_standalone_pileup_mode(self):
        store = PreferencesStore(self.root / "snp-preferences.json")
        store.save(Preferences().with_workflow("2", {
            "mode": "2", "reference": self.reference, "panel": self.snp_panel,
        }))
        status, _ = self.invoke([
            "W", "4", "", self.pileup, "", "", "", "1", "0", "0",
        ], preferences_store=store)
        self.assertEqual(status, 0)
        arguments = self.workflows.snp_batch.call_args.kwargs
        self.assertEqual(arguments["panel"], self.snp_panel)
        self.assertEqual(arguments["pileups"], [self.pileup])
        self.assertIsNone(arguments["reference"])

    def test_snp_batch_backtracking_preserves_selected_files(self):
        status, output = self.invoke([
            "W", "4", "1", self.bam, "", ":indietro", "1",
            self.reference, self.snp_panel, "", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.assertEqual(self.workflows.snp_batch.call_args.kwargs["bams"], [self.bam])
        self.assertIn("Elenco gia' inserito", output)


if __name__ == "__main__":
    unittest.main()
