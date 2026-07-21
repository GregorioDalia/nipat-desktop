import tempfile
import unittest
from pathlib import Path

from nipat.errors import ValidationError
from nipat.validation.files import require_contamination_input
from nipat.validation.integrity import verify_sha256_manifest


class ValidationTests(unittest.TestCase):
    def test_contamination_input_requires_confirmed_ratio_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "dnp.txt"
            source.write_text(
                "chr\tpos1\tpos2\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValidationError, "ratio_REF_ALT"):
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
