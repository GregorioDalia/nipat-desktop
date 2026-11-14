"""Synthetic caller regressions exercised against the installed R payload."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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

    def execute(self, workflow, root, **fields):
        root.mkdir()
        request = root / "request.json"
        request.write_text(json.dumps({
            "schema_version": 1, "workflow": workflow, **fields,
            "work_dir": str(root / "work"), "out_dir": str(root / "output"),
        }), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(PAYLOAD / "engine/main.py"), "execute", workflow,
             "--request", str(request)], cwd=root, env=dict(
                self.env, PYTHONPATH=str(HELPERS.parent),
                NIPAT_DNP_BLOCKS_HELPER=str(HELPERS / "dnp_blocks.R"),
                NIPAT_DNP_PILEUP_HELPER=str(HELPERS / "dnp_pileup.py"),
            ), capture_output=True, text=True, timeout=90,
        )

    def fasta(self, contigs):
        fasta = self.root / "reference.fa"
        fasta.write_text("".join(f">{contig}\n" + "A" * 100 + "\n" for contig in contigs), encoding="utf-8")
        subprocess.run(["samtools", "faidx", str(fasta)], check=True, capture_output=True)
        return str(fasta)

    def bam(self, name, dictionary, reads):
        sam = self.root / f"{name}.sam"
        sam.write_text("@HD\tVN:1.6\tSO:coordinate\n"
                       + "".join(f"@SQ\tSN:{contig}\tLN:{length}\n" for contig, length in dictionary)
                       + "".join(f"{qname}\t0\t{contig}\t49\t60\t4M\t*\t0\t0\t{bases}\tIIII\n"
                                 for contig, qname, bases in reads), encoding="utf-8")
        bam = self.root / f"{name}.bam"
        subprocess.run(["samtools", "view", "-b", "-o", str(bam), str(sam)], check=True, capture_output=True)
        return bam

    def test_snp_calls_each_textual_contig_with_real_coverage(self):
        contigs = ("01", "1", "NA")
        rows = [("01", "001", "A"), ("1", "01", "G"), ("NA", "1", "A")]
        reference = self.fasta(contigs)
        bam = self.bam("reads", [(contig, 100) for contig in contigs],
                       [(contig, qname, f"A{base}AA") for contig, qname, base in rows])
        pileup = self.root / "pileup.tsv"
        pileup.write_text("".join(f"{contig}\t{pos}\tA\t1\t{base if pos == 50 else '.'}\tI\t{qname}\n"
                                  for contig, qname, base in rows for pos in (49, 50, 51)), encoding="utf-8")
        panel = self.root / "SNPpanel.tsv"
        panel.write_text("chr\tpos\tref\talt\n" + "".join(f"{contig}\t50\tA\tG\n" for contig in contigs),
                         encoding="utf-8")
        expected = {"01": ("1", "0", "0/0"), "1": ("0", "1", "1/1"), "NA": ("1", "0", "0/0")}
        for mode, sources in (("bam", dict(bam=str(bam), reference=reference, pileup=None)),
                              ("pileup", dict(bam=None, reference=None, pileup=str(pileup)))):
            with self.subTest(mode=mode):
                output = self.root / mode
                result = self.execute("snp-call", output, mode=mode, panel=str(panel),
                                      scientific_settings={"baq": False}, **sources)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                actual = table(output / "output/SNPcall_output.txt")
                self.assertEqual({row["chr"]: (row["N_REF"], row["N_ALT"], row["GT"]) for row in actual},
                                 expected)

    def test_callers_reject_mismatched_bam_targets_and_keep_true_zero_coverage(self):
        reference = self.fasta(("chrA", "chrB"))
        snp_panel, dnp_panel = self.root / "snp.tsv", self.root / "dnp.tsv"
        snp_panel.write_text("chr\tpos\tref\talt\nchrA\t50\tA\tG\n", encoding="utf-8")
        dnp_panel.write_text("chrA\t50\t51\tAA\tGG\n", encoding="utf-8")
        for case, dictionary, error in (
            ("missing", [("chrB", 100)], "assente dal dizionario BAM"),
            ("unequal", [("chrA", 101)], "lunghezza discordante"),
            ("empty", [("chrA", 100)], None),
        ):
            with self.subTest(case=case):
                bam = self.bam("sample_0001", dictionary, [])
                outputs = (self.root / (case + "-snp"), self.root / (case + "-dnp"))
                results = (
                    self.execute("snp-call", outputs[0], mode="bam", panel=str(snp_panel),
                                 reference=reference, bam=str(bam), pileup=None),
                    self.execute("dnp-call", outputs[1], panel=str(dnp_panel), reference=reference,
                                 samples=[{"path": str(bam), "sample_id": "sample_0001"}], parallel=False),
                )
                tables = ("SNPcall_output.txt", "individual_outputs/full_output_sample_0001.txt")
                for result, output, table_name in zip(results, outputs, tables, strict=True):
                    if error:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(error, result.stdout + result.stderr)
                        self.assertFalse((output / "work/scientific-validation.json").exists())
                    else:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        row, = table(output / "output" / table_name)
                        self.assertEqual((row["chr"], row["N_REF"], row["GT"]), ("chrA", "0", "NA"))

    def test_dnp_rejects_reordered_bam_targets_before_joint_pileup(self):
        reference = self.fasta(("chrA", "chrB"))
        panel = self.root / "dnp.tsv"
        panel.write_text("chrA\t50\t51\tAA\tGG\nchrB\t50\t51\tAA\tGG\n", encoding="utf-8")
        first = self.bam("sample_0001", [("chrA", 100), ("chrB", 100)], [("chrA", "read1", "AAAA")])
        second = self.bam("sample_0002", [("chrB", 100), ("chrA", 100)], [("chrB", "read2", "AAAA")])
        samples = [{"path": str(path), "sample_id": path.stem} for path in (first, second)]
        for case in ("unindexed", "mixed", "indexed"):
            with self.subTest(case=case):
                if case != "unindexed":
                    subprocess.run(["samtools", "index", str(first if case == "mixed" else second)],
                                   check=True, capture_output=True)
                output = self.root / case
                result = self.execute("dnp-call", output, panel=str(panel), reference=reference,
                                      samples=samples, parallel=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Dizionari BAM incompatibili", result.stdout + result.stderr)
                evidence = json.loads((output / "work/dnp-pileup.json").read_text(encoding="utf-8"))
                self.assertEqual(evidence["status"], "failed")
                self.assertEqual([item["stage"] for item in evidence["processes"]], ["header", "header"])
                self.assertFalse((output / "work/scientific-validation.json").exists())

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
