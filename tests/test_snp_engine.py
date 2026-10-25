from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from nipat_scientific.errors import ValidationError
from nipat_scientific.snp import prepare_snp


class SnpEngineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nipat SNP à ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.panel = self.inputs / "SNP list.tsv"
        self.panel.write_text("pos\tref\talt\nchr1:100\tA\tC\n", encoding="utf-8")
        self.pileup = self.inputs / "pileup.txt"
        self.pileup.write_text("chr1\t100\tA\t1\t.\tI\tread1\n", encoding="utf-8")
        self.bam = self.inputs / "sample.bam"
        self.bam.write_bytes(b"BAM fixture, parsed by samtools only")
        self.reference = self.inputs / "genome.fa"
        self.reference.write_text(">chr1\n" + "A" * 200 + "\n", encoding="utf-8")
        Path(str(self.reference) + ".fai").write_text("chr1\t200\t6\t200\t201\n", encoding="utf-8")
        self.work = self.root / "results/work"
        self.output = self.root / "results/output"
        self.request = {
            "schema_version": 1, "workflow": "snp-call", "mode": "pileup",
            "panel": str(self.panel), "bam": None, "pileup": str(self.pileup),
            "reference": None, "work_dir": str(self.work), "out_dir": str(self.output),
        }

    def bam_request(self):
        return {**self.request, "mode": "bam", "bam": str(self.bam), "pileup": None,
                "reference": str(self.reference)}

    def assert_no_preparation(self):
        self.assertFalse(self.work.exists())
        self.assertFalse(self.output.exists())

    def test_existing_pileup_is_used_directly_without_creating_intermediates(self):
        original = {path: path.read_bytes() for path in self.inputs.iterdir()}
        prepared = prepare_snp(self.request)
        self.assertIsNone(prepared.preparation_command)
        self.assertIsNone(prepared.generated_pileup)
        self.assertEqual(prepared.native_arguments, [
            "--pileup", str(self.pileup), "--snplist", str(self.panel),
            "--out", str(self.output / "SNPcall_output.txt"),
        ])
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(original, {path: path.read_bytes() for path in self.inputs.iterdir()})

    def test_bam_preserves_three_base_windows_exact_flags_and_optional_index(self):
        original = {path: path.read_bytes() for path in self.inputs.iterdir()}
        prepared = prepare_snp(self.bam_request())
        self.assertEqual((self.work / "snp_regions.bed").read_text(), "chr1\t98\t101\n")
        self.assertEqual(prepared.preparation_command, [
            "samtools", "mpileup", "-f", str(self.reference), "-l", str(self.work / "snp_regions.bed"),
            "--output-QNAME", "--no-output-ins", "--no-output-del", "--no-output-ends",
            "-o", str(self.work / "pileup.txt"), str(self.bam),
        ])
        self.assertEqual(prepared.generated_pileup, self.work / "pileup.txt")
        self.assertFalse(prepared.generated_pileup.exists())
        self.assertEqual(prepared.native_arguments[1], str(prepared.generated_pileup))
        self.assertEqual(original, {path: path.read_bytes() for path in self.inputs.iterdir()})

    def test_position_one_remains_valid_only_for_existing_pileup(self):
        self.panel.write_text("pos\tref\talt\nchr1:1\tA\tC\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "posizione troppo bassa"):
            prepare_snp(self.bam_request())
        self.assert_no_preparation()
        self.assertIsNone(prepare_snp(self.request).preparation_command)

    def test_schema_and_mode_mismatches_fail_before_writes(self):
        cases = [
            None, [], {}, {**self.request, "schema_version": True},
            {**self.request, "schema_version": 2}, {**self.request, "workflow": "cpi"},
            {**self.request, "mode": []}, {**self.request, "mode": "invalid"},
            {**self.request, "unknown": "value"}, {**self.request, "panel": "relative.tsv"},
            {**self.request, "bam": str(self.bam)},
            {**self.request, "reference": str(self.reference)},
            {**self.request, "pileup": None},
            {**self.bam_request(), "pileup": str(self.pileup)},
            {**self.bam_request(), "reference": None},
            {**self.bam_request(), "bam": None},
        ]
        for request in cases:
            with self.subTest(request=request):
                with self.assertRaises(ValidationError):
                    prepare_snp(request)
                self.assert_no_preparation()

    def test_invalid_panel_missing_input_and_invalid_pileup_fail_before_writes(self):
        for contents in ("", "chr1\t100\tA\t1\t.\tI\n", "chr\tpos\tref\tcount\tbases\tqual\tqname\n"):
            self.pileup.write_text(contents, encoding="utf-8")
            with self.subTest(contents=contents):
                with self.assertRaises(ValidationError):
                    prepare_snp(self.request)
                self.assert_no_preparation()
        self.pileup.unlink()
        with self.assertRaisesRegex(ValidationError, "Pileup SNP non trovato"):
            prepare_snp(self.request)
        self.panel.write_text("invalid panel", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "colonne"):
            prepare_snp(self.bam_request())
        self.assert_no_preparation()

    def test_columns_after_qname_remain_supported(self):
        self.pileup.write_text("chr1\t100\tA\t1\t.\tI\tread1\textra\n", encoding="utf-8")
        self.assertIsNone(prepare_snp(self.request).preparation_command)

    def test_reference_index_is_required_and_bgzf_requires_gzi(self):
        Path(str(self.reference) + ".fai").unlink()
        with self.assertRaisesRegex(ValidationError, "Indice FASTA non trovato"):
            prepare_snp(self.bam_request())
        self.assert_no_preparation()
        compressed = self.inputs / "genome.fa.gz"
        compressed.write_bytes(b"BGZF content is read by samtools")
        Path(str(compressed) + ".fai").write_text("index", encoding="utf-8")
        request = {**self.bam_request(), "reference": str(compressed)}
        with self.assertRaisesRegex(ValidationError, "Indice FASTA BGZF non trovato"):
            prepare_snp(request)
        self.assert_no_preparation()
        Path(str(compressed) + ".gzi").write_bytes(b"gzi")
        prepared = prepare_snp(request)
        self.assertEqual(prepared.preparation_command[3], str(compressed))

    def test_overlap_between_work_output_or_inputs_is_rejected(self):
        for change in (
            {"out_dir": str(self.work)}, {"out_dir": str(self.work / "output")},
            {"out_dir": str(self.work.parent)}, {"work_dir": str(self.inputs)},
            {"out_dir": str(self.inputs)},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValidationError):
                    prepare_snp({**self.request, **change})
                self.assert_no_preparation()

    def test_existing_intermediates_and_output_are_not_overwritten(self):
        self.work.mkdir(parents=True)
        for name in ("snp_regions.bed", "pileup.txt"):
            with self.subTest(name=name):
                existing = self.work / name
                existing.write_text("prior work", encoding="utf-8")
                with self.assertRaisesRegex(ValidationError, "già presente"):
                    prepare_snp(self.bam_request())
                self.assertEqual(existing.read_text(), "prior work")
                existing.unlink()
        self.output.mkdir()
        previous = self.output / "SNPcall_output.txt"
        previous.write_text("prior output", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "deve essere vuota"):
            prepare_snp(self.request)
        self.assertEqual(previous.read_text(), "prior output")

    def test_existing_metadata_in_work_is_preserved(self):
        self.work.mkdir(parents=True)
        request_file = self.work / "engine-request.json"
        request_file.write_text("metadata", encoding="utf-8")
        prepare_snp(self.bam_request())
        self.assertEqual(request_file.read_text(), "metadata")


if __name__ == "__main__":
    unittest.main()
