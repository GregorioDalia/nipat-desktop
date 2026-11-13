"""Regression and mutation tests for the external installed-workflow oracles."""

from collections import Counter
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
SPEC = importlib.util.spec_from_file_location("installed_workflows", ROOT / "scripts/acceptance/installed_workflows.py")
workflows = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflows)


class InstalledWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def write_table(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def prepared(self):
        generated = self.root / "inputs/generated"
        generated.mkdir(parents=True)
        calls = []

        def samtools(arguments):
            calls.append(arguments)
            # These are placeholders only for fixture construction; no engine is simulated.
            if "-o" in arguments:
                self.write(arguments[arguments.index("-o") + 1], b"fixture construction placeholder\n")

        metadata = workflows.prepare_inputs(FIXTURES, generated, samtools)
        return generated, metadata, calls

    def test_prepare_uses_installed_samtools_and_three_base_snp_windows(self):
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                  for folder in ("dnp_engine", "snp_engine") for path in (FIXTURES / folder).iterdir() if path.is_file()}
        generated, metadata, calls = self.prepared()
        self.assertEqual([call[0] for call in calls], ["faidx", "sort", "sort", "sort", "mpileup", "faidx", "sort", "sort"])
        self.assertEqual((metadata["combined"] / "snp-regions.bed").read_text(),
                         "chrSynthetic\t48\t51\nchrSynthetic\t118\t121\n")
        pileup_command = next(call for call in calls if call[0] == "mpileup")
        self.assertIn("--output-QNAME", pileup_command)
        self.assertNotIn("-B", pileup_command)
        for call in calls:
            for argument in call:
                if isinstance(argument, Path):
                    self.assertTrue(argument.is_relative_to(generated))
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})
        self.assertEqual(len(metadata["bams"]), 3)
        self.assertEqual(len(metadata["pileups"]), 3)

    def test_positive_sam_recipe_has_exact_counts_and_unique_read_names(self):
        _, metadata, _ = self.prepared()
        expected = {20: ("AC", "GT"), 110: ("TA", "CG"), 200: ("GC", "AT")}
        for role, counts in (("maternal", (96, 4)), ("paternal", (50, 50))):
            records = [line.split("\t") for line in (metadata["positive"] / f"{role}.sam").read_text().splitlines()
                       if not line.startswith("@")]
            self.assertEqual(len(records), 300)
            self.assertEqual(len({row[0] for row in records}), 300)
            self.assertTrue(all(row[5] == "62M" and row[10] == "I" * 62 for row in records))
            observed = Counter((int(row[3]), row[9][30:32]) for row in records)
            self.assertEqual(observed, Counter({(position, allele): count for position, alleles in expected.items()
                                                for allele, count in zip(alleles, counts)}))

    def test_cases_cover_modes_presets_inputs_and_specific_failures(self):
        generated, metadata, _ = self.prepared()
        cases = workflows.build_cases(FIXTURES, generated, metadata)
        identities = [case["id"] for case in cases]
        self.assertEqual(len(cases), 17)
        self.assertEqual(len(set(identities)), len(cases))
        self.assertTrue(all(re.fullmatch(r"[a-z0-9-]{1,80}", identity) for identity in identities))
        self.assertEqual({case["mode"] for case in cases if case.get("compare_group") == "all-five"}, {"serial", "auto", "cap2"})
        presets = {case["args"][1] for case in cases if case["args"][0] == "workflow"}
        self.assertTrue({"dnp-contamination", "dnp-cpi", "dnp-contamination-cpi", "snp-batch", "analyze"} <= presets)
        self.assertTrue(all(callable(case["validate"]) or case.get("expect_failure") for case in cases))
        corrupt = next(case for case in cases if case["id"] == "reject-corrupt-bam")
        pattern = corrupt["expect_failure"]
        self.assertRegex("[mpileup] fail to read the header of /inputs/bams/sample_0001.bam", pattern)
        self.assertNotRegex("Docker startup failed while executing dnp-call --bam corrupt.bam", pattern)
        self.assertNotRegex("WSL could not start samtools pileup", pattern)
        self.assertTrue(all("--run-name" not in case["args"] for case in cases))

    def test_snp_oracle_accepts_exact_fixture_and_rejects_mutations(self):
        expected = FIXTURES / "snp_engine/expected.tsv"
        self.assertEqual(workflows.check_snp(expected, expected), {"loci": 2, "fields_per_locus": 17})
        for field, value in (("N_REF", "999"), ("GT", "0/0"), ("GL1", "-99"),
                             ("ratio", "nan"), ("combined_counts", "4-1-2"), ("REF", "C")):
            with self.subTest(field=field):
                rows = workflows.table(expected)
                rows[0][field] = value
                actual = self.write_table(self.root / "actual.tsv", rows)
                with self.assertRaises(AssertionError):
                    workflows.check_snp(actual, expected)

    def test_snp_oracle_rejects_missing_duplicate_loci_and_extra_fields(self):
        expected = FIXTURES / "snp_engine/expected.tsv"
        original = workflows.table(expected)
        variants = [original[:1], original + original[:1], [{**row, "extra": "value"} for row in original]]
        for rows in variants:
            actual = self.write_table(self.root / "actual.tsv", rows)
            with self.assertRaises(AssertionError):
                workflows.check_snp(actual, expected)

    def test_positive_snp_oracle_uses_q40_binomial_likelihood(self):
        workflows._positive_snp_oracle(self.root, "maternal", 96, 4)
        rows = workflows.table(self.root / "maternal-expected.tsv")
        self.assertEqual([row["pos"] for row in rows], ["50", "140", "230"])
        for row in rows:
            self.assertEqual(row["GT"], "0/0")
            self.assertEqual((row["N_REF"], row["N_ALT"], row["N_Other"]), ("96", "4", "0"))
            self.assertAlmostEqual(float(row["GL0"]), 96 * math.log(.9999) + 4 * math.log(.0001))
            self.assertAlmostEqual(float(row["GL1"]), 100 * math.log(.5))
        self.assertEqual(rows[1]["combined_bases"], "C-T")
        self.assertEqual(rows[1]["combined_counts"], "4-96")

    def test_cpi_cutoffs_are_identified_by_table_content_not_staged_filename(self):
        directory = self.root / "curves"
        def curve(label, cpi):
            return [{"Iteration": str(index), "CPI": str(cpi), "log_CPI": str(math.log10(cpi)),
                     "Cutoff": label} for index in (2, 3, 4)]
        self.write_table(directory / "family_panel_1.tsv", curve("Full", 8))
        second = directory / "family_panel_2.tsv"
        self.write_table(second, curve("First", 2))
        workflows.check_positive_curves(directory, cutoffs=True)
        single = self.root / "single"
        self.write_table(single / "family.tsv", curve("ALL", 8))
        workflows.check_positive_curves(single, cutoffs=False)
        for label, cpi in (("First", 8), ("Full", 8), ("Unknown", 2)):
            with self.subTest(label=label, cpi=cpi):
                self.write_table(second, curve(label, cpi))
                with self.assertRaises(AssertionError):
                    workflows.check_positive_curves(directory, cutoffs=True)

    def dnp_output(self):
        run = self.root / "dnp"
        expected = workflows.table(FIXTURES / "dnp_engine/expected.tsv")
        summary = []
        for sample_index, sample in enumerate(("A", "B", "A"), 1):
            identity = f"sample_{sample_index:04d}"
            rows = []
            for row_index, source in enumerate(row for row in expected if row["sample"] == sample):
                row = {field: source[field] for field in ("chr", "pos1", "pos2", "REF", "ALT", "N_REF", "N_ALT", "N_Other", "GT", "total_count")}
                alleles = {source[allele]: int(source[count]) for allele, count in (("REF", "N_REF"), ("ALT", "N_ALT"), ("OTHER", "N_Other")) if int(source[count])}
                gl = [-99., -20 * math.log(2), -99.]
                if source["GT"] != "0/1":
                    gl[0 if source["GT"] == "0/0" else 2] = -1.
                row.update({f"GL{index}": str(value) for index, value in enumerate(gl)})
                row.update(combined_bases="-".join(alleles), combined_counts="-".join(map(str, alleles.values())),
                           reads_discarded_for_indels="0", ratio_reads_discarded_for_indels="0")
                rows.append(row)
                if sample_index == 1:
                    summary.append({field: source[field] for field in ("chr", "pos1", "pos2", "REF", "ALT")})
                summary[row_index][f"GT_{identity}"] = source["GT"]
            self.write_table(run / f"output/individual_outputs/full_output_{identity}.txt", rows)
            for suffix in ("N_genotypes", "Ref_read_count", "Alt_read_count", "Other_read_count"):
                self.write(run / f"output/plots/{identity}/{identity}_{suffix}.pdf", b"%PDF-1.4\n")
        self.write_table(run / "output/summary/output_AllGenotypes.txt", summary)
        for name in ("Unassigned_genotypes", "DNPs_covered_UpSet_plot"):
            self.write(run / f"output/summary/{name}.pdf", b"%PDF-1.4\n")
        return run

    def test_dnp_oracle_rejects_changed_count_genotype_and_likelihood(self):
        run = self.dnp_output()
        self.assertEqual(workflows.check_dnp(run, FIXTURES)["samples"], 3)
        path = run / "output/individual_outputs/full_output_sample_0001.txt"
        for field, value in (("N_REF", "19"), ("GT", "1/1"), ("GL1", "-20"), ("combined_counts", "19-2")):
            with self.subTest(field=field):
                run = self.dnp_output()
                rows = workflows.table(path)
                rows[0][field] = value
                self.write_table(path, rows)
                with self.assertRaises(AssertionError):
                    workflows.check_dnp(run, FIXTURES)

    def plan_output(self):
        parent = self.root / "plan"
        root = parent / "output/workflow"
        plan = {"steps": [{"id": "snp", "workflow": "snp-call"}]}
        self.write(root / "plan.json", json.dumps(plan))
        artifact = self.write(root / "steps/snp/output/scientific.tsv", "site\tcount\n1\t10\n")
        settings = json.dumps({"workflow": "snp-call", "parameters": {"minimum": 1}})
        self.write(root / "steps/snp/work/effective-scientific-settings.json", settings)
        self.write(root / "steps/snp/output/scientific-settings.json", settings)
        state = {"status": "succeeded", "exit_code": 0,
                 "plan_sha256": hashlib.sha256((root / "plan.json").read_bytes()).hexdigest(),
                 "steps": [{"id": "snp", "status": "succeeded", "exit_code": 0, "finished_utc": "2026-01-01T00:00:01Z",
                            "artifacts": {"table": {"path": "steps/snp/output/scientific.tsv", "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}}}]}
        self.write(root / "workflow-state.json", json.dumps(state))
        self.write(parent / "run.json", json.dumps({"status": "succeeded", "commands": [{"argv": ["execute-plan"]}]}))
        return parent, root, state

    def test_plan_requires_successful_steps_and_retained_artifact_hashes(self):
        parent, root, state = self.plan_output()
        workflows.check_plan(parent, ["snp-call"])
        for mutation in ("status", "hash", "path", "duplicate", "planhash"):
            with self.subTest(mutation=mutation):
                parent, root, state = self.plan_output()
                if mutation == "status":
                    state["steps"][0]["status"] = "blocked"
                elif mutation == "hash":
                    state["steps"][0]["artifacts"]["table"]["sha256"] = "0" * 64
                elif mutation == "path":
                    state["steps"][0]["artifacts"]["table"]["path"] = "../../outside.tsv"
                elif mutation == "duplicate":
                    state["steps"].append(state["steps"][0])
                else:
                    state["plan_sha256"] = "0" * 64
                self.write(root / "workflow-state.json", json.dumps(state))
                with self.assertRaises(AssertionError):
                    workflows.check_plan(parent, ["snp-call"])

    def test_plan_rejects_changed_applied_settings(self):
        parent, root, _ = self.plan_output()
        self.write(root / "steps/snp/output/scientific-settings.json", json.dumps({"workflow": "snp-call", "parameters": {"minimum": 99}}))
        with self.assertRaisesRegex(AssertionError, "Impostazioni"):
            workflows.check_plan(parent, ["snp-call"])


if __name__ == "__main__":
    unittest.main()
