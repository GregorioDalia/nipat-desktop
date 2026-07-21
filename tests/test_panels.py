import tempfile
import unittest
from pathlib import Path

from nipat.adapters.panels import (
    read_dnp_list,
    read_snp_positions,
    write_position_panel,
    write_snp_bed,
)
from nipat.errors import ValidationError


class PanelTests(unittest.TestCase):
    def test_dnp_panel_is_read_and_adapted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source = tmp_path / "DNP_list.txt"
            source.write_text(
                "chr1\t10\t11\tAC\tGT\nchr2\t20\t21\tAA\tCC\n", encoding="utf-8"
            )
            records = read_dnp_list(source)
            destination = tmp_path / "DNPpanel.txt"
            write_position_panel(records, destination)
            self.assertEqual(
                destination.read_text(encoding="utf-8").splitlines(),
                [
                    "n°DNP\tchr\tpos1\tpos2",
                    "DNP001\tchr1\t10\t11",
                    "DNP002\tchr2\t20\t21",
                ],
            )

    def test_dnp_panel_rejects_non_adjacent_positions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "DNP_list.txt"
            source.write_text("chr1\t10\t12\tAC\tGT\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "pos2"):
                read_dnp_list(source)

    def test_snp_panel_generates_three_base_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source = tmp_path / "SNPlist.txt"
            source.write_text("pos\tref\talt\nchr1:100\tA\tG\n", encoding="utf-8")
            positions = read_snp_positions(source)
            destination = tmp_path / "regions.bed"
            write_snp_bed(positions, destination)
            self.assertEqual(destination.read_text(encoding="utf-8"), "chr1\t98\t101\n")


if __name__ == "__main__":
    unittest.main()
