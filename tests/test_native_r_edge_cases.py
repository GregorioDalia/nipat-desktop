"""Native R edge regressions; stdlib-only so the packaged image can run them.

Set NIPAT_NATIVE_TEST_PAYLOAD_ROOT=/opt/nipat to exercise installed sources and
helpers. Without this override the current checkout is tested. Fixtures always
come from this checkout, never from a mounted replacement of the payload.
"""

import csv
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from native_r_helpers import NATIVE_R_AVAILABLE, NATIVE_R_REASON


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = Path(os.environ.get("NIPAT_NATIVE_TEST_PAYLOAD_ROOT", ROOT))
HELPERS = PAYLOAD / ("lib" if "NIPAT_NATIVE_TEST_PAYLOAD_ROOT" in os.environ else "src") / "nipat_scientific"


def table(path, delimiter="\t"):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter=delimiter))


@unittest.skipUnless(NATIVE_R_AVAILABLE, NATIVE_R_REASON)
class NativeREdgeCases(unittest.TestCase):
    def run_native(self, root, workflow, inputs, native_options=(), settings=None):
        output = root / "output"
        source = {"cpin": "CPI_postnatal/Postnatal_CPI.R",
                  "cpi": "CPI_from_cffDNA/cfDNA_CPI_estimator.R"}[workflow]
        arguments = ["Rscript", str(PAYLOAD / "scientific/vendor/NEWPAT" / source),
                     "--pileup_dir", str(inputs), "--out_dir", str(output),
                     "--mother_prefix", "Mother", "--father_prefix", "Father",
                     "--popfreq", str(inputs / "population.txt")]
        arguments += (["--trios", "M1:F1:C1", "--child_prefix", "Child"] if workflow == "cpin"
                      else ["--pairs", "M1:F1"])
        arguments.extend(native_options)
        env = dict(os.environ, NIPAT_EXECUTION_MODE="serial",
                   NIPAT_PARALLEL_HELPER=str(HELPERS / "parallel.R"),
                   NIPAT_SETTINGS_HELPER=str(HELPERS / "settings.R"),
                   NIPAT_SETTINGS_REGISTRY=str(HELPERS / "settings_data.json"),
                   NIPAT_PLOTS_HELPER=str(HELPERS / "plots.R"))
        env.pop("NIPAT_SCIENTIFIC_SETTINGS", None)
        if settings is not None:
            settings_path = root / "scientific-settings-request.json"
            settings_path.write_text(json.dumps({"schema_version": 1, "workflow": workflow,
                                                 "parameters": settings}))
            env["NIPAT_SCIENTIFIC_SETTINGS"] = str(settings_path)
        process = subprocess.run(arguments, cwd=root, env=env, capture_output=True, text=True, timeout=90)
        return process, output

    def test_cpin_absent_and_uncovered_samples(self):
        for marker in ("SNP", "DNP"):
            for case in ("empty_child", "empty_trio", "uncovered_child"):
                with self.subTest(marker=marker, case=case), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    inputs = root / "inputs"
                    shutil.copytree(ROOT / "tests/fixtures/cpin" / marker, inputs)
                    samples = ("MotherM1", "FatherF1", "ChildC1") if case == "empty_trio" else ("ChildC1",)
                    for sample in samples:
                        path = inputs / f"{sample}.txt"
                        rows = table(path)
                        with path.open("w", newline="") as stream:
                            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
                            writer.writeheader()
                            if case == "uncovered_child":
                                for row in rows:
                                    row.update(N_REF="0", N_ALT="0", N_Other="0", total_count="NA")
                                writer.writerows(rows)
                    process, output = self.run_native(root, "cpin", inputs)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    summaries = table(output / "Summary_Postnatal_CPI.txt")
                    self.assertEqual(len(summaries), 2)
                    for row in summaries:
                        self.assertEqual((row["N_sites"], row["CPI"], row["Log10_CPI"]), ("0", "NA", "NA"))
                    sites = table(next((output / "sites").glob("*.tsv")))
                    expected = "quality_filter" if case == "uncovered_child" else "missing_call"
                    self.assertEqual({row["Status"] for row in sites}, {expected} if case != "empty_trio" else set())
                    self.assertTrue(all(not table(path) for path in (output / "curves").iterdir()))

    def test_cpi_empty_and_uncovered_samples_preserve_invalid_total_errors(self):
        for marker in ("SNP", "DNP"):
            for case in ("empty", "uncovered", "malformed"):
                with self.subTest(marker=marker, case=case), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    inputs = root / "inputs"
                    shutil.copytree(ROOT / "tests/fixtures/cpin" / marker, inputs)
                    for sample in ("MotherM1", "FatherF1"):
                        path = inputs / f"{sample}.txt"
                        rows = table(path)
                        with path.open("w", newline="") as stream:
                            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
                            writer.writeheader()
                            if case != "empty":
                                for row in rows:
                                    row.update(N_REF="0", N_ALT="0", N_Other="0",
                                               total_count="NA" if case == "uncovered" else "bad")
                                writer.writerows(rows)
                    process, output = self.run_native(root, "cpi", inputs)
                    if case == "malformed":
                        self.assertNotEqual(process.returncode, 0)
                        self.assertIn("invalid total_count", process.stderr)
                        self.assertFalse((output / "Summary_FetalFraction_CPI.csv").exists())
                    else:
                        self.assertEqual(process.returncode, 0, process.stderr)
                        summaries = table(output / "Summary_FetalFraction_CPI.csv", ",")
                        self.assertEqual(len(summaries), 1)
                        self.assertEqual(summaries[0]["N_sites_mother"], "0")
                        self.assertEqual(summaries[0]["N_sites_father"], "0")
                        self.assertEqual(summaries[0]["Mean_logCPI"], "NA")

    def test_cpi_log_stays_finite_outside_the_raw_product_range(self):
        for loci, father, expected in ((400, (0, 100), 400.0),
                                       (200, (100, 0), 200 * math.log10(0.002))):
            with self.subTest(loci=loci), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                inputs = root / "inputs"
                inputs.mkdir()
                header = "chr\tpos\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n"
                (inputs / "MotherM1.txt").write_text(header + "".join(
                    f"01\t{i}\tA\tG\t95\t5\t0\t100\n" for i in range(2, loci + 2)))
                (inputs / "FatherF1.txt").write_text(header + "".join(
                    f"01\t{i}\tA\tG\t{father[0]}\t{father[1]}\t0\t100\n" for i in range(2, loci + 2)))
                alt = 0.1 if loci == 400 else 0.5
                (inputs / "population.txt").write_text("chr\tpos\tRef_f.pop\tAlt_f.pop\n" + "".join(
                    f"01\t{i}\t{1-alt}\t{alt}\n" for i in range(2, loci + 2)))
                process, output = self.run_native(root, "cpi", inputs)
                self.assertEqual(process.returncode, 0, process.stderr)
                rows = table(next((output / "curves").glob("*.tsv")))
                self.assertTrue(rows)
                for row in rows:
                    self.assertAlmostEqual(float(row["log_CPI"]), expected, places=8)
                    self.assertEqual(float(row["CPI"]), math.inf if loci == 400 else 0.0)
                summary = table(output / "Summary_FetalFraction_CPI.csv", ",")[0]
                self.assertAlmostEqual(float(summary["CPI_medianFF"]), expected, places=3)

    def test_downstream_joins_preserve_numeric_looking_contigs(self):
        for workflow in ("cpi", "cpin"):
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                inputs = root / "inputs"
                inputs.mkdir()
                header = "chr\tpos\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n"
                (inputs / "MotherM1.txt").write_text(header + "01\t20\tA\tG\t95\t5\t0\t100\n")
                (inputs / "FatherF1.txt").write_text(header + "1\t20\tA\tG\t0\t100\t0\t100\n")
                (inputs / "ChildC1.txt").write_text(header + "01\t20\tA\tG\t50\t50\t0\t100\n")
                (inputs / "population.txt").write_text("chr\tpos\tRef_f.pop\tAlt_f.pop\n01\t20\t0.8\t0.2\n")
                process, output = self.run_native(root, workflow, inputs)
                self.assertEqual(process.returncode, 0, process.stderr)
                if workflow == "cpi":
                    row = table(output / "Summary_FetalFraction_CPI.csv", ",")[0]
                    self.assertEqual((row["N_sites_father"], row["CPI_medianFF"]), ("0", "NA"))
                else:
                    rows = table(output / "Summary_Postnatal_CPI.txt")
                    self.assertTrue(all(row["N_sites"] == "0" and row["Log10_CPI"] == "NA" for row in rows))

    def test_cpin_tiny_positive_frequencies_preserve_finite_log_cpi(self):
        for marker in ("SNP", "DNP"):
            for frequency in ("1e-310", "0"):
                with self.subTest(marker=marker, frequency=frequency), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    inputs = root / "inputs"
                    shutil.copytree(ROOT / "tests/fixtures/cpin" / marker, inputs)
                    population = inputs / "population.txt"
                    rows = table(population)
                    for row in rows:
                        row.update({"Ref_f.pop": frequency, "Alt_f.pop": frequency})
                    with population.open("w", newline="") as stream:
                        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
                        writer.writeheader()
                        writer.writerows(rows)
                    process, output = self.run_native(root, "cpin", inputs)
                    if frequency == "0":
                        self.assertNotEqual(process.returncode, 0)
                        self.assertIn("finite and in (0, 1]", process.stderr)
                        self.assertFalse((output / "Summary_Postnatal_CPI.txt").exists())
                    else:
                        self.assertEqual(process.returncode, 0, process.stderr)
                        summaries = table(output / "Summary_Postnatal_CPI.txt")
                        self.assertEqual([row["N_sites"] for row in summaries], ["2", "3"])
                        for row in summaries:
                            expected = math.log10(0.5) + math.log10(float(row["Error_constant"]))
                            expected -= int(row["N_sites"]) * math.log10(float(frequency))
                            self.assertAlmostEqual(float(row["Log10_CPI"]), expected, places=10)
                        for path in (output / "curves").iterdir():
                            self.assertTrue(all(math.isfinite(float(row["Log10_CPI"])) for row in table(path)))


if __name__ == "__main__":
    unittest.main()
