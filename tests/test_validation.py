import tempfile
import unittest
from pathlib import Path

from nipat.errors import ValidationError
from nipat.validation.files import require_contamination_input
from nipat.validation.integrity import verify_sha256_manifest


class ValidationTests(unittest.TestCase):
    def test_contamination_input_accepts_dnpcall_without_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "dnp.txt"
            source.write_text(
                "chr\tpos1\tpos2\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n",
                encoding="utf-8",
            )
            original = source.read_bytes()
            require_contamination_input(source)
            self.assertEqual(source.read_bytes(), original)

    def test_contamination_input_accepts_minimal_count_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "minimal.txt"
            source.write_text("chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\n", encoding="utf-8")
            require_contamination_input(source)

    def test_contamination_input_rejects_missing_required_columns(self) -> None:
        columns = ["chr", "pos1", "pos2", "N_REF", "N_ALT", "N_Other"]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing.txt"
            for missing in columns:
                with self.subTest(missing=missing):
                    source.write_text(
                        "\t".join(column for column in columns if column != missing) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValidationError, missing):
                        require_contamination_input(source)

    def test_contamination_input_accepts_current_expected_interface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "dnp.txt"
            source.write_text(
                "chr\tpos1\tpos2\tREF\tALT\tN_REF\tN_ALT\tN_Other\t"
                "ratio_REF_ALT\ttotal_count\n",
                encoding="utf-8",
            )
            require_contamination_input(source)

    def test_scientific_manifest_detects_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "script.R"
            script.write_bytes(b"original\n")
            manifest = root / "SHA256SUMS"
            manifest.write_text(
                "25718360e05d3c2d0963d1381e9dd4dae5fca789244ee4b9f861adcc0cc96218  script.R\n",
                encoding="utf-8",
            )
            verify_sha256_manifest(manifest)
            script.write_bytes(b"changed\n")
            with self.assertRaisesRegex(ValidationError, "modificata"):
                verify_sha256_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
