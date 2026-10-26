import tempfile
import unittest
from contextlib import chdir
from pathlib import Path

from nipat.cli import DEFAULT_ERR_CONST
from nipat.paths import ProjectLayout
from nipat.errors import ValidationError
from nipat.wizard_forms import Cancelled, Field, WorkflowForm, check_reference
from nipat.workflow_forms import DnpContaminationForm, DnpCpiForm, SnpBatchForm


class RecordingUI:
    def __init__(self, answers):
        self.answers = iter(str(answer) for answer in answers)
        self.events = []

    def message(self, text, kind="info"):
        self.events.append((kind, text))

    def heading(self, text):
        self.events.append(("heading", text))

    def prompt(self, label, default="", path=False):
        self.events.append(("prompt", label))
        return next(self.answers)

    def menu(self, title, choices, default=None):
        self.events.append(("menu", title))
        return next(self.answers) or default or ""


class WizardGuidanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.layout = ProjectLayout(self.root, self.root, self.root / "data",
                                    self.root / "runs", self.root / "compose.yaml")
        self.bam = self.file("sample one.bam", "")
        self.reference = self.file("ref.fa", ">chr1\nACGT\n")
        self.file("ref.fa.fai", "chr1\t4\t6\t4\t5\n")
        self.panel = self.file("panel.txt", "chr1\t1\t2\tAC\tGT\n")
        self.snp = self.file("snp.txt", "pos\tref\talt\nchr1:2\tC\tG\n")
        self.pileup = self.file("pileup.txt", "chr1\t2\tC\t1\t.\tI\tread1\n")
        self.table = self.file("counts.tsv", "chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\nchr1\t1\t2\t10\t0\t0\n")
        self.popfreq = self.file("pop.txt", "chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\nchr1\t1\t2\t0.5\t0.5\n")

    def file(self, name, contents):
        path = self.root / name
        path.write_text(contents, encoding="utf-8")
        return path

    def collect(self, choice, answers):
        ui = RecordingUI(answers)
        form = WorkflowForm(choice, ui, self.layout, DEFAULT_ERR_CONST)
        form.collect()
        return form, ui

    def assert_no_errors(self, ui):
        self.assertEqual([text for kind, text in ui.events if kind == "error"], [])

    def test_empty_enter_keeps_first_bam_prompt_and_does_not_finish_list(self):
        form, ui = self.collect("1", ["1", "", "", f'"{self.bam}"', "",
                                       self.reference, self.panel, "1", ""])
        self.assertEqual(form.arguments()["bams"], [self.bam])
        self.assert_no_errors(ui)
        prompts = [text for kind, text in ui.events if kind == "prompt"]
        self.assertEqual(prompts[:3], ["Percorso del primo BAM"] * 3)
        self.assertIn("Invio per continuare", prompts[3])
        mode_index = ui.events.index(("menu", "Input DNPcall"))
        selected_index = next(i for i, event in enumerate(ui.events)
                              if event[0] == "muted" and event[1].startswith("Selezione:"))
        first_prompt = ui.events.index(("prompt", prompts[0]))
        self.assertLess(mode_index, selected_index)
        self.assertLess(selected_index, first_prompt)

    def test_empty_required_inputs_are_neutral_in_all_workflows_and_modes(self):
        bamlist = self.file("bams.txt", '"sample one.bam"\n')
        cases = [
            ("1", ["2", "", bamlist, "", self.reference, "", self.panel, "1", ""], "bamlist", bamlist),
            ("2", ["1", "", self.bam, "", self.reference, "", self.snp, ""], "bam", self.bam),
            ("2", ["2", "", self.pileup, "", self.snp, ""], "pileup", self.pileup),
            ("3", ["1", "", self.table, "", "", self.panel, ""], "inputs", [self.table]),
            ("3", ["2", "", self.root, "", self.panel, ""], "input_dir", self.root),
            ("4", ["", self.root, "", "A1:A1", "", "", "", self.popfreq, "0", "", ""], "pairs", "A1:A1"),
        ]
        for choice, answers, key, expected in cases:
            with self.subTest(choice=choice, key=key):
                form, ui = self.collect(choice, answers)
                self.assertEqual(form.arguments()[key], expected)
                self.assert_no_errors(ui)
                self.assertIsNone(form.arguments()["run_name"])
                # Every new field has inline, muted guidance before its first input.
                for index, (kind, _) in enumerate(ui.events):
                    if kind == "heading":
                        self.assertEqual(ui.events[index + 1][0], "muted")

    def test_empty_cutoff_label_and_file_wait_without_losing_entries(self):
        form, ui = self.collect("4", [self.root, "A1:A1", "", "", self.popfreq,
                                       "2", "", "0", "", self.panel, "", "0", ""])
        self.assertEqual(form.arguments()["cutoffs"], [("0", self.panel)])
        self.assertEqual(form.arguments()["err_const"], 0)
        self.assert_no_errors(ui)

    def test_invalid_files_still_fail_validation_and_keep_previous_items(self):
        form, ui = self.collect("1", ["1", self.root / "missing.bam", "", self.bam,
                                       self.bam, "", self.reference, self.panel, "1", ""])
        self.assertEqual(form.arguments()["bams"], [self.bam])
        errors = [text for kind, text in ui.events if kind == "error"]
        self.assertEqual(len(errors), 2)
        self.assertIn("BAM non trovato", errors[0])
        self.assertIn("gia' presente", errors[1])
        for index, (kind, _) in enumerate(ui.events):
            if kind == "error":
                self.assertEqual(ui.events[index + 1][0], "muted")

    def test_empty_required_field_can_be_cancelled_without_accepting_empty_input(self):
        for choice, answers in (("1", ["1", "", ":annulla"]),
                                ("2", ["1", "", ":annulla"]),
                                ("3", ["1", "", ":annulla"]),
                                ("4", ["", ":annulla"])):
            with self.subTest(choice=choice):
                ui = RecordingUI(answers)
                form = WorkflowForm(choice, ui, self.layout, DEFAULT_ERR_CONST)
                with self.assertRaises(Cancelled):
                    form.collect()
                self.assert_no_errors(ui)
                self.assertNotIn("run_name", form.values)

    def test_reference_index_selection_is_actionable_and_never_silently_replaced(self):
        compressed = self.file("genome.fa.gz", "fixture")
        for suffix in (".fai", ".gzi", ".FAI"):
            reference = compressed if suffix == ".gzi" else self.reference
            index = self.file(reference.name + suffix, "index fixture")
            with self.subTest(suffix=suffix):
                ui = RecordingUI([index, ":annulla"])
                form = WorkflowForm("1", ui, self.layout, DEFAULT_ERR_CONST)
                field = next(field for field in form.fields() if field.key == "reference")
                with self.assertRaises(Cancelled):
                    form._read(field)
                errors = [text for kind, text in ui.events if kind == "error"]
                self.assertEqual(len(errors), 1)
                self.assertIn("non il file FASTA delle sequenze", errors[0])
                self.assertIn(str(reference), errors[0])
                self.assertNotIn(".fai.fai", errors[0])
                self.assertNotIn("reference", form.values)
                self.assertEqual([text for kind, text in ui.events if kind == "prompt"],
                                 ["File FASTA di riferimento"] * 2)

    def test_reference_validation_preserves_bgzf_and_real_missing_index_errors(self):
        check_reference(self.reference)
        missing = self.file("unindexed.fa", ">chr1\nACGT\n")
        with self.assertRaisesRegex(ValidationError, "Indice FASTA non trovato"):
            check_reference(missing)
        for extension in (".gz", ".bgz", ".bgzf"):
            compressed = self.file("indexed.fa" + extension, "fixture")
            self.file(compressed.name + ".fai", "index fixture")
            with self.subTest(extension=extension):
                with self.assertRaisesRegex(ValidationError, "Indice FASTA BGZF non trovato"):
                    check_reference(compressed)
                self.file(compressed.name + ".gzi", "index fixture")
                check_reference(compressed)

    def test_all_bam_forms_share_clear_reference_and_dnp_panel_guidance(self):
        ui = RecordingUI([])
        forms = [WorkflowForm("1", ui, self.layout, DEFAULT_ERR_CONST),
                 WorkflowForm("2", ui, self.layout, DEFAULT_ERR_CONST),
                 DnpContaminationForm("1", ui, self.layout, DEFAULT_ERR_CONST),
                 DnpCpiForm(ui, self.layout, DEFAULT_ERR_CONST, include_contamination=False),
                 DnpCpiForm(ui, self.layout, DEFAULT_ERR_CONST, include_contamination=True),
                 SnpBatchForm(ui, self.layout, DEFAULT_ERR_CONST)]
        for form in forms:
            with self.subTest(form=form.title):
                ui.events.clear()
                reference = next(field for field in form.fields() if field.key == "reference")
                self.assertEqual(reference.label, "File FASTA di riferimento")
                form._guide(reference)
                guidance = "\n".join(text for _, text in ui.events)
                self.assertIn("non il suo indice .fai o .gzi", guidance)
                self.assertIn("BGZF", guidance)
                if form.choice == "1":
                    form._guide(next(field for field in form.fields() if field.key == "panel"))
                    guidance = "\n".join(text for _, text in ui.events)
                    self.assertIn("posizioni e gli alleli da analizzare", guidance)
                    self.assertIn("il file puo' avere un altro nome", guidance)

    def test_relative_path_base_is_shown_at_each_file_and_list_prompt(self):
        with chdir(self.root):
            form, ui = self.collect("1", ["1", self.bam.name, "", self.reference.name,
                                           self.panel.name, "1", ""])
        self.assertEqual(form.arguments()["bams"], [self.bam])
        self.assertEqual(form.arguments()["panel"], self.panel)
        self.assertNotEqual(self.root, self.layout.data_dir)
        previous_prompt = -1
        file_prompts = {"Percorso del primo BAM", "Altro file (Invio per continuare)",
                        "File FASTA di riferimento", "Pannello DNP"}
        for index, (kind, label) in enumerate(ui.events):
            if kind != "prompt":
                continue
            if label in file_prompts:
                guidance = "\n".join(text for _, text in ui.events[previous_prompt + 1:index])
                self.assertIn(f"Base dei percorsi relativi: {self.root}", guidance)
                self.assertIn("L'impostazione Dati non cambia questa base", guidance)
            previous_prompt = index

    def test_cutoff_file_and_native_map_explain_relative_base(self):
        with chdir(self.root):
            for field, answers in (
                (Field("cutoff_file", "File cutoff", "file"), [self.panel.name]),
                (Field("cutoff_map", "Mappa cutoff"), ["panel=" + self.panel.name]),
            ):
                with self.subTest(field=field.key):
                    ui = RecordingUI(answers)
                    form = WorkflowForm("4", ui, self.layout, DEFAULT_ERR_CONST)
                    result = form._read(field)
                    self.assertEqual(result, self.panel if field.kind == "file" else answers[0])
                    self.assertIn(("muted", f"Base dei percorsi relativi: {self.root}"), ui.events)

    def test_pair_labels_and_file_roles_are_explained_before_input(self):
        father = self.file("father.bam", "fixture")
        ui = RecordingUI(["Coppia01", self.bam.name, father.name, ""])
        form = DnpCpiForm(ui, self.layout, DEFAULT_ERR_CONST, include_contamination=True)
        with chdir(self.root):
            pairs = form._pairs()
        self.assertEqual(pairs, [("Coppia01", self.bam, father)])
        first_prompt = next(index for index, event in enumerate(ui.events) if event == ("prompt", "ID coppia"))
        guidance = "\n".join(text for _, text in ui.events[:first_prompt])
        for phrase in ("etichetta scelta dall'utente", "Coppia01", "Non e' un parametro scientifico o un barcode",
                       "non deve coincidere con i nomi dei file", "ID distinto per ogni coppia",
                       "due campioni con ruolo noto", "Un solo BAM non basta"):
            self.assertIn(phrase, guidance)
        previous_prompt = first_prompt
        for index, (kind, label) in enumerate(ui.events[first_prompt + 1:], first_prompt + 1):
            if kind == "prompt":
                if label in {"BAM cfDNA materno", "BAM campione paterno"}:
                    self.assertIn(("muted", f"Base dei percorsi relativi: {self.root}"),
                                  ui.events[previous_prompt + 1:index])
                previous_prompt = index


if __name__ == "__main__":
    unittest.main()
