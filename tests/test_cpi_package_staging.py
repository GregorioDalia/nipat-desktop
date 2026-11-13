"""Keep package assertions strict for allele-bearing and coordinate-only panels."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from nipat_scientific.panels import read_position_panel, write_position_panel


PROJECT = Path(__file__).resolve().parents[1]


class CpiPackageStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "nipat_cpi_package_staging", PROJECT / "scripts/verify_cpi_engine.py")
        cls.helper = importlib.util.module_from_spec(spec)
        with patch.object(sys, "path", [str(PROJECT / "scripts"), *sys.path]):
            spec.loader.exec_module(cls.helper)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nipat CPI staging gate ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "work/inputs").mkdir(parents=True)
        self.panel = self.root / "work/DNPpanel.txt"

    def check(self, *, include_alleles):
        self.helper.check_staging(self.root, {}, {"DNPpanel.txt": ((100, 200), include_alleles)})

    def test_allele_bearing_output_preserves_schema_coordinates_and_alleles(self):
        records = read_position_panel(PROJECT / "tests/fixtures/cpi/DNP_list.txt")[:2]
        write_position_panel(records, self.panel)
        self.check(include_alleles=True)
        original = self.panel.read_text(encoding="utf-8")
        for mutated in (
            # Losing alleles must fail even when coordinates remain correct.
            "n°DNP\tchr\tpos1\tpos2\nDNP001\tchr1\t100\t101\nDNP002\tchr1\t200\t201\n",
            original.replace("AA\tCC", "AA\tTT"),
            original.replace("100\t101", "100\t102"),
            original.replace("REF\tALT", "ALT\tREF"),
            original.replace("chr\tpos1", "chromosome\tpos1"),
        ):
            with self.subTest(panel=mutated):
                self.panel.write_text(mutated, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "expected coordinates or alleles"):
                    self.check(include_alleles=True)

    def test_coordinate_only_output_preserves_ids_without_inventing_alleles(self):
        source = self.root / "positions.tsv"
        source.write_text("chr\tpos1\tpos2\nchr1\t100\t101\nchr1\t200\t201\n", encoding="utf-8")
        write_position_panel(read_position_panel(source), self.panel)
        self.check(include_alleles=False)
        original = self.panel.read_text(encoding="utf-8")
        for mutated in (
            original.replace("DNP002", "DNP003"),
            original.replace("200\t201", "200\t202"),
            "chr\tpos1\tpos2\tREF\tALT\nchr1\t100\t101\tAA\tCC\nchr1\t200\t201\tGG\tTT\n",
        ):
            with self.subTest(panel=mutated):
                self.panel.write_text(mutated, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "expected coordinates or alleles"):
                    self.check(include_alleles=False)


if __name__ == "__main__":
    unittest.main()
