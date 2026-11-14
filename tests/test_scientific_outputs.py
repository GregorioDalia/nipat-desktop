from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from nipat_scientific.errors import PlanExecutionError
from nipat_scientific.outputs import validate_standalone_outputs
from snp_output_helpers import write_snp_auxiliary


class ScientificOutputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "output"
        self.output.mkdir()
        panel = self.root / "panel.tsv"
        panel.write_text("pos\tref\talt\nchr1:10\ta\tg\n", encoding="utf-8")
        self.request = {"workflow": "snp-call", "panel": str(panel), "mode": "pileup",
                        "work_dir": str(self.root / "work"), "out_dir": str(self.output)}

    def settings(self, workflow):
        from nipat_scientific.settings import defaults, describe_settings
        (self.output / "scientific-settings.json").write_text(json.dumps({
            "schema_version": 1, "workflow": workflow, "parameters": defaults(workflow),
            "constants": describe_settings(workflow)["constants"]}))

    def snp(self, ratio, ref=1):
        path = self.output / "SNPcall_output.txt"
        path.write_text("chr\tpos\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\tratio\tGL0\tGL1\tGL2\tGT\treads_discarded_for_indels\tratio_reads_discarded_for_indels\tcombined_bases\tcombined_counts\n"
                        f"chr1\t10\tA\tG\t{ref}\t0\t0\t{ref}\t{ratio}\t"
                        + ("-0.0001\t-0.6931\t-9.21\t0/0" if ref else "NA\tNA\tNA\tNA")
                        + "\t0\t0\tNA\tNA\n", encoding="utf-8")
        write_snp_auxiliary(self.output)
        return path

    def test_scientific_settings_sidecar_must_match_schema_parameters_and_constants(self):
        from nipat_scientific.settings import normalize_settings, describe_settings
        self.snp("1")
        self.request["scientific_settings"] = {"other_fraction_max": 0.25}
        document = {"schema_version": 1, "workflow": "snp-call",
            "parameters": normalize_settings("snp-call", self.request["scientific_settings"]),
            "constants": describe_settings("snp-call")["constants"]}
        path = self.output / "scientific-settings.json"
        path.write_text(json.dumps(document))
        self.assertIn("scientific-settings", validate_standalone_outputs(self.request))
        for mutation in (lambda value: value.update(schema_version=999),
                         lambda value: value.update(schema_version=True),
                         lambda value: value["parameters"].update(other_fraction_max=0.9),
                         lambda value: value["parameters"].update(max_depth=False),
                         lambda value: value["parameters"].pop("max_depth"),
                         lambda value: value.update(constants={}),
                         lambda value: value.update(workflow="dnp-call")):
            invalid = copy.deepcopy(document)
            mutation(invalid)
            path.write_text(json.dumps(invalid))
            with self.assertRaises(PlanExecutionError):
                validate_standalone_outputs(self.request)
        path.unlink()
        with self.assertRaisesRegex(PlanExecutionError, "scientific-settings.json"):
            validate_standalone_outputs(self.request)

    def test_expected_na_and_anomalous_estimates_have_distinct_outcomes(self):
        for value, count, expected in (("NA", 0, None), ("NA", 1, "output.missing_estimate"),
                                       ("NaN", 0, "output.nonfinite"), ("Inf", 1, "output.nonfinite")):
            with self.subTest(value=value, count=count):
                path = self.snp(value, count)
                original = path.read_bytes()
                result = validate_standalone_outputs(self.request)
                self.assertEqual([w["code"] for w in result["quality_warnings"]], [expected] if expected else [])
                self.assertEqual(path.read_bytes(), original)
                if expected:
                    self.assertEqual(result["quality_warnings"][0]["context"], {"chr": "chr1", "pos": "10"})

    def test_missing_nonnumeric_and_badly_encoded_results_fail_cleanly(self):
        for value in ("", "unknown"):
            with self.subTest(value=value):
                self.snp(value)
                with self.assertRaises(PlanExecutionError):
                    validate_standalone_outputs(self.request)
        path = self.snp("1")
        path.write_bytes(b"\xff\xfeunreadable")
        with self.assertRaises(PlanExecutionError):
            validate_standalone_outputs(self.request)
        path.unlink()
        with self.assertRaises(PlanExecutionError):
            validate_standalone_outputs(self.request)

    def test_snp2_q_zero_negative_infinity_is_valid_but_nan_and_positive_infinity_fail(self):
        path = self.snp("1")
        template = path.read_text()
        path.write_text(template.replace("-0.0001", "-Inf"))
        self.assertEqual(validate_standalone_outputs(self.request)["quality_warnings"], [])
        for value in ("NaN", "Inf", "nonnumeric"):
            path.write_text(template.replace("-0.0001", value))
            with self.subTest(value=value), self.assertRaises(PlanExecutionError):
                validate_standalone_outputs(self.request)

    def test_snp2_alleles_and_unassigned_genotype_contract_are_checked(self):
        path = self.snp("1")
        template = path.read_text()
        for changed in (template.replace("chr1\t10\tA\tG", "chr1\t10\tA\tT"),
                        template.replace("0/0", "0|1"),
                        template.replace("\t1\t0\t0\t1\t1\t", "\t9\t0\t1\t10\t1\t")):
            path.write_text(changed)
            with self.assertRaises(PlanExecutionError):
                validate_standalone_outputs(self.request)
        # At exactly 10% Other, counts and GL stay available while GT is NA.
        path.write_text(template.replace("\t1\t0\t0\t1\t1\t", "\t9\t0\t1\t10\t1\t").replace("0/0", "NA"))
        write_snp_auxiliary(self.output)
        self.assertEqual(validate_standalone_outputs(self.request)["quality_warnings"], [])

    def test_snp2_missing_plots_resources_or_inconsistent_genotypes_are_rejected(self):
        for mutation in ("plot", "resources", "genotypes"):
            self.snp("1")
            if mutation == "plot":
                (self.output / "plots/sample_0001/sample_0001_Ref_read_count.pdf").unlink()
            elif mutation == "resources":
                (self.output / "summary/resources.tsv").unlink()
            else:
                path = self.output / "summary/SNPcall_AllGenotypes.txt"
                path.write_text(path.read_text().replace("0/0", "1/1"))
            with self.subTest(mutation=mutation), self.assertRaises(PlanExecutionError):
                validate_standalone_outputs(self.request)

    def test_contamination_summary_and_site_rows_must_agree(self):
        self.settings("contamination")
        request = {"workflow": "contamination", "samples": [{"name": "sample.txt"}],
                   "work_dir": str(self.root / "work"), "out_dir": str(self.output)}
        summary = self.output / "contamination_summary.txt"
        summary.write_text("individuo\tinformative_sites\tmean_contamination\tsd_contamination\n"
                           "sample\t1\t0.01\tNA\n", encoding="utf-8")
        table = self.output / "contamination_sample.txt"
        table.write_text("chr\tpos1\tpos2\tcontamination\nchr1\t10\t11\t0.01\n", encoding="utf-8")
        self.assertEqual(validate_standalone_outputs(request)["quality_warnings"], [])
        table.write_text("chr\tpos1\tpos2\tcontamination\n", encoding="utf-8")
        with self.assertRaisesRegex(PlanExecutionError, "site count"):
            validate_standalone_outputs(request)
        summary.write_text("individuo\tinformative_sites\tmean_contamination\tsd_contamination\n"
                           "sample\t1\t0.01\n", encoding="utf-8")
        with self.assertRaises(PlanExecutionError):
            validate_standalone_outputs(request)

    def test_cpin_summary_and_provenance_must_match_requested_settings(self):
        from nipat_scientific.settings import normalize_settings, describe_settings
        request = {"workflow": "cpin", "trios": "M:F:C", "marker_type": "SNP",
            "scientific_settings": {"min_child_reads": 5, "err_const_snp": 0.02},
            "work_dir": str(self.root / "work"), "out_dir": str(self.output)}
        effective = normalize_settings("cpin", request["scientific_settings"])
        sidecar = self.output / "scientific-settings.json"
        sidecar.write_text(json.dumps({"schema_version": 1, "workflow": "cpin", "parameters": effective,
            "constants": describe_settings("cpin")["constants"]}))
        native = "MotherM-FatherF-ChildC_SNPs"
        columns = ["Trio", "Marker_type", "Analysis", "N_sites", "N_heterozygous_child_sites",
            "N_homozygous_child", "Matching_sites", "Mismatching_sites", "Log10_CPI", "CPI",
            "Error_constant", "Min_child_reads"]
        rows = [dict(zip(columns, [native, "SNP", analysis, "1", "1", "0", "1", "0", "0", "1", "0.02", "5"]))
                for analysis in ("heterozygous_child_sites", "all_compatible_sites")]
        summary = self.output / "Summary_Postnatal_CPI.txt"

        def write_rows(values):
            with summary.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t")
                writer.writeheader()
                writer.writerows(values)

        write_rows(rows)
        for name in ("sites", "curves", "plots"):
            (self.output / name).mkdir()
        (self.output / "sites" / f"{native}_sites.tsv").write_text("Status\tPaternity_Index\tMismatch\nvalid\t1\tFALSE\n")
        for row in rows:
            (self.output / "curves" / f"{native}_{row['Analysis']}_curve.tsv").write_text(
                "Min_child_reads\tThrough_min_child_reads\tN_sites\tLog10_CPI\tMatching_sites\tMismatching_sites\n5\t5\t1\t0\t1\t0\n")
            (self.output / "plots" / f"{native}_{row['Analysis']}_CPIplot.pdf").write_bytes(b"%PDF-1.7 fixture")
        (self.output / "All_CPIplots.pdf").write_bytes(b"%PDF-1.7 fixture")
        self.assertIn("scientific-settings", validate_standalone_outputs(request))
        for field, value in (("Marker_type", "DNP"), ("Min_child_reads", "2"),
                             ("Error_constant", "0.001"), ("Error_constant", "NaN")):
            changed = copy.deepcopy(rows)
            changed[0][field] = value
            write_rows(changed)
            with self.subTest(field=field, value=value), self.assertRaises(PlanExecutionError):
                validate_standalone_outputs(request)
        write_rows(rows)
        sidecar.unlink()
        with self.assertRaisesRegex(PlanExecutionError, "scientific-settings.json"):
            validate_standalone_outputs(request)

    def test_dnp_preserves_uncovered_panel_locus_but_rejects_truncation(self):
        self.settings("dnp-call")
        panel = self.root / "DNP_list.txt"
        panel.write_text("chr1\t10\t11\tAA\tGG\nchr1\t20\t21\tAA\tGG\n", encoding="utf-8")
        request = {"workflow": "dnp-call", "panel": str(panel),
                   "samples": [{"sample_id": "sample_0001"}],
                   "work_dir": str(self.root / "work"), "out_dir": str(self.output)}
        directory = self.output / "individual_outputs"
        directory.mkdir()
        path = directory / "full_output_sample_0001.txt"
        header = "chr\tpos1\tpos2\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\tGT\n"
        covered = "chr1\t10\t11\tAA\tGG\t5\t0\t0\t5\t0/0\n"
        uncovered = "chr1\t20\t21\tAA\tGG\t0\t0\t0\tNA\tNA\n"
        path.write_text(header + covered + uncovered, encoding="utf-8")
        summary = self.output / "summary" / "output_AllGenotypes.txt"
        summary.parent.mkdir()
        summary_text = ("chr\tpos1\tpos2\tREF\tALT\tGT_sample_0001\n"
                        "chr1\t10\t11\tAA\tGG\t0/0\nchr1\t20\t21\tAA\tGG\tNA\n")
        summary.write_text(summary_text, encoding="utf-8")
        original = path.read_bytes()
        artifacts = validate_standalone_outputs(request)
        self.assertEqual(artifacts["quality_warnings"], [])
        self.assertEqual(artifacts["dnp-summary"]["genotypes"]["path"],
                         "output/summary/output_AllGenotypes.txt")
        self.assertEqual(path.read_bytes(), original)
        for invalid in (summary_text.replace("\tNA\n", "\t1/1\n"),
                        summary_text.replace("\tGG\tNA", "\tTT\tNA"),
                        summary_text.replace("GT_sample_0001", "GT_sample_0002"),
                        summary_text + summary_text.splitlines()[1] + "\n"):
            summary.write_text(invalid, encoding="utf-8")
            with self.assertRaisesRegex(PlanExecutionError, "DNP genotype summary"):
                validate_standalone_outputs(request)
        summary.unlink()
        with self.assertRaisesRegex(PlanExecutionError, "output_AllGenotypes.txt"):
            validate_standalone_outputs(request)
        summary.write_text(summary_text, encoding="utf-8")
        for contents in (header, header + covered):
            path.write_text(contents, encoding="utf-8")
            with self.assertRaisesRegex(PlanExecutionError, "loci"):
                validate_standalone_outputs(request)


if __name__ == "__main__":
    unittest.main()
