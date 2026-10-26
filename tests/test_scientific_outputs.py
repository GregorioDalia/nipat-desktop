from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from nipat_scientific.errors import PlanExecutionError
from nipat_scientific.outputs import validate_standalone_outputs


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

    def snp(self, ratio, ref=1):
        path = self.output / "SNPcall_output.txt"
        path.write_text("chr\tpos\tReference\tAlternative\tN_Reference\tN_Alternative\tN_Altro\ttotal_count\tratio\n"
                        f"chr1\t10\tA\tG\t{ref}\t0\t0\t{ref}\t{ratio}\n", encoding="utf-8")
        return path

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

    def test_contamination_summary_and_site_rows_must_agree(self):
        request = {"workflow": "contamination", "samples": [{"name": "sample.txt"}],
                   "work_dir": str(self.root / "work"), "out_dir": str(self.output)}
        summary = self.output / "contamination_summary.txt"
        summary.write_text("individuo\tinformative_DNPs\tmean_contamination\tsd_contamination\n"
                           "sample\t1\t0.01\tNA\n", encoding="utf-8")
        table = self.output / "contamination_sample.txt"
        table.write_text("chr\tpos1\tpos2\tcontamination\nchr1\t10\t11\t0.01\n", encoding="utf-8")
        self.assertEqual(validate_standalone_outputs(request)["quality_warnings"], [])
        table.write_text("chr\tpos1\tpos2\tcontamination\n", encoding="utf-8")
        with self.assertRaisesRegex(PlanExecutionError, "site count"):
            validate_standalone_outputs(request)
        summary.write_text("individuo\tinformative_DNPs\tmean_contamination\tsd_contamination\n"
                           "sample\t1\t0.01\n", encoding="utf-8")
        with self.assertRaises(PlanExecutionError):
            validate_standalone_outputs(request)

    def test_dnp_preserves_uncovered_panel_locus_but_rejects_truncation(self):
        panel = self.root / "DNP_list.txt"
        panel.write_text("chr1\t10\t11\tAA\tGG\nchr1\t20\t21\tAA\tGG\n", encoding="utf-8")
        request = {"workflow": "dnp-call", "panel": str(panel),
                   "samples": [{"sample_id": "sample_0001"}],
                   "work_dir": str(self.root / "work"), "out_dir": str(self.output)}
        directory = self.output / "individual_outputs"
        directory.mkdir()
        path = directory / "full_output_sample_0001.txt"
        header = "chr\tpos1\tpos2\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n"
        covered = "chr1\t10\t11\tAA\tGG\t5\t0\t0\t5\n"
        uncovered = "chr1\t20\t21\tAA\tGG\t0\t0\t0\tNA\n"
        path.write_text(header + covered + uncovered, encoding="utf-8")
        original = path.read_bytes()
        self.assertEqual(validate_standalone_outputs(request)["quality_warnings"], [])
        self.assertEqual(path.read_bytes(), original)
        for contents in (header, header + covered):
            path.write_text(contents, encoding="utf-8")
            with self.assertRaisesRegex(PlanExecutionError, "loci"):
                validate_standalone_outputs(request)


if __name__ == "__main__":
    unittest.main()
