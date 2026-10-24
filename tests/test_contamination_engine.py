from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nipat.errors import ValidationError as ClientValidationError
from nipat_scientific.contamination import prepare_contamination
from nipat_scientific.errors import ValidationError


class ContaminationEngineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nipat contamination ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.panel = self.inputs / "panel.txt"
        self.panel.write_text("chr1\t100\t101\tAA\tCC\n", encoding="utf-8")
        self.sample = self.inputs / "source.tsv"
        self.sample.write_text(
            "chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\n"
            "chr1\t100\t101\t95\t5\t0\n", encoding="utf-8",
        )
        self.work = self.root / "run/work"
        self.output = self.root / "run/output"
        self.work.mkdir(parents=True)
        self.output.mkdir()
        self.request = {
            "schema_version": 1, "workflow": "contamination", "panel": str(self.panel),
            "samples": [{"path": str(self.sample), "name": "Campione à 1.txt"}],
            "work_dir": str(self.work), "out_dir": str(self.output),
        }

    def assert_no_staging(self):
        self.assertFalse((self.work / "inputs").exists())
        self.assertFalse((self.work / "DNPpanel.txt").exists())
        self.assertFalse(any(self.output.iterdir()))

    def test_prepares_native_inputs_and_preserves_original_bytes(self):
        original = {source: source.read_bytes() for source in (self.panel, self.sample)}
        (self.work / "request.json").write_text("metadata already recorded", encoding="utf-8")
        native = prepare_contamination(self.request)
        self.assertEqual(native, [str(self.work / "DNPpanel.txt"),
                                  str(self.work / "inputs"), str(self.output)])
        self.assertEqual((self.work / "inputs/Campione à 1.txt").read_bytes(), original[self.sample])
        self.assertEqual((self.work / "DNPpanel.txt").read_text(encoding="utf-8"),
                         "n°DNP\tchr\tpos1\tpos2\nDNP001\tchr1\t100\t101\n")
        for source, contents in original.items():
            self.assertEqual(source.read_bytes(), contents)

    def test_native_and_headerless_panel_modes_remain_supported(self):
        for index, text in enumerate((
            "pos2\tannotation\tchr\tpos1\n105\tX\tchr1\t100\n",
            "chr1\t100\t105\n", "chr1 100 105 AA CC\n",
        )):
            with self.subTest(panel=text):
                self.panel.write_text(text, encoding="utf-8")
                request = {**self.request, "work_dir": str(self.root / f"work{index}"),
                           "out_dir": str(self.root / f"out{index}")}
                native = prepare_contamination(request)
                self.assertIn("DNP001\tchr1\t100\t105", Path(native[0]).read_text(encoding="utf-8"))

    def test_schema_errors_fail_before_any_preparation(self):
        cases = [None, [], {}, {**self.request, "schema_version": True},
                 {**self.request, "schema_version": 2}, {**self.request, "workflow": "cpi"},
                 {**self.request, "samples": []}, {**self.request, "samples": [None]},
                 {**self.request, "samples": [{"path": str(self.sample)}]},
                 {**self.request, "extra": "unsupported"},
                 {**self.request, "panel": "relative.txt"}]
        for request in cases:
            with self.subTest(request=request):
                with self.assertRaises(ValidationError):
                    prepare_contamination(request)
                self.assert_no_staging()

    def test_name_traversal_and_control_characters_are_rejected(self):
        for name in ("../escape.txt", "/escape.txt", "a\\b.txt", "a\nb.txt", "a\0.txt",
                     ".txt", "", "sample.tsv"):
            with self.subTest(name=name):
                request = {**self.request, "samples": [{"path": str(self.sample), "name": name}]}
                with self.assertRaisesRegex(ValidationError, "Nome campione non valido"):
                    prepare_contamination(request)
                self.assert_no_staging()

    def test_case_insensitive_name_collisions_are_rejected(self):
        request = {**self.request, "samples": [
            {"path": str(self.sample), "name": "Sample.txt"},
            {"path": str(self.sample), "name": "sample.txt"},
        ]}
        with self.assertRaisesRegex(ValidationError, "Nome file duplicato"):
            prepare_contamination(request)
        self.assert_no_staging()

    def test_all_tables_are_checked_before_first_copy(self):
        invalid = self.inputs / "invalid.txt"
        invalid.write_text("chr\tpos1\tpos2\nchr1\t100\t101\n", encoding="utf-8")
        request = copy.deepcopy(self.request)
        request["samples"].append({"path": str(invalid), "name": "invalid.txt"})
        with self.assertRaisesRegex(ValidationError, "colonne mancanti"):
            prepare_contamination(request)
        self.assert_no_staging()

    def test_missing_input_or_bad_panel_fail_before_first_copy(self):
        for field, value in (("panel", str(self.inputs / "missing.txt")),
                             ("samples", [{"path": str(self.inputs / "missing.txt"), "name": "a.txt"}])):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    prepare_contamination({**self.request, field: value})
                self.assert_no_staging()
        self.panel.write_text("broken panel", encoding="utf-8")
        with self.assertRaises(ValidationError):
            prepare_contamination(self.request)
        self.assert_no_staging()

    def test_existing_staging_and_output_are_not_overwritten(self):
        prepare_contamination(self.request)
        staged = self.work / "inputs/Campione à 1.txt"
        staged.write_text("keep prior result", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "già presente"):
            prepare_contamination(self.request)
        self.assertEqual(staged.read_text(), "keep prior result")
        (self.output / "result.txt").write_text("keep output", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "deve essere vuota"):
            prepare_contamination({**self.request, "work_dir": str(self.root / "another-work")})
        self.assertEqual((self.output / "result.txt").read_text(), "keep output")

    def test_inputs_cannot_be_inside_writable_directories(self):
        for key in ("work_dir", "out_dir"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValidationError, "Gli input non possono"):
                    prepare_contamination({**self.request, key: str(self.inputs)})
                self.assert_no_staging()

    def test_work_and_output_cannot_overlap(self):
        for output in (self.work, self.work / "output", self.work.parent):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValidationError, "non sovrapposte"):
                    prepare_contamination({**self.request, "out_dir": str(output)})
                self.assert_no_staging()

    def test_copy_error_leaves_original_unchanged_and_cannot_be_retried_in_place(self):
        before = self.sample.read_bytes()
        with patch("nipat_scientific.contamination.shutil.copy2", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                prepare_contamination(self.request)
        self.assertEqual(self.sample.read_bytes(), before)
        self.assertFalse((self.work / "DNPpanel.txt").exists())
        with self.assertRaisesRegex(ValidationError, "già presente"):
            prepare_contamination(self.request)

    def test_client_and_engine_use_the_same_validation_exception(self):
        self.assertIs(ClientValidationError, ValidationError)


if __name__ == "__main__":
    unittest.main()
