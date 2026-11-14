"""Synthetic caller regressions exercised against the installed R payload."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from nipat_scientific.settings import describe_settings, normalize_settings

from native_r_helpers import NATIVE_R_AVAILABLE, NATIVE_R_REASON
from test_native_r_edge_cases import HELPERS, PAYLOAD, table


@unittest.skipUnless(NATIVE_R_AVAILABLE, NATIVE_R_REASON)
class NativeCallerInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nipat-audit-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = dict(os.environ, NIPAT_EXECUTION_MODE="serial",
                        NIPAT_PARALLEL_HELPER=str(HELPERS / "parallel.R"),
                        NIPAT_SETTINGS_HELPER=str(HELPERS / "settings.R"),
                        NIPAT_SETTINGS_REGISTRY=str(HELPERS / "settings_data.json"),
                        NIPAT_PLOTS_HELPER=str(HELPERS / "plots.R"))
        self.env.pop("NIPAT_SCIENTIFIC_SETTINGS", None)

    def run_r(self, script, arguments, *, root=None):
        return subprocess.run(
            ["Rscript", str(PAYLOAD / "scientific/vendor" / script), *arguments],
            cwd=root or self.root, env=self.env, capture_output=True, text=True, timeout=90,
        )

    def test_snp_preserves_names_and_rejects_wrong_ref_or_repeated_names(self):
        snp = self.root / "panel.tsv"
        pileup = self.root / "pileup.tsv"
        output = self.root / "snp.tsv"
        snp.write_text("chr\tpos\tref\talt\n01\t50\tA\tG\n1\t50\tA\tG\n")
        args = ["--pileup", str(pileup), "--snplist", str(snp), "--out", str(output)]
        for label, reference, obs, qnames, error in (
            ("distinct", "A", ".", ("001", "01", "1"), None),
            ("reference", "G", ".", ("read", "read", "read"), "panel REF differs"),
            ("duplicate", "A", "..", ("read,read",) * 3, "repeats a QNAME"),
        ):
            with self.subTest(label=label):
                pileup.write_text("".join(
                    f"01\t{position}\t{reference}\t{len(obs)}\t{obs}\t{'I' * len(obs)}\t{name}\n"
                    for position, name in zip(range(49, 52), qnames, strict=True)))
                result = self.run_r("NEWPAT/SNPcall/SNPcall.R", args)
                if error:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(error, result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    rows = {row["chr"]: row for row in table(output)}
                    self.assertEqual(set(rows), {"01", "1"})
                    self.assertTrue(all(row["N_REF"] == "0" and row["GT"] == "NA"
                                        for row in rows.values()))

    def test_dnp_rejects_wrong_reference_and_represents_empty_sample(self):
        self.assertIsNotNone(shutil.which("samtools"), "Native DNP checks require samtools")
        self.env.update(PYTHONPATH=str(HELPERS.parent),
                        NIPAT_DNP_KEEP_PILEUP="1",
                        NIPAT_DNP_BLOCKS_HELPER=str(HELPERS / "dnp_blocks.R"),
                        NIPAT_DNP_PILEUP_HELPER=str(HELPERS / "dnp_pileup.py"))
        settings = self.root / "dnp-settings.json"
        settings.write_text(json.dumps({"schema_version": 1, "workflow": "dnp-call",
                                        "parameters": normalize_settings("dnp-call", {"baq": False}),
                                        "constants": describe_settings("dnp-call")["constants"]}))
        self.env["NIPAT_SCIENTIFIC_SETTINGS"] = str(settings)
        reference = self.root / "reference.fa"
        reference.write_text(">01\n" + "A" * 100 + "\n")
        subprocess.run(["samtools", "faidx", str(reference)], check=True, capture_output=True)
        for case, allele, record in (
            ("covered", "AA", "read\t0\t01\t47\t60\t10M\t*\t0\t0\tAAAAAAAAAA\tIIIIIIIIII\n"),
            ("wrong-ref", "GG", "read\t0\t01\t47\t60\t10M\t*\t0\t0\tAAAAAAAAAA\tIIIIIIIIII\n"),
            ("uncovered", "AA", ""),
            ("distinct-numeric-reads", "AA", "".join(
                f"{'0' * (52 - position)}1\t0\t01\t{position}\t60\t1M\t*\t0\t0\tA\tI\n"
                for position in range(49, 53))),
        ):
            with self.subTest(case=case):
                directory = self.root / case
                directory.mkdir()
                (directory / "work").mkdir()
                (directory / "output").mkdir()
                sam = directory / "sample.sam"
                bam = directory / "sample_0001.bam"
                sam.write_text("@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:01\tLN:100\n" + record)
                subprocess.run(["samtools", "view", "-b", "-o", str(bam), str(sam)],
                               check=True, capture_output=True)
                (directory / "bamlist.txt").write_text(str(bam) + "\n")
                (directory / "panel.txt").write_text(f"01\t50\t51\t{allele}\t{'GG' if allele == 'AA' else 'AA'}\n")
                result = self.run_r("DNPcall/DNPcall.R", ["--bamlist=bamlist.txt", "--DNPs=panel.txt",
                    "--out=output", f"--reference={reference}"], root=directory)
                if case == "wrong-ref":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("panel REF differs", result.stderr)
                elif case == "distinct-numeric-reads":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("no retained reference/alternative likelihoods", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    row, = table(directory / "output/individual_outputs/full_output_sample_0001.txt")
                    self.assertEqual((row["chr"], row["N_REF"], row["GT"]),
                                     ("01", "1", "0/0") if case == "covered" else ("01", "0", "NA"),
                                     (directory / "mpileup.txt").read_text())

    def test_contamination_uses_counts_and_exact_contig(self):
        panel = self.root / "panel.tsv"
        panel.write_text("chr\tpos\n01\t50\n")
        calls = self.root / "calls.tsv"
        calls.write_text("chr\tpos\tN_REF\tN_ALT\tN_Other\tratio_REF_ALT\n"
                         "01\t50\t99\t1\t0\t0.01\n1\t50\t100\t0\t0\t1\n")
        out = self.root / "results"
        result = self.run_r("NEWPAT/contamination/detect_contamination.R",
                            [str(panel), str(calls), str(out)])
        self.assertEqual(result.returncode, 0, result.stderr)
        row, = table(out / "contamination_calls.txt")
        self.assertEqual(row["chr"], "01")
        self.assertAlmostEqual(float(row["contamination"]), 0.01)


if __name__ == "__main__":
    unittest.main()
