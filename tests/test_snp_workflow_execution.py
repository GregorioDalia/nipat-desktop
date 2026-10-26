from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest

from nipat_scientific.errors import ValidationError
from nipat_scientific.executor import PlanExecutionError, execute_plan


@unittest.skipUnless(os.name == "posix", "scientific execution runs inside the Linux image")
class SnpWorkflowExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nipat-snp-plan-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "original inputs $ ,="
        self.inputs.mkdir()
        self.bam = self.inputs / "sample_0001.bam"
        self.bam.write_bytes(b"fixture bam")
        self.reference = self.inputs / "reference.fa"
        self.reference.write_text(">chr1\nAAAAAAAAAAAAAAAAAAAA\n", encoding="utf-8")
        Path(str(self.reference) + ".fai").write_text("chr1\t20\t6\t20\t21\n", encoding="utf-8")
        self.panel = self.inputs / "snp panel.tsv"
        self.panel.write_text("pos\tref\talt\nchr1:10\tA\tG\nchr1:15\tA\tT\n", encoding="utf-8")
        self.pileup = self.inputs / "pileup.txt"
        self.pileup.write_text("chr1\t10\tA\t2\t.G\tII\tread1,read2\n", encoding="utf-8")
        self.script = self.root / "SNPcall.R"
        self.script.write_text("# unchanged R\n", encoding="utf-8")
        self.run = self.root / "workflow"
        self.plan = {"schema_version": 1, "samples": [
            {"id": "donor", "kind": "bam", "path": str(self.bam)},
        ], "steps": [{"id": "snp", "workflow": "snp-call", "inputs": {
            "sample": "donor", "reference": str(self.reference), "panel": str(self.panel),
        }, "parameters": {"mode": "bam"}}]}
        self.calls = []

    def execute(self, process=None):
        return execute_plan(self.plan, run_dir=self.run, script_paths={"snp-call": self.script},
                            run_process=process or self.fake_process)

    def fake_process(self, command, cwd, log):
        self.calls.append(command)
        log.write_text("samtools output\n" if command[0] == "samtools" else "R output\n", encoding="utf-8")
        if command[0] == "samtools":
            Path(command[command.index("-o") + 1]).write_bytes(self.pileup.read_bytes())
        else:
            Path(command[command.index("--out") + 1]).write_text(
                "chr\tpos\tReference\tAlternative\tN_Reference\tN_Alternative\tN_Altro\ttotal_count\tratio\n"
                "chr1\t10\tA\tG\t1\t1\t0\t2\t0.5\n"
                "chr1\t15\tA\tT\t0\t0\t0\t0\tNA\n", encoding="utf-8",
            )
        return 0

    def imported_pileup(self):
        self.plan["samples"][0].update(kind="snp-pileup", path=str(self.pileup))
        self.plan["steps"][0]["inputs"]["reference"] = None
        self.plan["steps"][0]["parameters"]["mode"] = "pileup"

    def add_independent_step(self):
        step = copy.deepcopy(self.plan["steps"][0])
        step["id"] = "zzz_snp"
        self.plan["steps"].append(step)

    def test_bam_prepares_then_runs_r_and_preserves_originals_and_intermediates(self):
        before = {path.name: path.read_bytes() for path in self.inputs.iterdir()}
        result = self.execute()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual([call[0] for call in self.calls], ["samtools", "Rscript"])
        self.assertEqual(self.calls[0][-1], str(self.bam))
        self.assertEqual(result, json.loads((self.run / "workflow-state.json").read_text()))
        record = result["steps"][0]
        self.assertEqual(record["sample_mapping"], {"sample": "donor", "mode": "bam", "path": str(self.bam)})
        self.assertEqual(record["preparation_exit_code"], 0)
        self.assertEqual(record["artifacts"]["snp-tables"][0]["sample"], "donor")
        self.assertEqual(record["artifacts"]["preparation"], record["preparation_artifacts"])
        self.assertEqual([item["kind"] for item in record["preparation_artifacts"]], ["regions-bed", "pileup"])
        for artifact in [*record["preparation_artifacts"], *record["artifacts"]["snp-tables"]]:
            path = self.run / artifact["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"])
        self.assertEqual((self.run / "steps/snp/work/snp_regions.bed").read_text(),
                         "chr1\t8\t11\nchr1\t13\t16\n")
        self.assertEqual((self.run / "steps/snp/preparation.log").read_text(), "samtools output\n")
        self.assertEqual((self.run / "steps/snp/command.log").read_text(), "R output\n")
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.inputs.iterdir()})

    def test_imported_pileup_calls_only_r_and_does_not_claim_generation(self):
        self.imported_pileup()
        result = self.execute()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual([call[0] for call in self.calls], ["Rscript"])
        self.assertEqual(self.calls[0][self.calls[0].index("--pileup") + 1], str(self.pileup))
        record = result["steps"][0]
        self.assertNotIn("preparation_command", record)
        self.assertNotIn("preparation_artifacts", record)
        self.assertEqual(record["artifacts"]["preparation"], [])
        self.assertFalse((self.run / "steps/snp/work/pileup.txt").exists())
        self.assertFalse((self.run / "steps/snp/preparation.log").exists())

    def test_duplicate_panel_coordinates_and_zero_count_na_remain_supported(self):
        self.imported_pileup()
        with self.panel.open("a", encoding="utf-8") as handle:
            handle.write("chr1:10\tA\tG\n")
        def repeated_result(command, cwd, log):
            self.fake_process(command, cwd, log)
            output = Path(command[command.index("--out") + 1])
            with output.open("a", encoding="utf-8") as handle:
                handle.write("chr1\t10\tA\tG\t1\t1\t0\t2\t0.5\n")
            return 0
        result = self.execute(repeated_result)
        self.assertEqual(result["status"], "succeeded")
        output = self.run / result["steps"][0]["artifacts"]["snp-tables"][0]["path"]
        self.assertIn("chr1\t15\tA\tT\t0\t0\t0\t0\tNA", output.read_text())

    def test_external_input_errors_prevent_all_execution_and_directory_creation(self):
        original = copy.deepcopy(self.plan)
        for mutation in ("reference_missing", "index_missing", "bgzf_index_missing", "bad_panel", "bad_pileup"):
            with self.subTest(mutation=mutation):
                self.plan = copy.deepcopy(original)
                self.run = self.root / mutation
                self.reference.write_text(">chr1\nAAAA\n", encoding="utf-8")
                Path(str(self.reference) + ".fai").write_text("index", encoding="utf-8")
                self.panel.write_text("pos\tref\talt\nchr1:10\tA\tG\n", encoding="utf-8")
                if mutation == "reference_missing":
                    self.reference.unlink()
                elif mutation == "index_missing":
                    Path(str(self.reference) + ".fai").unlink()
                elif mutation == "bgzf_index_missing":
                    reference = self.inputs / "reference.fa.gz"
                    reference.write_bytes(b"compressed")
                    Path(str(reference) + ".fai").write_text("index", encoding="utf-8")
                    self.plan["steps"][0]["inputs"]["reference"] = str(reference)
                elif mutation == "bad_panel":
                    self.panel.write_text("pos\tref\talt\nchr1:1\tA\tG\n", encoding="utf-8")
                else:
                    self.imported_pileup()
                    self.pileup.write_text("chr1\t10\tA\t2\t.G\tII\n", encoding="utf-8")
                with self.assertRaises(ValidationError):
                    self.execute()
                self.assertFalse(self.run.exists())
                self.assertEqual(self.calls, [])

    def test_later_invalid_independent_step_prevents_earlier_valid_step(self):
        self.add_independent_step()
        self.plan["steps"][1]["inputs"]["panel"] = str(self.inputs / "missing.tsv")
        with self.assertRaises(ValidationError):
            self.execute()
        self.assertFalse(self.run.exists())
        self.assertEqual(self.calls, [])

    def test_samtools_failure_preserves_log_without_running_r_or_next_step(self):
        self.add_independent_step()
        def fail(command, cwd, log):
            self.calls.append(command)
            log.write_text("reference mismatch", encoding="utf-8")
            return 23
        result = self.execute(fail)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 23)
        self.assertEqual([s["status"] for s in result["steps"]], ["failed", "blocked"])
        self.assertEqual([call[0] for call in self.calls], ["samtools"])
        self.assertEqual(result["steps"][0]["preparation_exit_code"], 23)
        self.assertTrue((self.run / "steps/snp/request.json").exists())
        self.assertFalse((self.run / "steps/snp/command.log").exists())
        self.assertFalse((self.run / "steps/zzz_snp").exists())

    def test_zero_exit_with_missing_empty_or_invalid_generated_pileup_prevents_r(self):
        for content in (None, "", "chr1\t10\tA\t1\t.\tI\n"):
            with self.subTest(content=content):
                self.run = self.root / f"invalid_{len(self.calls)}"
                def invalid(command, cwd, log):
                    self.calls.append(command)
                    log.write_text("preparation finished", encoding="utf-8")
                    if content is not None:
                        Path(command[command.index("-o") + 1]).write_text(content, encoding="utf-8")
                    return 0
                result = self.execute(invalid)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["exit_code"], 2)
                self.assertTrue(all(call[0] == "samtools" for call in self.calls))
                self.assertFalse((self.run / "steps/snp/command.log").exists())

    def test_preparation_cancellation_blocks_other_independent_steps(self):
        self.add_independent_step()
        def cancel(command, cwd, log):
            self.fake_process(command, cwd, log)
            signal.raise_signal(signal.SIGTERM)
            return 0
        result = self.execute(cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["exit_code"], 143)
        self.assertEqual([s["status"] for s in result["steps"]], ["cancelled", "blocked"])
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.run / "steps/snp/command.log").exists())

    def test_r_failure_keeps_generated_artifacts_and_does_not_start_next_step(self):
        self.add_independent_step()
        def fail_r(command, cwd, log):
            if command[0] == "samtools":
                return self.fake_process(command, cwd, log)
            self.calls.append(command)
            log.write_text("R error", encoding="utf-8")
            return 17
        result = self.execute(fail_r)
        self.assertEqual(result["exit_code"], 17)
        self.assertEqual([s["status"] for s in result["steps"]], ["failed", "blocked"])
        self.assertEqual(len(result["steps"][0]["preparation_artifacts"]), 2)
        self.assertEqual(result["steps"][0]["artifacts"], {})

    def test_r_cancellation_keeps_preparation_and_sample_identity(self):
        self.add_independent_step()
        def cancel_r(command, cwd, log):
            self.fake_process(command, cwd, log)
            if command[0] == "Rscript":
                raise KeyboardInterrupt
            return 0
        result = self.execute(cancel_r)
        self.assertEqual(result["exit_code"], 130)
        self.assertEqual([s["status"] for s in result["steps"]], ["cancelled", "blocked"])
        record = result["steps"][0]
        self.assertEqual(record["sample_mapping"]["sample"], "donor")
        self.assertEqual(len(record["preparation_artifacts"]), 2)
        self.assertEqual(record["artifacts"], {})
        self.assertFalse((self.run / "steps/zzz_snp").exists())

    def test_missing_malformed_or_unrelated_results_are_not_successful(self):
        self.imported_pileup()
        for mutation in ("missing", "header_only", "column_missing", "duplicate_column", "short_row", "wrong_locus", "outside"):
            with self.subTest(mutation=mutation):
                self.run = self.root / mutation
                def corrupt(command, cwd, log):
                    self.fake_process(command, cwd, log)
                    output = Path(command[command.index("--out") + 1])
                    text = output.read_text()
                    if mutation == "missing":
                        output.unlink()
                    elif mutation == "header_only":
                        output.write_text(text.splitlines()[0] + "\n")
                    elif mutation == "column_missing":
                        output.write_text(text.replace("N_Altro", "unknown"))
                    elif mutation == "duplicate_column":
                        output.write_text(text.replace("\tratio\n", "\tratio\tratio\n"))
                    elif mutation == "short_row":
                        output.write_text(text + "chr1\t10\n")
                    elif mutation == "wrong_locus":
                        output.write_text(text.replace("chr1\t15\t", "chr2\t15\t"))
                    else:
                        external = self.inputs / "outside.txt"
                        external.write_text(text)
                        output.unlink()
                        output.symlink_to(external)
                    return 0
                result = self.execute(corrupt)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"]["code"], "execution.output")

    def test_multiple_steps_share_one_sample_but_keep_results_separate(self):
        self.add_independent_step()
        result = self.execute()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["execution_order"], ["snp", "zzz_snp"])
        artifacts = [record["artifacts"]["snp-tables"][0] for record in result["steps"]]
        self.assertEqual([artifact["sample"] for artifact in artifacts], ["donor", "donor"])
        self.assertNotEqual(artifacts[0]["path"], artifacts[1]["path"])
        self.assertEqual(artifacts[0]["sha256"], artifacts[1]["sha256"])
        snapshot = {str(path.relative_to(self.run)): path.read_bytes() for path in self.run.rglob("*") if path.is_file()}
        with self.assertRaises(PlanExecutionError):
            self.execute()
        self.assertEqual(snapshot, {str(path.relative_to(self.run)): path.read_bytes() for path in self.run.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
