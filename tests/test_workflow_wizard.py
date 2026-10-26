"""Interaction checks for the one-confirmation scientific chain."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from nipat.cli import DEFAULT_ERR_CONST
from nipat.errors import RuntimeExecutionError
from nipat.paths import ProjectLayout
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
        self.reference = self.file("reference.fa", ">chr1\nACGT\n")
        self.file("reference.fa.fai", "chr1\t4\t6\t4\t5\n")
        self.panel = self.file("dnp.tsv", "chr1\t2\t3\tCG\tAT\n")
        self.positions = self.file("positions.tsv", "chr\tpos1\tpos2\nchr1\t2\t3\n")
        self.run = self.layout.runs_dir / "complete"
        (self.run / "output").mkdir(parents=True)
        self.workflows = Mock()
        self.workflows.dnp_contamination.return_value = self.run

    def file(self, name, contents):
        result = self.root / name
        result.write_text(contents, encoding="utf-8")
        return result

    def invoke(self, answers, **kwargs):
        messages = []
        reader = Mock(side_effect=[str(value) if isinstance(value, Path) else value for value in answers])
        result = run_wizard(
            self.workflows, self.layout, err_const=DEFAULT_ERR_CONST,
            read=reader, write=messages.append, **kwargs,
        )
        return result, "\n".join(messages)

    def inputs(self, *, choice="W", name="chain"):
        return [choice, "1", f'"{self.bam}"', "", self.reference, self.panel, "1", "1", name]

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
            parallel=False, contamination_panel=None, run_name="chain",
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
            "w", "2", bamlist, self.reference, self.panel, "2", "2", self.positions,
            "", "1", "0", "0",
        ])
        self.assertEqual(status, 0)
        self.workflows.dnp_contamination.assert_called_once_with(
            bams=None, bamlist=bamlist, reference=self.reference, panel=self.panel,
            parallel=True, contamination_panel=self.positions, run_name=None,
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
        status, output = self.invoke(["W", "1", "", "", ":annulla", "0"])
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
            "W", "1", self.bam, "", self.reference, self.panel, "1", "2", "",
            self.positions, "", "1", "0", "0",
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


if __name__ == "__main__":
    unittest.main()
