"""Mutation tests for independent installed-model acceptance oracles."""

from collections import Counter
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installed_models", ROOT / "scripts/acceptance/installed_models.py")
models = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(models)


class InstalledModelsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run = self.root / "run"

    def write(self, name, contents):
        path = self.run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, bytes):
            path.write_bytes(contents)
        else:
            path.write_text(contents, encoding="utf-8")
        return path

    def pdf(self, name):
        self.write("output/" + name, b"%PDF-1.4\n" + b"fixture-content\n" * 10 + b"%%EOF\n")

    def settings(self, workflow, **overrides):
        # These are observed payload metadata, not expected numerical answers.
        registry = json.loads((ROOT / "src/nipat_scientific/settings_data.json").read_text())
        module = registry["workflows"][workflow]
        parameters = {name: entry["default"] for name, entry in module["parameters"].items()}
        parameters.update(overrides)
        record = {"schema_version": 1, "workflow": workflow, "parameters": parameters,
                  "constants": module["constants"]}
        for path in ("work/effective-scientific-settings.json", "output/scientific-settings.json"):
            self.write(path, json.dumps(record))

    def contamination(self, include_zero=True):
        self.settings("contamination", include_zero=include_zero)
        header = "individuo\tinformative_sites\tmean_contamination\tsd_contamination\n"
        self.write("output/contamination_summary.txt", header + (
            "Sample1\t2\t0.025\t0.0353553390593274\n" if include_zero else "Sample1\t1\t0.05\tNA\n"))
        self.write("output/contamination_Sample1.txt",
                   "chr\tpos\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\tratio_REF_ALT\tratio_Other\tN_unexpected\tcontamination\n"
                   "chr1\t100\tA\tC\t95\t5\t11\t111\t0.95\t0.0990990990990991\t5\t0.05\n" + (
                       "chr1\t200\tA\tC\t100\t0\t0\t100\t1\t0\t0\t0\n" if include_zero else ""))

    def cpi(self):
        self.settings("cpi")
        self.write("output/Summary_FetalFraction_CPI.csv",
                   "Pair,N_sites_mother,N_sites_father,Median_fetal_fraction_raw,Median_fetal_fraction_percent,"
                   "Max_logCPI,Min_logCPI,Median_logCPI,Mean_logCPI,CPI_medianFF,Error_constant,Min_fetal_reads,Marker_type\n"
                   "MotherM-FatherF_SNPs,3,3,0.06,6,1.301,0.301,0.602,0.735,0.602,0.001,2,SNP\n"
                   "MotherN-FatherN_SNPs,0,0,NA,NA,NA,NA,NA,NA,NA,0.001,2,SNP\n")
        header = "Iteration\tInfSites_mother\tInfSites_father\tCPI\tlog_CPI\tMismatch\tNotMismatch\tCutoff\n"
        self.write("output/curves/MotherM-FatherF_SNPs_panel_1.tsv", header +
                   "2\t3\t3\t20\t1.30102999566398\t0\t3\tALL\n"
                   "3\t2\t2\t4\t0.602059991327962\t0\t2\tALL\n"
                   "4\t1\t1\t2\t0.301029995663981\t0\t1\tALL\n")
        self.write("output/curves/MotherN-FatherN_SNPs_panel_1.tsv", header)
        for name in ("MotherM-FatherF_SNPs", "MotherN-FatherN_SNPs", "All"):
            self.pdf(f"plots/{name}_CPIplot.pdf" if name != "All" else "plots/All_CPIplots.pdf")

    def cpin(self):
        self.settings("cpin")
        identity = "MotherM-FatherF-ChildC_SNPs"
        self.write("output/Summary_Postnatal_CPI.txt",
                   "Trio\tMarker_type\tAnalysis\tN_sites\tN_heterozygous_child_sites\tN_homozygous_child\tMatching_sites\t"
                   "Mismatching_sites\tLog10_CPI\tCPI\tError_constant\tMin_child_reads\n" +
                   identity + "\tSNP\theterozygous_child_sites\t2\t2\t0\t1\t1\t-2.50514997831991\t0.003125\t0.001\t2\n" +
                   identity + "\tSNP\tall_compatible_sites\t3\t2\t1\t2\t1\t-2.28330122870355\t0.00520833333333333\t0.001\t2\n")
        self.write(f"output/sites/{identity}_sites.tsv",
                   "chr\tpos\tStatus\tPaternity_Index\tChild_support\tMismatch\tPaternal_transmission\tRequired_paternal_allele\n"
                   "chr1\t100\teligible\t1.25\t5\tFALSE\t0.5\tALT\n"
                   "chr1\t200\teligible\t0.0025\t6\tTRUE\t0\tALT\n"
                   "chr1\t300\teligible\t1.66666666666667\t10\tFALSE\t1\tREF\n"
                   "chr1\t400\tmother_child_incompatible\tNA\tNA\tNA\tNA\tNA\n"
                   "chr1\t500\tmother_not_homozygous\tNA\tNA\tNA\tNA\tNA\n"
                   "chr1\t600\tinsufficient_child_support\tNA\t1\tNA\tNA\tALT\n"
                   "chr1\t700\tquality_filter\tNA\tNA\tNA\tNA\tNA\n"
                   "chr1\t800\tquality_filter\tNA\t5\tNA\tNA\tALT\n"
                   "chr1\t900\tfather_unassigned\tNA\t5\tNA\tNA\tALT\n")
        header = "Min_child_reads\tThrough_min_child_reads\tN_sites\tLog10_CPI\tMatching_sites\tMismatching_sites\n"
        self.write(f"output/curves/{identity}_heterozygous_child_sites_curve.tsv", header +
                   "2\t5\t2\t-2.50514997831991\t1\t1\n6\t6\t1\t-2.60205999132796\t0\t1\n")
        self.write(f"output/curves/{identity}_all_compatible_sites_curve.tsv", header +
                   "2\t5\t3\t-2.28330122870355\t2\t1\n6\t6\t2\t-2.38021124171161\t1\t1\n"
                   "7\t10\t1\t0.221848749616356\t1\t0\n")
        for selection in ("heterozygous_child_sites", "all_compatible_sites"):
            self.pdf(f"plots/{identity}_{selection}_CPIplot.pdf")
        self.pdf("All_CPIplots.pdf")

    def mutate_table(self, name, row_index, column, value):
        path = self.run / "output" / name
        delimiter = "," if path.suffix == ".csv" else "\t"
        rows = list(csv.DictReader(io.StringIO(path.read_text()), delimiter=delimiter))
        rows[row_index][column] = value
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter=delimiter)
            writer.writeheader()
            writer.writerows(rows)

    def test_matrix_covers_34_positive_and_three_negative_cases_without_modifying_sources(self):
        fixtures = ROOT / "tests/fixtures"
        before = models.tree_hashes(fixtures / "five_modules")
        cases = models.build_cases(fixtures, self.root / "generated")
        self.assertEqual(len(cases), 37)
        self.assertEqual(len({case["id"] for case in cases}), 37)
        self.assertEqual(Counter(case["category"] for case in cases),
                         {"downstream-analytical": 16, "downstream-batch": 18, "invalid-input": 3})
        self.assertEqual(sum(callable(case["validate"]) for case in cases), 34)
        groups = {}
        for case in cases:
            self.assertTrue(callable(case["validate"]) or (case["validate"] is None and case["expect_failure"]))
            if "compare_group" in case:
                groups.setdefault(case["compare_group"], set()).add(case["mode"])
            paths = [argument for argument in case["args"] if isinstance(argument, Path)]
            self.assertTrue(paths and all(path.exists() and path.is_relative_to(self.root / "generated") for path in paths))
        self.assertEqual(len(groups), 6)
        self.assertTrue(all(modes == {"serial", "auto", "cap2"} for modes in groups.values()))
        self.assertEqual(models.tree_hashes(fixtures / "five_modules"), before)
        # The mismatch and metadata variants are applied only to their own copies.
        mismatch = self.root / "generated/models-snp-cpi-mismatch/FatherF.txt"
        self.assertEqual(models.table(mismatch, {"N_REF", "N_ALT"})[1]["N_ALT"], "0")
        baseline = self.root / "generated/models-snp-cpi-default/FatherF.txt"
        self.assertEqual(models.table(baseline, {"N_ALT"})[1]["N_ALT"], "50")
        self.assertIn("unused_metadata", (self.root / "generated/models-snp-cpi-metadata-na/population.tsv").read_text())
        batch = next(case for case in cases if case["id"] == "models-snp-cpin-batch3-auto")
        self.assertIn("M1:F1:C1,M2:F2:C2,M3:F3:C3", batch["args"])
        with self.assertRaises(FileExistsError):
            models.build_cases(fixtures, self.root / "generated")

    def test_expected_invalid_inputs_match_the_real_cli_diagnostic_before_execution(self):
        cases = models.build_cases(ROOT / "tests/fixtures", self.root / "generated")
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "NIPAT_PROJECT_DIR": str(ROOT),
                       "NIPAT_WORKSPACE_DIR": str(self.root), "NIPAT_DATA_DIR": str(self.root / "data"),
                       "NIPAT_RUNS_DIR": str(self.root / "runs"), "NIPAT_BACKEND": "native"}
        if os.name == "nt":
            environment.update(NIPAT_BACKEND="wsl", NIPAT_WSL_DISTRO="NIPAT-Desktop-test")
        for case in (item for item in cases if item.get("expect_failure")):
            with self.subTest(case=case["id"]):
                result = subprocess.run([sys.executable, "-m", "nipat", "--dry-run", *map(str, case["args"]),
                                         "--run-name", case["id"]],
                                        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertRegex(result.stderr, case["expect_failure"])
                for unrelated in ("Docker unavailable", "WSL failed", "Python import failed"):
                    self.assertNotRegex(unrelated, case["expect_failure"])
        self.assertFalse(list((self.root / "runs").rglob("run.json")))

    def test_all_three_independent_positive_readouts_pass(self):
        for workflow in ("contamination", "cpi", "cpin"):
            with self.subTest(workflow=workflow):
                self.run = self.root / workflow
                getattr(self, workflow)()
                result = models.validate_model(self.run, workflow=workflow, marker="SNP")
                self.assertTrue(result["scientific_sha256"])
                self.assertEqual(result["summary_rows"], 1 if workflow == "contamination" else 2)
                json.dumps(result)

    def test_contamination_rejects_wrong_other_denominator_and_false_zero_sd(self):
        self.contamination()
        self.mutate_table("contamination_Sample1.txt", 0, "ratio_Other", "0.11")
        with self.assertRaisesRegex(ValueError, "ratio_Other"):
            models.validate_model(self.run, workflow="contamination", marker="SNP")
        self.contamination(include_zero=False)
        models.validate_model(self.run, workflow="contamination", marker="SNP", include_zero=False)
        self.mutate_table("contamination_summary.txt", 0, "sd_contamination", "0")
        with self.assertRaisesRegex(ValueError, "expected explicit NA"):
            models.validate_model(self.run, workflow="contamination", marker="SNP", include_zero=False)

    def test_cpi_rejects_zero_in_place_of_no_sites_na(self):
        self.cpi()
        self.mutate_table("Summary_FetalFraction_CPI.csv", 1, "CPI_medianFF", "0")
        with self.assertRaisesRegex(ValueError, "expected explicit NA"):
            models.validate_model(self.run, workflow="cpi", marker="SNP")

    def test_cpi_rejects_missing_or_numerically_changed_curve(self):
        self.cpi()
        name = "curves/MotherM-FatherF_SNPs_panel_1.tsv"
        self.mutate_table(name, 1, "CPI", "4.01")
        with self.assertRaisesRegex(ValueError, "CPI curve"):
            models.validate_model(self.run, workflow="cpi", marker="SNP")
        self.cpi()
        (self.run / "output" / name).unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            models.validate_model(self.run, workflow="cpi", marker="SNP")

    def test_cpin_rejects_site_mismatch_or_wrong_exclusion(self):
        name = "sites/MotherM-FatherF-ChildC_SNPs_sites.tsv"
        for row, column, value in ((1, "Paternity_Index", "1.25"), (6, "Status", "eligible"),
                                   (3, "Paternity_Index", "0"), (0, "Required_paternal_allele", "REF")):
            with self.subTest(column=column, row=row):
                self.cpin()
                self.mutate_table(name, row, column, value)
                with self.assertRaises(ValueError):
                    models.validate_model(self.run, workflow="cpin", marker="SNP")

    def test_cpin_rejects_curve_gap_and_duplicated_trio_selection(self):
        self.cpin()
        self.mutate_table("curves/MotherM-FatherF-ChildC_SNPs_all_compatible_sites_curve.tsv",
                          2, "Min_child_reads", "8")
        with self.assertRaisesRegex(ValueError, "curve has gaps"):
            models.validate_model(self.run, workflow="cpin", marker="SNP")
        self.cpin()
        self.mutate_table("Summary_Postnatal_CPI.txt", 1, "Analysis", "heterozygous_child_sites")
        with self.assertRaisesRegex(ValueError, "duplicated"):
            models.validate_model(self.run, workflow="cpin", marker="SNP")

    def test_settings_cannot_pass_just_because_both_candidate_records_agree(self):
        self.cpi()
        self.settings("cpi", err_const_snp=.01)
        with self.assertRaisesRegex(ValueError, "settings/err_const_snp"):
            models.validate_model(self.run, workflow="cpi", marker="SNP")

    def test_missing_or_truncated_pdf_is_not_scientific_success(self):
        self.cpin()
        self.write("output/All_CPIplots.pdf", b"%PDF-1.4\n")
        with self.assertRaisesRegex(ValueError, "incomplete analytical PDF"):
            models.validate_model(self.run, workflow="cpin", marker="SNP")

    def test_input_mutation_fails_before_validating_a_run(self):
        case = models.build_cases(ROOT / "tests/fixtures", self.root / "generated")[0]
        path = self.root / "generated" / case["id"] / "MotherM.txt"
        path.write_text("modified input\n")
        with self.assertRaisesRegex(ValueError, "modified an original"):
            case["validate"](self.root / "no-run")

    def test_numeric_comparison_rejects_nonfinite_and_boolean_values(self):
        for value in ("nan", "Inf", "-Inf", True, "not-a-number"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                models.number(value, 1, "oracle")


if __name__ == "__main__":
    unittest.main()
