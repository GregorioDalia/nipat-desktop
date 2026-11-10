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

    def test_dnp_panel_requires_the_preceding_base_but_accepts_position_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "DNP_list.txt"
            for position in (-1, 0, 1):
                with self.subTest(position=position):
                    source.write_text(f"chr1\t{position}\t{position + 1}\tAC\tGT\n", encoding="utf-8")
                    with self.assertRaisesRegex(ValidationError, "pos1 deve essere almeno 2"):
                        read_dnp_list(source)
            source.write_text("chr1\t2\t3\tAC\tGT\n", encoding="utf-8")
            record = read_dnp_list(source)[0]
            self.assertEqual((record.pos1, record.pos2), (2, 3))

    def test_snp_panel_generates_three_base_windows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source = tmp_path / "SNPlist.txt"
            source.write_text("pos\tref\talt\nchr1:100\tA\tG\n", encoding="utf-8")
            positions = read_snp_positions(source)
            destination = tmp_path / "regions.bed"
            write_snp_bed(positions, destination)
            self.assertEqual(destination.read_text(encoding="utf-8"), "chr1\t98\t101\n")

    def test_snp2_native_panel_coordinate_limits_and_alleles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "SNPs.tsv"
            source.write_text("chr\tpos\tref\talt\nchr1\t2\ta\tg\nchrX\t2147483646\tC\tT\n")
            self.assertEqual(read_snp_positions(source), [("chr1", 2), ("chrX", 2147483646)])
            for row in ("chr1\t1\tA\tG", "chr1\t2147483647\tA\tG",
                        "chr:1\t10\tA\tG", "chr 1\t10\tA\tG", "chr1\t10\tA\tA",
                        "chr1\t10\tAA\tG", "chr1\t10\tA\tN"):
                source.write_text("chr\tpos\tref\talt\n" + row + "\n")
                for for_bed in (False, True):
                    with self.subTest(row=row, for_bed=for_bed), self.assertRaises(ValidationError):
                        read_snp_positions(source, for_bed=for_bed)

    def test_snp2_native_panel_rejects_duplicate_coordinates_and_extra_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "SNPs.tsv"
            for text in ("chr\tpos\tref\talt\nchr1\t10\tA\tG\nchr1\t10\tA\tT\n",
                         "chr\tpos\tref\talt\textra\nchr1\t10\tA\tG\tignored\n"):
                source.write_text(text)
                with self.assertRaises(ValidationError):
                    read_snp_positions(source)


if __name__ == "__main__":
    unittest.main()
