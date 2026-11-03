"""Readable artifacts preserve canonical scientific identity and values."""

import csv
import json
from pathlib import Path
import tempfile
import unittest

from nipat_scientific.errors import ValidationError
from nipat_scientific.plan import validate_plan
from nipat_scientific.presentation import (
    _copy_table, _filename, _unique_labels, finish_presentation,
    normalize_presentation, prepare_presentation, step_presentation,
    validate_request_presentation,
)


class PresentationTests(unittest.TestCase):
    def test_exact_coverage_and_labels_are_data(self):
        labels = {"a": 'È un campione "A".bam', "b": "sample_0001.bam"}
        self.assertEqual(normalize_presentation({"samples": labels, "pairs": {}}, set(labels))["samples"], labels)
        for value in ({"a": "a.bam"}, {"a": "a.bam", "b": "b.bam", "c": "c.bam"}):
            with self.assertRaises(ValidationError):
                normalize_presentation({"samples": value, "pairs": {}}, {"a", "b"})
        for name in ("../escape", "a\\b", "a\tb", "a\nb", "a\x00b", "a\u202eb", ""):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                normalize_presentation({"samples": {"a": name}, "pairs": {}}, {"a"})

    def test_duplicate_names_are_distinct_and_portable(self):
        names = {"one": "é.bam", "two": "e\u0301.bam", "three": "É.bam"}
        labels = _unique_labels(names)
        self.assertEqual(labels, _unique_labels(dict(reversed(list(names.items())))))
        self.assertEqual(len(set(labels.values())), 3)
        for identity, original in names.items():
            self.assertIn(original, labels[identity])
            self.assertIn(identity, labels[identity])
        first, second = _filename("con: ?" + "界" * 600, "one"), _filename("con: ?" + "界" * 600, "two")
        self.assertNotEqual(first.casefold(), second.casefold())
        self.assertLess(len(first.encode()), 195)
        self.assertFalse(any(char in first for char in '/\\:*?"<>|'))

    def test_tables_replace_identity_only_and_keep_numeric_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "native.csv", Path(tmp) / "readable.csv"
            content = 'Pair,GT_sample_0001,N_REF,CPI_medianFF,other\n"pair",0/1,001,6.020000e-1,sample_0001\n'
            source.write_text(content, encoding="utf-8")
            _copy_table(source, target, {"pair": 'Madre: "A" | Padre: B', "GT_sample_0001": "GT_Campione à.bam", "sample_0001": "A.bam"})
            with target.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], ["Pair", "GT_Campione à.bam", "N_REF", "CPI_medianFF", "other"])
            self.assertEqual(rows[1], ['Madre: "A" | Padre: B', "0/1", "001", "6.020000e-1", "sample_0001"])
            self.assertEqual(source.read_text(encoding="utf-8"), content)

    def test_legacy_command_unchanged(self):
        request = {"workflow": "snp-call"}
        self.assertIsNone(validate_request_presentation(request))
        script = Path("/native.R")
        self.assertEqual(prepare_presentation(request, script, ["--a", "b"]), ["Rscript", str(script), "--a", "b"])

    def test_spreadsheet_labels_are_text_but_negative_numbers_stay_numeric(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "native.txt", Path(tmp) / "readable.txt"
            source.write_text("individuo\tGL0\nA\t-1.230\n", encoding="utf-8")
            _copy_table(source, target, {"A": ' =1+2&".bam"'})
            with target.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle, delimiter="\t"))
            self.assertEqual(rows[1], ['\' =1+2&".bam"', "-1.230"])

    def test_snp_export_is_readable_escaped_and_canonical_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work, output = root / "work", root / "output"
            work.mkdir(); output.mkdir()
            request = {"workflow": "snp-call", "work_dir": str(work), "out_dir": str(output),
                       "presentation": {"samples": {"sample_0001": "<script>alert(1)<.pileup"}, "pairs": {}}}
            command = prepare_presentation(request, Path("/native.R"), ["one", "two"])
            self.assertTrue(command[1].endswith("presentation.R"))
            self.assertEqual(command[2:], ["one", "two"])
            native = output / "SNPcall_output.txt"
            native.write_text("pos\tN_REF\n1\t010\n", encoding="utf-8")
            before = native.read_bytes()
            report = finish_presentation(request, root)
            self.assertEqual(report["status"], "complete")
            index = (root / report["index"]["path"]).read_text(encoding="utf-8")
            self.assertIn("&lt;script&gt;", index)
            self.assertNotIn("<script>", index)
            self.assertEqual(native.read_bytes(), before)
            readable = root / report["files"][0]["path"]
            with readable.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle, delimiter="\t"))
            self.assertEqual(rows, [["Sample", "pos", "N_REF"], ["<script>alert(1)<.pileup", "1", "010"]])

    def test_missing_plot_fails_visibly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "work").mkdir(); (root / "output").mkdir()
            request = {"workflow": "dnp-call", "samples": [{"sample_id": "sample_0001"}],
                       "work_dir": str(root / "work"), "out_dir": str(root / "output"),
                       "presentation": {"samples": {"sample_0001": "A.bam"}, "pairs": {}}}
            prepare_presentation(request, Path("/native.R"), [])
            config = json.loads((root / "work/presentation-config.json").read_text(encoding="utf-8"))
            for source in config["tables"]:
                target = root / "output" / source; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("chr\tGT_sample_0001\n1\t0/0\n", encoding="utf-8")
            for source in config["plots"]:
                target = root / "output" / source; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"%PDF-native")
            with self.assertRaisesRegex(ValidationError, "Esportazione assente"):
                finish_presentation(request, root)
            self.assertFalse((root / "work/presentation-report.json").exists())

    def test_reordered_plan_inputs_keep_identity_not_position(self):
        plan = {"presentation": {"samples": {"a": "A.bam", "b": "B.bam"}, "pairs": {}}}
        dnp = {"workflow": "dnp-call", "inputs": {"samples": ["b", "a"]}}
        contamination = {"workflow": "contamination", "inputs": {"samples": [{"sample": "b"}, {"sample": "a"}]}}
        self.assertEqual(step_presentation(plan, dnp, {})["samples"], {"sample_0001": "B.bam", "sample_0002": "A.bam"})
        self.assertEqual(step_presentation(plan, contamination, {})["samples"], {"table_0001": "B.bam", "table_0002": "A.bam"})
        bindings = [{"native_selection": "m001:f001", "pair": "family", "mother": {"sample": "b"}, "father": {"sample": "a"}}]
        cpi = step_presentation(plan, {"workflow": "cpi"}, {}, bindings)
        self.assertEqual(cpi["samples"], {"Motherm001": "B.bam", "Fatherf001": "A.bam"})
        self.assertEqual(cpi["pairs"]["m001:f001"], "family — Madre: B.bam | Padre: A.bam")

    def test_plan_preserves_complete_presentation_and_rejects_unknown_identity(self):
        plan = {"schema_version": 1, "samples": [{"id": "sample_a", "kind": "bam", "path": "/inputs/a.bam"}],
                "steps": [{"id": "dnp", "workflow": "dnp-call", "inputs": {"samples": ["sample_a"],
                           "reference": "/inputs/ref.fa", "panel": "/inputs/panel.txt"}, "parameters": {"parallel": False}}],
                "presentation": {"samples": {"sample_a": "Original à.bam"}, "pairs": {}}}
        canonical = validate_plan(plan)["plan"]
        self.assertEqual(canonical["presentation"], plan["presentation"])
        plan["presentation"]["samples"] = {"wrong": "Original à.bam"}
        with self.assertRaisesRegex(ValidationError, "plan.presentation"):
            validate_plan(plan)


if __name__ == "__main__":
    unittest.main()
