from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from nipat_scientific.errors import ValidationError
from nipat_scientific.files import (
    require_contamination_input, require_dnp_input, require_population_frequencies,
    require_snp_pileup,
)
from nipat_scientific.panels import read_snp_list
from nipat_scientific.snp import prepare_snp


class ScientificPreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.table = self.root / "table.tsv"

    def counts(self, row="chr1\t10\t11\t95\t5\t0", extra_header="", extra_row=""):
        self.table.write_text("chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other" + extra_header +
                              "\n" + row + extra_row + "\n", encoding="utf-8")
        return self.table

    def test_counts_reject_invalid_values_without_rewriting(self):
        for value in ("-1", "0.5", "NA", "NaN", "Inf", "-Inf", "1e100000000", "abc"):
            with self.subTest(value=value):
                path = self.counts(f"chr1\t10\t11\t95\t{value}\t0")
                before = path.read_bytes()
                with self.assertRaisesRegex(ValidationError, "riga 2.*N_ALT"):
                    require_contamination_input(path)
                self.assertEqual(path.read_bytes(), before)

    def test_counts_zero_and_empty_rows_have_valid_no_information_semantics(self):
        require_contamination_input(self.counts("chr1\t10\t11\t0\t0\t0"))
        self.table.write_text("chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\n", encoding="utf-8")
        require_contamination_input(self.table)

    def test_native_dnp_uncovered_locus_allows_na_total_only_with_zero_primary_counts(self):
        for function in (require_contamination_input, require_dnp_input):
            with self.subTest(function=function.__name__):
                self.table.write_text("chr\tpos1\tpos2\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n"
                                      "chr1\t10\t11\tAA\tGG\t0\t0\t0\tNA\n", encoding="utf-8")
                original = self.table.read_bytes()
                self.assertEqual(function(self.table), [])
                self.assertEqual(self.table.read_bytes(), original)
                for suffix in ("1\t0\t0\tNA", "NA\t0\t0\tNA", "0\t0\t0\tNaN", "0\t0\t0\t"):
                    self.table.write_text("chr\tpos1\tpos2\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n"
                                          "chr1\t10\t11\tAA\tGG\t" + suffix + "\n", encoding="utf-8")
                    with self.assertRaises(ValidationError):
                        function(self.table)

    def test_locus_duplicates_and_reversed_coordinates_are_rejected(self):
        for row in ("chr1\t10\t10\t95\t5\t0", "chr1\t10\t9\t95\t5\t0",
                    "chr1\t0\t1\t95\t5\t0", "chr1\t10\t11\t95\t5\t0\nchr1\t10\t11\t95\t5\t0"):
            with self.subTest(row=row):
                with self.assertRaises(ValidationError):
                    require_contamination_input(self.counts(row))

    def test_supplied_ratio_and_total_mismatches_are_warnings_not_repairs(self):
        path = self.counts(extra_header="\tratio_REF_ALT\ttotal_count", extra_row="\t0.9\t101")
        original = path.read_bytes()
        warnings = require_contamination_input(path)
        self.assertEqual({w["code"] for w in warnings}, {"input.ratio_mismatch", "input.total_count_mismatch"})
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(all(w["row"] == 2 for w in warnings))

    def test_missing_supplied_ratio_remains_explicit(self):
        warnings = require_contamination_input(self.counts(extra_header="\tratio_REF_ALT", extra_row="\tNA"))
        self.assertEqual([w["code"] for w in warnings], ["input.missing_ratio"])
        self.assertEqual(require_contamination_input(self.counts("chr1\t10\t11\t0\t0\t0",
                         extra_header="\tratio_REF_ALT", extra_row="\tNA")), [])

    def test_whitespace_and_quoted_cpi_tables_remain_supported(self):
        self.table.write_text('"chr" "pos1" "pos2" "REF" "ALT" "N_REF" "N_ALT" "N_Other" "total_count"\n'
                              '"chr1" 10 11 "AA" "GG" 98 2 0 100\n', encoding="utf-8")
        self.assertEqual(require_dnp_input(self.table), [])

    def test_frequency_range_and_duplicate_keys_are_rejected(self):
        header = "chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\n"
        for row in ("chr1\t10\t11\t-0.1\t1.1\n", "chr1\t10\t11\t0.5\tInf\n",
                    "chr1\t10\t11\t0.5\tNA\n", "chr1\t10\t11\t0.5\t0.5\n" * 2, ""):
            with self.subTest(row=row):
                self.table.write_text(header + row, encoding="utf-8")
                with self.assertRaises(ValidationError):
                    require_population_frequencies(self.table)

    def test_frequency_decimal_comma_preserved_and_endpoints_are_warned(self):
        self.table.write_text("chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\n"
                              "chr1\t10\t11\t0,5\t0,5\n"
                              "chr1\t20\t21\t0\t0,5\n", encoding="utf-8")
        original = self.table.read_bytes()
        warnings = require_population_frequencies(self.table)
        self.assertEqual({w["code"] for w in warnings}, {"input.zero_population_frequency", "input.frequency_sum"})
        self.assertEqual(self.table.read_bytes(), original)

    def test_invalid_text_header_and_rows_raise_shared_validation_error(self):
        cases = [b"\xff\xfeinvalid", b"chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\tN_REF\n",
                 b"chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\nchr1\t10\t11\t1\n"]
        for content in cases:
            with self.subTest(content=content):
                self.table.write_bytes(content)
                with self.assertRaises(ValidationError):
                    require_contamination_input(self.table)

    def test_pileup_checks_later_rows_in_stream(self):
        self.table.write_text("chr1\t10\tA\t1\t.\tI\tread1\n"
                              "chr1\t11\tA\t-1\t.\tI\tread1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "riga 2"):
            require_snp_pileup(self.table)

    def test_snp_normalization_preserves_original_and_records_exact_copy(self):
        self.table.write_text("pos\tref\talt\nchr1:10\ta\tg\n", encoding="utf-8")
        original = self.table.read_bytes()
        pileup = self.root / "pileup.txt"
        pileup.write_text("chr1\t10\tA\t1\tG\tI\tread1\n", encoding="utf-8")
        request = {"schema_version": 1, "workflow": "snp-call", "mode": "pileup",
                   "panel": str(self.table), "pileup": str(pileup), "bam": None, "reference": None,
                   "work_dir": str(self.root / "run/work"), "out_dir": str(self.root / "run/output")}
        prepared = prepare_snp(request)
        normalized = Path(prepared.native_arguments[3])
        self.assertEqual(normalized.read_text(), "pos\tref\talt\nchr1:10\tA\tG\n")
        self.assertEqual(self.table.read_bytes(), original)
        report = json.loads((self.root / "run/work/input-validation.json").read_text())
        self.assertEqual(report["warnings"], [])
        self.assertNotEqual(report["normalizations"][0]["source_sha256"],
                            report["normalizations"][0]["prepared_sha256"])

    def test_snp_invalid_or_duplicate_alleles_fail(self):
        for row in ("chr1:10\tA\tA", "chr1:10\tAA\tG", "chr1:10\tA\tN", "chr1:10\tA\t",
                    "chr1:10\tA\tG\nchr1:10\tA\tT"):
            with self.subTest(row=row):
                self.table.write_text("pos\tref\talt\n" + row + "\n", encoding="utf-8")
                with self.assertRaises(ValidationError):
                    read_snp_list(self.table)


if __name__ == "__main__":
    unittest.main()
