from __future__ import annotations

import copy
import csv
from pathlib import Path
import tempfile
import unittest

from nipat_scientific.errors import PlanExecutionError
from nipat_scientific.snp_summary import finalize_snp_summaries


def rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class SnpSummaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.plan = {"steps": [], "presentation": {"samples": {}, "pairs": {}}}
        self.state = {"steps": []}
        self.render_calls = []

    def add_sample(self, name, genotype, *, panel="/input/SNP.tsv", reference="/input/ref.fa"):
        step = f"call_{len(self.plan['steps']) + 1:04d}"
        output = self.root / "steps" / step / "output"
        (output / "summary").mkdir(parents=True)
        table = output / "SNPcall_output.txt"
        table.write_text("chr\tpos\tREF\tALT\tGT\n"
                         f"chr2\t10\tA\tG\t{genotype}\nchr1\t20\tC\tT\tNA\n")
        (output / "summary/resources.tsv").write_text(
            "sample\tseconds\tresident_MB_start\tresident_MB_end\n"
            "sample_0001\t1.25\t20.5\t21.0\n")
        self.plan["steps"].append({"id": step, "workflow": "snp-call",
            "inputs": {"sample": name, "panel": panel, "reference": reference}, "parameters": {"mode": "bam"}})
        self.state["steps"].append({"id": step, "status": "succeeded", "artifacts": {
            "snp-tables": [{"sample": name, "path": table.relative_to(self.root).as_posix()}]}})
        self.plan["presentation"]["samples"][name] = "same.bam"
        return table

    def render(self, command, cwd, log):
        self.render_calls.append(command)
        for name in ("Unassigned_genotypes.pdf", "SNPs_covered_UpSet_plot.pdf"):
            (cwd / name).write_bytes(b"%PDF-1.4 fixture")
        log.write_text("rendered")
        return 0

    def finalize(self, render=None):
        return finalize_snp_summaries(self.plan, self.state, self.root, render or self.render)

    def test_three_samples_merge_in_order_with_na_and_unambiguous_original_names(self):
        inputs = [self.add_sample(name, gt) for name, gt in (("a", "0/0"), ("b", "0/1"), ("c", "NA"))]
        before = {path: path.read_bytes() for path in inputs}
        result = self.finalize()
        self.assertEqual(len(result), 1)
        summary = result[0]
        self.assertEqual(summary["samples"], ["a", "b", "c"])
        table = rows(self.root / summary["genotypes"]["path"])
        self.assertEqual(table[0], {"chr": "chr2", "pos": "10", "REF": "A", "ALT": "G",
                                   "GT_a": "0/0", "GT_b": "0/1", "GT_c": "NA"})
        self.assertEqual(table[1]["GT_a"], "NA")
        self.assertEqual([row["sample"] for row in rows(self.root / summary["resources"]["path"])], ["a", "b", "c"])
        self.assertEqual([row["display_name"] for row in rows(self.root / summary["sample_labels"]["path"])],
                         ["same.bam [a]", "same.bam [b]", "same.bam [c]"])
        self.assertEqual(len(self.render_calls), 1)
        self.assertEqual(before, {path: path.read_bytes() for path in inputs})

    def test_single_sample_and_incompatible_panels_are_not_merged(self):
        self.add_sample("a", "0/0")
        self.add_sample("b", "0/1", panel="/input/other.tsv")
        self.add_sample("c", "1/1", reference="/input/other.fa")
        self.assertEqual(self.finalize(), [])
        self.assertFalse((self.root / "snp_summary").exists())

    def test_different_scientific_parameters_form_distinct_comparison_groups(self):
        for sample in ("a", "b", "c", "d"):
            self.add_sample(sample, "0/1")
        self.plan["steps"][0]["parameters"]["scientific_settings"] = {"other_fraction_max": 0.2}
        self.plan["steps"][2]["parameters"]["scientific_settings"] = {"other_fraction_max": 0.2}
        result = self.finalize()
        self.assertEqual([group["samples"] for group in result], [["a", "c"], ["b", "d"]])
        self.assertEqual([group["scientific_settings"]["other_fraction_max"] for group in result], [0.2, 0.1])

    def test_repeated_analysis_does_not_duplicate_an_individual(self):
        self.add_sample("a", "0/0")
        self.add_sample("a", "0/1")
        self.add_sample("b", "1/1")
        result = self.finalize()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["samples"], ["a", "b"])
        self.assertEqual(rows(self.root / result[0]["genotypes"]["path"])[0]["GT_a"], "0/0")

    def test_allele_disagreement_cannot_be_hidden_by_coordinate_join(self):
        self.add_sample("a", "0/0")
        table = self.add_sample("b", "0/1")
        table.write_text(table.read_text().replace("\tA\tG\t", "\tA\tT\t"))
        with self.assertRaisesRegex(PlanExecutionError, "different loci or alleles"):
            self.finalize()
        self.assertEqual(self.render_calls, [])

    def test_malformed_resources_and_failed_renderer_fail_the_summary(self):
        first = self.add_sample("a", "0/0")
        self.add_sample("b", "1/1")
        resource = first.parent / "summary/resources.tsv"
        resource.write_text(resource.read_text().replace("\t1.25\t", "\tNaN\t"))
        with self.assertRaisesRegex(PlanExecutionError, "resource value"):
            self.finalize()

    def test_renderer_failure_is_not_reported_as_success(self):
        self.add_sample("a", "0/0")
        self.add_sample("b", "0/1")
        with self.assertRaisesRegex(PlanExecutionError, "rendering failed"):
            self.finalize(lambda command, cwd, log: 7)


if __name__ == "__main__":
    unittest.main()
