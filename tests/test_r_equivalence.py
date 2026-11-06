"""The differential gate must detect scientific changes, not just successful runs."""

import csv
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_r_equivalence", PROJECT / "scripts/verify_r_equivalence.py")
verification = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verification
spec.loader.exec_module(verification)


class REquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def file(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_reference_is_exact_stable_version_not_current_candidate(self):
        result = verification.verify_reference()
        self.assertEqual(result["source_commit"], "eafadf7002a9c7d7c1b9af9ccafc47d698a059e5")
        self.assertEqual(len(result["files"]), 6)

    def test_editing_both_reference_and_manifest_cannot_redefine_oracle(self):
        shutil.copytree(PROJECT / verification.BASELINE, self.root / verification.BASELINE)
        original = self.root / verification.BASELINE
        relative = next(iter(verification.EXPECTED_REFERENCE))
        (original / relative).write_text("# replaced reference\n", encoding="utf-8")
        manifest_path = original / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for item in manifest["files"]:
            if item["path"] == relative:
                item["sha256"] = verification.digest(original / relative)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest differs"):
            verification.verify_reference(self.root)

    def test_extra_reference_script_is_not_silently_accepted(self):
        shutil.copytree(PROJECT / verification.BASELINE, self.root / verification.BASELINE)
        (self.root / verification.BASELINE / "extra.R").write_text("stop('unexpected')\n")
        with self.assertRaisesRegex(ValueError, "modified or is incomplete"):
            verification.verify_reference(self.root)

    def test_exact_tables_pass_and_ignored_logs_are_not_scientific_oracles(self):
        content = "site\tcount\tGL\n2\t10\t-0.123456789012345\n1\t0\tNA\n"
        self.file("reference/result.tsv", content)
        self.file("candidate/result.tsv", content)
        self.file("reference/runtime.log", "time=12\n")
        self.file("candidate/runtime.log", "time=8\n")
        result = verification.compare_tables(self.root / "reference", self.root / "candidate")
        self.assertEqual(set(result), {"result.tsv"})

    def test_scientific_value_schema_order_and_missing_values_all_fail(self):
        baseline = "site\tcount\tGL\n2\t10\t-0.123456789012345\n1\t0\tNA\n"
        self.file("reference/result.tsv", baseline)
        for label, value in {
            "integer": baseline.replace("10", "11", 1),
            "unrounded": baseline.replace("-0.123456789012345", "-0.123456789012346"),
            "schema": baseline.replace("count", "reads"),
            "NA": baseline.replace("NA", "0"),
            "order": "site\tcount\tGL\n1\t0\tNA\n2\t10\t-0.123456789012345\n",
        }.items():
            with self.subTest(label=label):
                self.file("candidate/result.tsv", value)
                with self.assertRaisesRegex(ValueError, "Scientific table differs"):
                    verification.compare_tables(self.root / "reference", self.root / "candidate")

    def test_missing_and_empty_tables_fail(self):
        (self.root / "reference").mkdir()
        (self.root / "candidate").mkdir()
        with self.assertRaisesRegex(ValueError, "missing or differ"):
            verification.compare_tables(self.root / "reference", self.root / "candidate")
        self.file("reference/a.csv", "a,b\n1,2\n")
        self.file("candidate/b.csv", "a,b\n1,2\n")
        with self.assertRaisesRegex(ValueError, "missing or differ"):
            verification.compare_tables(self.root / "reference", self.root / "candidate")

    def test_image_must_contain_the_candidate_sources(self):
        hashes = {p: verification.digest(PROJECT / p) for p in verification.SCRIPTS.values()}
        with patch.object(verification, "run", return_value=json.dumps(hashes)):
            self.assertEqual(verification.verify_image_sources("sha256:" + "a" * 64, self.root), hashes)
        hashes[next(iter(hashes))] = "0" * 64
        with patch.object(verification, "run", return_value=json.dumps(hashes)):
            with self.assertRaisesRegex(ValueError, "does not contain"):
                verification.verify_image_sources("sha256:" + "a" * 64, self.root)

    def test_pdf_pixel_differences_are_rejected_but_metadata_is_not_compared(self):
        self.file("reference/plot.pdf", "%PDF-1.4\nmetadata=first\n")
        self.file("candidate/plot.pdf", "%PDF-1.4\nmetadata=second\n")

        def render(arguments):
            Path(arguments[-1] + "-1.ppm").write_bytes(b"P6\n1 1\n255\n\x00\x00\x00")
            return ""

        with patch.object(verification, "command", side_effect=render):
            result = verification.compare_pdfs(self.root / "reference", self.root / "candidate", self.root / "raster-pass")
        self.assertEqual(result["plot.pdf"]["pages"], 1)

        def changed_render(arguments):
            color = b"\xff\x00\x00" if "/candidate/" in arguments[-2] else b"\x00\x00\x00"
            Path(arguments[-1] + "-1.ppm").write_bytes(b"P6\n1 1\n255\n" + color)
            return ""

        with patch.object(verification, "command", side_effect=changed_render):
            with self.assertRaisesRegex(ValueError, "Rendered scientific PDF differs"):
                verification.compare_pdfs(self.root / "reference", self.root / "candidate", self.root / "raster-fail")

    def test_bind_mount_quotes_comma_in_host_path(self):
        path = self.root / "input with , comma"
        arguments = next(csv.reader([verification.mount(path, "/inputs", readonly=True)]))
        self.assertEqual(arguments, ["type=bind", f"source={path}", "target=/inputs", "readonly"])

    def test_cases_cover_all_workflows_without_private_bam(self):
        cases = verification.cases()
        self.assertEqual({case.workflow for case in cases}, set(verification.SCRIPTS))
        self.assertEqual(len({case.name for case in cases}), len(cases))
        self.assertTrue(any("--parallel" in case.arguments for case in cases))
        self.assertTrue(any(case.name == "contamination-panel-only" for case in cases))
        self.assertTrue(any(case.name == "cpi-zero-error" for case in cases))


if __name__ == "__main__":
    unittest.main()
