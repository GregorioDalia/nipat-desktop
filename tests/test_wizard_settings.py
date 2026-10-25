"""The guided settings persist only deliberate choices and never execute a workflow."""

from contextlib import chdir
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from nipat.cli import DEFAULT_ERR_CONST
from nipat.paths import ProjectLayout
from nipat.preferences import Preferences, PreferencesStore
from nipat.wizard import run_wizard


class WizardSettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        project = self.root / "app"
        project.mkdir()
        self.layout = ProjectLayout(project, self.root, self.root / "data",
                                    self.root / "runs", project / "compose.yaml")
        self.store = PreferencesStore(self.root / "preferences.json")
        self.workflows = Mock()
        self.run = self.layout.runs_dir / "known"
        (self.run / "output").mkdir(parents=True)
        for method in ("dnp_call", "snp_call", "contamination", "cpi"):
            getattr(self.workflows, method).return_value = self.run
        self.bam = self.file("one.bam", "")
        self.bamlist = self.file("bams.txt", "one.bam\n")
        self.ref = self.file("ref.fa", ">chr1\nAC\n")
        self.file("ref.fa.fai", "chr1\t2\t6\t2\t3\n")
        self.panel = self.file("DNP.tsv", "chr1\t1\t2\tAC\tGT\n")
        self.snp = self.file("SNP.tsv", "pos\tref\talt\nchr1:1\tA\tG\n")
        self.pileup = self.file("pileup.txt", "chr1\t1\tA\t1\t.\tI\tread1\n")
        self.popfreq = self.file("freq.tsv", "chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\nchr1\t1\t2\t0.5\t0.5\n")

    def file(self, name, contents):
        path = self.root / name
        path.write_text(contents, encoding="utf-8")
        return path

    def invoke(self, answers, **kwargs):
        messages = []
        reader = Mock(side_effect=[str(answer) for answer in answers])
        status = run_wizard(self.workflows, self.layout, err_const=DEFAULT_ERR_CONST,
                            preferences_store=self.store, read=reader,
                            write=messages.append, **kwargs)
        return status, "\n".join(messages)

    def assert_no_analyses(self):
        for method in ("dnp_call", "snp_call", "contamination", "cpi"):
            getattr(self.workflows, method).assert_not_called()
        self.workflows.runner.doctor.assert_not_called()

    def test_view_configuration_is_read_only_and_help_has_distinct_purpose(self):
        status, output = self.invoke(["5", "6", "0", "7", "2", "3", "4", "5", "0", "0"])
        self.assertEqual(status, 0)
        self.assertFalse(self.store.path.exists())
        self.assert_no_analyses()
        for text in ("Configura", "Guida e informazioni", "Verifica ambiente",
                     "Contamination: tabelle", "costanti interne", "full_output_*.txt",
                     "programma di installazione"):
            self.assertIn(text, output)

    def test_directories_are_saved_relative_to_selection_and_survive_restart(self):
        with chdir(self.root):
            status, output = self.invoke(["5", "1", "1", '"my data"', "2", "my runs", "9", "0", "0"])
        self.assertEqual(status, 0)
        self.assertEqual(self.store.load().data_dir, self.root / "my data")
        self.assertEqual(self.store.load().runs_dir, self.root / "my runs")
        self.assertTrue((self.root / "my runs").is_dir())
        self.assertTrue(self.run.is_dir())
        self.invoke(["0"])
        self.assertEqual(self.workflows.layout.runs_dir, self.root / "my runs")
        self.assert_no_analyses()
        self.assertIn("prossimi avvii", output)

    def test_cancelled_edits_and_empty_confirmation_never_save(self):
        self.invoke(["5", "1", "2", self.root / "discarded", "", "2", "4", "2", "0", "0", "0"])
        self.assertFalse(self.store.path.exists())
        self.assertFalse((self.root / "discarded").exists())
        self.assert_no_analyses()

    def test_dnp_defaults_are_reused_but_sample_and_run_are_selected_each_time(self):
        self.invoke(["5", "2", "1", "2", "2", self.ref, "3", self.panel, "4", "2", "9", "0", "0"])
        saved = self.store.load().workflow_defaults("1")
        self.assertEqual(saved, {"mode": "2", "reference": self.ref, "panel": self.panel, "parallel": "2"})
        self.assert_no_analyses()
        self.invoke(["1", "", self.bamlist, "", "", "", "new-run", "1", "0", "0"])
        self.workflows.dnp_call.assert_called_once_with(
            bams=None, bamlist=self.bamlist, reference=self.ref, panel=self.panel,
            parallel=True, run_name="new-run")
        self.assertEqual(self.store.load().workflow_defaults("1"), saved)

    def test_defaults_for_snp_contamination_and_cpi_are_separate(self):
        self.invoke(["5", "3", "1", "2", "2", self.snp, "9",
                     "4", "1", "2", "2", self.panel, "9",
                     "5", "1", "Plasma_", "2", ":vuoto", "3", self.popfreq,
                     "4", "1", "5", self.panel, "6", "0.001", "9", "0", "0"])
        prefs = self.store.load()
        self.assertEqual(prefs.workflow_defaults("2"), {"mode": "2", "panel": self.snp})
        self.assertEqual(prefs.workflow_defaults("3"), {"mode": "2", "panel": self.panel})
        self.assertEqual(prefs.workflow_defaults("4"), {
            "mother_prefix": "Plasma_", "father_prefix": "", "popfreq": self.popfreq,
            "cutoff_mode": "1", "panel": self.panel, "err_const": 0.001})
        self.assert_no_analyses()
        self.invoke(["4", self.root, "M:F", "", "", "", "", "", "", "", "1", "0", "0"])
        self.workflows.cpi.assert_called_once_with(
            input_dir=self.root, pairs="M:F", mother_prefix="Plasma_", father_prefix="",
            popfreq=self.popfreq, panel=self.panel, cutoffs=None, cutoff_map=None,
            err_const=0.001, run_name=None)

    def test_cutoff_defaults_are_absolute_and_can_be_cleared(self):
        with chdir(self.root):
            self.invoke(["5", "5", "4", "3", "5", "group=DNP.tsv", "9", "0", "0"])
        self.assertEqual(self.store.load().workflow_defaults("4")["cutoff_map"], f"group={self.panel}")
        self.invoke(["5", "5", "5", ":vuoto", "9", "0", "0"])
        self.assertNotIn("cutoff_map", self.store.load().workflow_defaults("4"))
        self.invoke(["5", "5", "4", "2", "5", "group", self.panel, "", "9", "0", "0"])
        self.assertEqual(self.store.load().workflow_defaults("4")["cutoffs"], [("group", self.panel)])
        self.invoke(["5", "5", "5", "4", "9", "0", "0"])
        self.assertNotIn("cutoffs", self.store.load().workflow_defaults("4"))
        self.assert_no_analyses()

    def test_missing_saved_file_is_reprompted_without_losing_other_defaults(self):
        self.store.save(Preferences(workflows={"2": {"mode": "2", "panel": self.root / "missing.tsv"}}))
        status, output = self.invoke(["2", "", self.pileup, "", self.snp, "", "1", "0", "0"])
        self.assertEqual(status, 0)
        self.assertIn("non trovato", output)
        self.assertEqual(self.workflows.snp_call.call_args.kwargs["panel"], self.snp)
        self.assertEqual(self.store.load().workflow_defaults("2")["panel"], self.root / "missing.tsv")

    def test_missing_cutoff_default_can_be_replaced_before_execution(self):
        missing = self.root / "missing-cutoff.tsv"
        self.store.save(Preferences(workflows={"4": {
            "cutoff_mode": "2", "cutoffs": [("old", missing)], "popfreq": self.popfreq}}))
        status, output = self.invoke([
            "4", self.root, "M:F", "", "", "", "", "1", "2", "new", self.panel,
            "", "", "", "1", "0", "0"])
        self.assertEqual(status, 0)
        self.assertIn("Sostituire l'elenco", output)
        self.assertEqual(self.workflows.cpi.call_args.kwargs["cutoffs"], [("new", self.panel)])
        self.assertEqual(self.store.load().workflow_defaults("4")["cutoffs"], [("old", missing)])

    def test_explicit_session_directory_wins_while_saved_future_value_is_retained(self):
        override = self.root / "explicit"
        self.invoke(["5", "1", "2", self.root / "next-time", "9", "0", "0"],
                    directory_overrides={"runs_dir": override})
        self.assertEqual(self.workflows.layout.runs_dir, override)
        self.assertEqual(self.store.load().runs_dir, self.root / "next-time")
        self.invoke(["0"])
        self.assertEqual(self.workflows.layout.runs_dir, self.root / "next-time")

    def test_malformed_settings_require_explicit_reset_and_preserve_analysis_files(self):
        self.store.path.write_text("{broken", encoding="utf-8")
        status, output = self.invoke(["1", "5", "2", "7", "0", "0", "0"])
        self.assertEqual(status, 0)
        self.assertEqual(self.store.path.read_text(), "{broken")
        self.assertIn("Impostazioni da correggere", output)
        self.assert_no_analyses()
        self.invoke(["5", "7", "1", "0", "0"])
        self.assertFalse(self.store.path.exists())
        self.assertTrue(self.run.is_dir())
        self.assertTrue(self.bam.exists())

    def test_saved_overlapping_directories_can_be_corrected_from_configuration(self):
        self.store.save(Preferences(runs_dir=self.layout.data_dir / "nested"))
        status, output = self.invoke(["1", "5", "1", "2", self.root / "repaired", "9", "0", "0"])
        self.assertEqual(status, 0)
        self.assertIn("senza sovrapporsi", output)
        self.assertEqual(self.store.load().runs_dir, self.root / "repaired")
        self.assert_no_analyses()

    def test_empty_review_never_launches_analysis(self):
        self.invoke(["2", "2", self.pileup, self.snp, "", "", "0"])
        self.assert_no_analyses()

    def test_failed_save_keeps_effective_defaults_and_original_file(self):
        self.store.save(Preferences(runs_dir=self.layout.runs_dir))
        original = self.store.path.read_bytes()
        self.store.save = Mock(side_effect=OSError("Accesso negato"))
        status, output = self.invoke(["5", "1", "2", self.root / "new", "9", "0", "0", "0"])
        self.assertEqual(status, 0)
        self.assertIn("Accesso negato", output)
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(self.workflows.layout.runs_dir, self.layout.runs_dir)


if __name__ == "__main__":
    unittest.main()
