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

    def test_image_must_contain_the_supporting_scientific_sources(self):
        for name in verification.SUPPORTING_SOURCES:
            self.file(name, name + "\n")
        hashes = {name: verification.digest(self.root / name) for name in verification.SUPPORTING_SOURCES}
        with patch.object(verification, "PROJECT", self.root), patch.object(verification, "run", return_value=json.dumps(hashes)):
            self.assertEqual(verification.verify_supporting_sources("sha256:" + "a" * 64, self.root), hashes)
        hashes[next(iter(hashes))] = "0" * 64
        with patch.object(verification, "PROJECT", self.root), patch.object(verification, "run", return_value=json.dumps(hashes)):
            with self.assertRaisesRegex(ValueError, "supporting sources"):
                verification.verify_supporting_sources("sha256:" + "a" * 64, self.root)

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
            source = Path(arguments[-2])
            color = b"\xff\x00\x00" if source.parent.name == "candidate" else b"\x00\x00\x00"
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
        self.assertTrue(any(case.name == "dnp-varied-qualities" for case in cases))
        self.assertTrue(any(case.name == "snp-extra-columns" for case in cases))
        shared = next(case for case in cases if case.name == "cpi-shared-parents")
        pairs = shared.arguments[shared.arguments.index("--pairs") + 1].split(",")
        self.assertEqual(len(pairs), len(set(pairs)))
        self.assertTrue(any(left.split(":")[0] == right.split(":")[0]
                            for left, right in zip(pairs, pairs[1:])))
        self.assertTrue(any(left.split(":")[1] == right.split(":")[1]
                            for left, right in zip(pairs, pairs[1:])))

    def test_block_settings_do_not_change_the_reference_execution(self):
        cases = [case for case in verification.cases() if case.compare_pileup]
        self.assertEqual({dict(case.candidate_environment)["NIPAT_DNP_BLOCK_LOCI"] for case in cases}, {"1", "2", "3"})
        for case in cases:
            script = Path(verification.SCRIPTS[case.workflow])
            reference = verification.case_environment(case, "reference", verification.BASELINE / script)
            candidate = verification.case_environment(case, "candidate", script)
            self.assertNotIn("NIPAT_DNP_BLOCK_LOCI", reference)
            self.assertNotIn("NIPAT_DNP_KEEP_PILEUP", reference)
            self.assertEqual(reference["NIPAT_EQ_KEEP_PILEUP"], "1")
            self.assertEqual(candidate["NIPAT_DNP_KEEP_PILEUP"], "1")
            self.assertEqual(candidate["NIPAT_DNP_BLOCK_LOCI"], dict(case.candidate_environment)["NIPAT_DNP_BLOCK_LOCI"])

    def test_indexed_pileup_requires_exact_nonempty_bytes(self):
        reference = self.file("reference/mpileup.txt", "1\t60\tA\t1\t.\tI\tshared\n")
        candidate = self.file("candidate/mpileup.txt", reference.read_text())
        result = verification.compare_pileup(reference, candidate)
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["sha256"], verification.digest(reference))
        for different in ("", reference.read_text().replace("shared", "other"), reference.read_text() * 2):
            candidate.write_text(different)
            with self.assertRaisesRegex(ValueError, "pileup differs"):
                verification.compare_pileup(reference, candidate)
        candidate.unlink()
        with self.assertRaisesRegex(ValueError, "pileup is missing"):
            verification.compare_pileup(reference, candidate)

    def test_forced_partition_and_uncovered_window_must_be_observed(self):
        metadata = {"status": "succeeded", "block_loci_limit": 1, "samples": {"Boundary": {"blocks": [
            {"loci": 1, "raw_rows": 4}, {"loci": 1, "raw_rows": 0}]}}}
        path = self.file("work/dnp-blocks.json", json.dumps(metadata))
        self.assertEqual(verification.verify_block_execution(path, 1)["samples"]["Boundary"]["uncovered_blocks"], 1)
        with self.assertRaisesRegex(ValueError, "requested DNP block limit"):
            verification.verify_block_execution(path, 2)
        metadata["samples"]["Boundary"]["blocks"][1]["raw_rows"] = 4
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "uncovered windows"):
            verification.verify_block_execution(path, 1)

    def test_compatibility_fallback_cannot_stand_in_for_partition_coverage(self):
        reason = "legacy-repeated-qname-within-position"
        metadata = {"status": "succeeded", "block_loci_limit": 1,
                    "compatibility_reasons": [reason],
                    "samples": {"Boundary": {"blocks": [{"loci": 12, "raw_rows": 34}]}}}
        path = self.file("work/dnp-blocks.json", json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "compatibility path"):
            verification.verify_block_execution(path, 1)
        result = verification.verify_block_execution(path, 1, reason)
        self.assertEqual(result["samples"]["Boundary"]["blocks"], 1)
        metadata["samples"]["Boundary"]["blocks"].append({"loci": 1, "raw_rows": 0})
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "block boundaries"):
            verification.verify_block_execution(path, 1, reason)
        metadata["status"] = "started"
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "requested DNP block limit"):
            verification.verify_block_execution(path, 1, reason)

    def test_block_fixture_has_overlaps_global_types_indels_and_uncovered_tail(self):
        with patch.object(verification, "run", return_value=""):
            verification.make_dnp_block_inputs(self.root, "synthetic-image")
        panel = list(csv.reader((self.root / "dnp-blocks/panel.txt").read_text().splitlines(), delimiter="\t"))
        positions = [int(row[1]) for row in panel]
        self.assertIn(60, positions)
        self.assertIn(62, positions)
        self.assertIn(100000, positions)
        self.assertEqual(positions[-1], 1000)
        self.assertNotEqual(positions, sorted(positions))
        records = [row.split("\t") for row in (self.root / "dnp-blocks/Boundary.sam").read_text().splitlines()
                   if not row.startswith("@")]
        self.assertTrue(any(row[0] == "0001" and set(row[10]) == {"5"} for row in records))
        self.assertGreater(sum(row[0] == "shared" for row in records), 2)
        keys = [(row[0], row[2], row[3]) for row in records]
        self.assertEqual(len(keys), len(set(keys)))
        duplicate_records = [row.split("\t") for row in (self.root / "dnp-blocks/Duplicate.sam").read_text().splitlines()
                             if not row.startswith("@")]
        duplicate_keys = [(row[0], row[2], row[3]) for row in duplicate_records]
        self.assertLess(len(set(duplicate_keys)), len(duplicate_keys))
        self.assertTrue(all(any(operation in row[5] for row in records) for operation in "IDNS"))
        numeric = (self.root / "dnp-numeric/panel.txt").read_text()
        self.assertIn("01\t", numeric)
        self.assertIn("1\t", numeric)
        self.assertIn("100000\t100000\t100001\t", numeric)

    def test_generated_inputs_exercise_quality_range_and_optional_pileup_columns(self):
        with patch.object(verification, "run", return_value=""):
            inputs = verification.make_inputs(self.root, "synthetic-image")
        sam = (inputs / "dnp/Quality.sam").read_text().splitlines()
        qualities = [line.split("\t")[10] for line in sam if not line.startswith("@")]
        self.assertTrue(set(range(13, 94)).issubset({ord(c) - 33 for q in qualities for c in q}))
        basic = list(csv.reader((inputs / "snp/pileup.txt").read_text().splitlines(), delimiter="\t"))
        wide = list(csv.reader((inputs / "snp/pileup-wide.txt").read_text().splitlines(), delimiter="\t"))
        self.assertEqual([row[:7] for row in wide], basic)
        self.assertTrue(all(len(row) == 10 for row in wide))


if __name__ == "__main__":
    unittest.main()
