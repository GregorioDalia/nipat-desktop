import tempfile
import unittest
from pathlib import Path

from nipat.cli import DEFAULT_ERR_CONST
from nipat.paths import ProjectLayout
from nipat.wizard_forms import Cancelled, WorkflowForm


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


if __name__ == "__main__":
    unittest.main()
