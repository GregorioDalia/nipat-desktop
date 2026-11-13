"""Regression coverage for marker-aware adapters and scientific controls."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from nipat_scientific.contamination import prepare_contamination
from nipat_scientific.cpi import prepare_cpi
from nipat_scientific.errors import ValidationError


class MarkerAwareAdaptersTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="nipat-marker-controls-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def fixture(self, marker):
        directory = self.root / marker
        directory.mkdir()
        coordinates = "chr\tpos" if marker == "SNP" else "chr\tpos1\tpos2"
        site = "chr1\t100" if marker == "SNP" else "chr1\t100\t101"
        alleles = "A\tC" if marker == "SNP" else "AA\tCC"
        samples = []
        for name, counts in (("MotherM.txt", "98\t2\t0\t100"),
                             ("FatherF.txt", "0\t100\t0\t100")):
            path = directory / name
            path.write_text(f"{coordinates}\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n"
                            f"{site}\t{alleles}\t{counts}\n", encoding="utf-8")
            samples.append({"name": name, "path": str(path)})
        population = directory / "population.tsv"
        population.write_text(f"{coordinates}\tRef_f.pop\tAlt_f.pop\n{site}\t0.8\t0.2\n")
        panel = directory / "panel.tsv"
        panel.write_text(f"{coordinates}\tREF\tALT\n{site}\t{alleles}\n")
        return {
            "schema_version": 1, "workflow": "cpi", "samples": samples,
            "pairs": "M:F", "mother_prefix": "Mother", "father_prefix": "Father",
            "popfreq": str(population), "cutoff_mode": "panel",
            "cutoffs": [{"label": "", "path": str(panel)}],
            "work_dir": str(directory / "run/work"), "out_dir": str(directory / "run/output"),
        }, panel

    def test_marker_specific_default_error_constants_and_preserved_panel_alleles(self):
        for marker, expected in (("SNP", 0.001), ("DNP", 0.0000892303778101497)):
            with self.subTest(marker=marker):
                request, _ = self.fixture(marker)
                argv = prepare_cpi(request)
                self.assertEqual(float(argv[argv.index("--err_const") + 1]), expected)
                self.assertEqual(argv[argv.index("--min_fetal_reads") + 1], "2")
                normalized = Path(request["work_dir"]) / f"{marker}panel.txt"
                self.assertIn("\tREF\tALT\n", normalized.read_text())

    def test_configured_cpi_constants_and_minimum_are_effective(self):
        request, _ = self.fixture("SNP")
        request["scientific_settings"] = {"err_const_snp": 0.02, "min_fetal_reads": 5}
        argv = prepare_cpi(request)
        self.assertEqual(argv[argv.index("--err_const") + 1], "0.02")
        self.assertEqual(argv[argv.index("--min_fetal_reads") + 1], "5")

    def test_invalid_cpi_settings_do_not_create_run(self):
        request, _ = self.fixture("SNP")
        for settings in ({"err_const_snp": 0}, {"min_fetal_reads": 0},
                         {"min_fetal_reads": 1.5}, {"unsupported": 42}):
            with self.subTest(settings=settings), self.assertRaises(ValidationError):
                prepare_cpi({**request, "scientific_settings": settings})
        self.assertFalse(Path(request["work_dir"]).exists())

    def test_mixed_marker_cpi_rejects_before_staging(self):
        request, _ = self.fixture("SNP")
        other, _ = self.fixture("DNP")
        request["samples"][1]["path"] = other["samples"][1]["path"]
        with self.assertRaises(ValidationError):
            prepare_cpi(request)
        self.assertFalse(Path(request["work_dir"]).exists())

    def test_contamination_zero_policy_reaches_native_cli(self):
        for marker, include in (("SNP", False), ("DNP", True)):
            source, panel = self.fixture(marker)
            request = {key: source[key] for key in ("schema_version", "samples", "work_dir", "out_dir")}
            request.update(workflow="contamination", panel=str(panel),
                           scientific_settings={"include_zero": include})
            argv = prepare_contamination(request)
            self.assertEqual(argv[-1], "--include_zero" if include else "--exclude_zero")
            self.assertEqual(Path(argv[0]).name, f"{marker}panel.txt")

    def test_contamination_rejects_mixed_types_and_malformed_sample_before_writes(self):
        source, panel = self.fixture("SNP")
        other, _ = self.fixture("DNP")
        request = {key: source[key] for key in ("schema_version", "samples", "work_dir", "out_dir")}
        request.update(workflow="contamination", panel=str(panel))
        malformed = deepcopy(request)
        malformed["samples"][0] = None
        mixed = deepcopy(request)
        mixed["samples"][1]["path"] = other["samples"][1]["path"]
        for case in (malformed, mixed):
            with self.assertRaises(ValidationError):
                prepare_contamination(case)
        self.assertFalse(Path(request["work_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
