from __future__ import annotations

import copy
import csv
import errno
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from nipat_scientific.executor import (
    PlanExecutionError, _Cancellation, _run_process, execute_plan,
)
from nipat_scientific.errors import ValidationError


class UnsupportedExecutionTests(unittest.TestCase):
    def test_unsupported_step_rejects_whole_plan_before_any_file_access(self):
        plan = {"schema_version": 1, "samples": [
            {"id": "a", "kind": "snp-pileup", "path": "/missing/pileup.tsv"},
        ], "steps": [{"id": "snp", "workflow": "snp-call", "inputs": {
            "sample": "a", "reference": None, "panel": "/missing/panel.tsv",
        }, "parameters": {"mode": "pileup"}}]}
        with patch.object(Path, "is_file", side_effect=AssertionError("unexpected read")), \
                patch.object(Path, "mkdir", side_effect=AssertionError("unexpected write")):
            with self.assertRaises(PlanExecutionError) as caught:
                execute_plan(plan, run_dir=Path("/new/run"), script_paths={})
        self.assertEqual(caught.exception.code, "execution.workflow")


@unittest.skipUnless(os.name == "posix", "scientific execution runs inside the Linux image")
class WorkflowExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nipat-execution-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        for name in ("sample_0001.bam", "sample_0002.bam", "reference.fa", "reference.fa.fai"):
            (self.inputs / name).write_text(name, encoding="utf-8")
        (self.inputs / "panel.tsv").write_text("chr1\t10\t11\tAA\tGG\n", encoding="utf-8")
        self.scripts = {}
        for workflow in ("dnp-call", "contamination"):
            script = self.root / f"{workflow}.R"
            script.write_text("# unchanged scientific code\n", encoding="utf-8")
            self.scripts[workflow] = script
        self.run = self.root / "workflow"
        self.plan = {"schema_version": 1, "samples": [
            {"id": "donor_a", "kind": "bam", "path": str(self.inputs / "sample_0001.bam")},
            {"id": "donor_b", "kind": "bam", "path": str(self.inputs / "sample_0002.bam")},
        ], "steps": [
            {"id": "contamination", "workflow": "contamination", "inputs": {
                # Deliberately reverse both consumer order and step declaration.
                "samples": [{"step": "dnp", "output": "dnp-tables", "sample": "donor_b"},
                            {"step": "dnp", "output": "dnp-tables", "sample": "donor_a"}],
                "panel": str(self.inputs / "panel.tsv")}, "parameters": {}},
            {"id": "dnp", "workflow": "dnp-call", "inputs": {
                "samples": ["donor_a", "donor_b"], "reference": str(self.inputs / "reference.fa"),
                "panel": str(self.inputs / "panel.tsv")}, "parameters": {"parallel": False}},
        ]}
        self.calls = []

    def execute(self, action=None):
        return execute_plan(self.plan, run_dir=self.run, script_paths=self.scripts,
                            run_process=action or self.fake_r)

    def fake_r(self, command, cwd, log_path):
        self.calls.append(command)
        log_path.write_text("scientific output\n", encoding="utf-8")
        if Path(command[1]).name == "dnp-call.R":
            directory = cwd / "output" / "individual_outputs"
            directory.mkdir()
            for number in (1, 2):
                (directory / f"full_output_sample_{number:04d}.txt").write_text(
                    "chr\tpos1\tpos2\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n"
                    f"chr1\t10\t11\tAA\tGG\t{number * 100}\t0\t0\t{number * 100}\n",
                    encoding="utf-8",
                )
        else:
            selected, output = Path(command[-2]), Path(command[-1])
            rows = []
            for source in sorted(selected.iterdir()):
                with source.open(encoding="utf-8") as handle:
                    row = next(csv.DictReader(handle, delimiter="\t"))
                (output / f"contamination_{source.stem}.txt").write_text(
                    "chr\tpos1\tpos2\tN_REF\tcontamination\n"
                    f"chr1\t10\t11\t{row['N_REF']}\t0\n", encoding="utf-8",
                )
                rows.append(f"{source.stem}\t1\t0\tNA\n")
            (output / "contamination_summary.txt").write_text(
                "individuo\tinformative_DNPs\tmean_contamination\tsd_contamination\n" + "".join(rows),
                encoding="utf-8",
            )
        return 0

    def saved(self):
        return json.loads((self.run / "workflow-state.json").read_text(encoding="utf-8"))

    def test_chain_preserves_identity_when_consumer_order_is_reversed(self):
        original = copy.deepcopy(self.plan)
        inputs_before = {p.name: p.read_bytes() for p in self.inputs.iterdir()}
        result = self.execute()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["execution_order"], ["dnp", "contamination"])
        self.assertEqual([s["status"] for s in result["steps"]], ["succeeded", "succeeded"])
        self.assertEqual(result, self.saved())
        self.assertEqual(self.plan, original)
        self.assertEqual(inputs_before, {p.name: p.read_bytes() for p in self.inputs.iterdir()})
        artifacts = result["steps"][1]["artifacts"]["contamination-tables"]
        self.assertEqual([a["sample"] for a in artifacts], ["donor_b", "donor_a"])
        for artifact, expected in zip(artifacts, (200, 100), strict=True):
            path = self.run / artifact["path"]
            self.assertEqual(artifact["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertIn(f"\t{expected}\t", path.read_text(encoding="utf-8"))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result["plan_sha256"], hashlib.sha256((self.run / "plan.json").read_bytes()).hexdigest())

    def test_existing_run_is_never_overwritten_even_after_success(self):
        self.execute()
        before = (self.run / "workflow-state.json").read_bytes()
        with self.assertRaises(PlanExecutionError) as caught:
            self.execute()
        self.assertEqual(caught.exception.code, "execution.destination")
        self.assertEqual(before, (self.run / "workflow-state.json").read_bytes())
        self.assertEqual(len(self.calls), 2)

    def test_reordered_dnp_aliases_fail_before_run_creation(self):
        self.plan["steps"][1]["inputs"]["samples"].reverse()
        with self.assertRaises(PlanExecutionError) as caught:
            self.execute()
        self.assertEqual(caught.exception.code, "execution.alias")
        self.assertFalse(self.run.exists())
        self.assertFalse(self.calls)

    def test_symlink_alias_cannot_hide_unsafe_native_path(self):
        original = self.inputs / "sample_0001.bam"
        unsafe = self.inputs / "unsafe name.bam"
        original.rename(unsafe)
        original.symlink_to(unsafe)
        with self.assertRaises(PlanExecutionError) as caught:
            self.execute()
        self.assertEqual(caught.exception.code, "execution.alias")
        self.assertFalse(self.run.exists())

    def test_same_physical_bam_cannot_acquire_two_identities(self):
        second = self.inputs / "sample_0002.bam"
        second.unlink()
        second.hardlink_to(self.inputs / "sample_0001.bam")
        with self.assertRaises(PlanExecutionError) as caught:
            self.execute()
        self.assertEqual(caught.exception.code, "execution.sample_identity")
        self.assertFalse(self.run.exists())

    def test_missing_reference_index_is_preflight_failure(self):
        (self.inputs / "reference.fa.fai").unlink()
        with self.assertRaises(ValidationError):
            self.execute()
        self.assertFalse(self.run.exists())

    def test_missing_later_panel_is_detected_before_dnp_runs(self):
        self.plan["steps"][0]["inputs"]["panel"] = str(self.inputs / "missing.tsv")
        with self.assertRaises(ValidationError):
            self.execute()
        self.assertFalse(self.run.exists())
        self.assertFalse(self.calls)

    def test_nonzero_dnp_blocks_consumer_and_preserves_native_exit_code(self):
        def fail(command, cwd, log_path):
            log_path.write_text("native failure\n", encoding="utf-8")
            self.calls.append(command)
            return 17
        result = self.execute(fail)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 17)
        self.assertEqual([s["status"] for s in result["steps"]], ["failed", "blocked"])
        self.assertEqual(result["error"]["code"], "execution.process")
        self.assertEqual(result, self.saved())
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.run / "steps" / "contamination").exists())

    def test_missing_or_misnamed_dnp_table_blocks_consumer_even_after_exit_zero(self):
        for mutation in ("missing", "extra", "schema", "symlink"):
            with self.subTest(mutation=mutation):
                self.run = self.root / f"workflow_{mutation}"
                def malformed(command, cwd, log_path):
                    self.fake_r(command, cwd, log_path)
                    directory = cwd / "output" / "individual_outputs"
                    first = directory / "full_output_sample_0001.txt"
                    if mutation == "missing":
                        first.unlink()
                    elif mutation == "extra":
                        (directory / "full_output_unregistered.txt").write_bytes(first.read_bytes())
                    elif mutation == "schema":
                        first.write_text("wrong\tcolumns\n", encoding="utf-8")
                    else:
                        outside = self.root / "outside.txt"
                        outside.write_bytes(first.read_bytes())
                        first.unlink()
                        first.symlink_to(outside)
                    return 0
                result = self.execute(malformed)
                self.assertEqual([s["status"] for s in result["steps"]], ["failed", "blocked"])
                self.assertEqual(result["exit_code"], 2)
                self.assertEqual(result["steps"][0]["artifacts"], {})

    def test_corrupted_contamination_summary_is_not_success(self):
        def malformed(command, cwd, log_path):
            self.fake_r(command, cwd, log_path)
            if Path(command[1]).name == "contamination.R":
                path = Path(command[-1]) / "contamination_summary.txt"
                path.write_text(path.read_text(encoding="utf-8").replace("table_0001", "unregistered"), encoding="utf-8")
            return 0
        result = self.execute(malformed)
        self.assertEqual([s["status"] for s in result["steps"]], ["succeeded", "failed"])
        self.assertEqual(result["error"]["code"], "execution.output")

    def test_keyboard_interrupt_blocks_downstream_and_restores_handlers(self):
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        def interrupt(command, cwd, log_path):
            raise KeyboardInterrupt
        result = self.execute(interrupt)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["exit_code"], 130)
        self.assertEqual([s["status"] for s in result["steps"]], ["cancelled", "blocked"])
        self.assertEqual(result, self.saved())
        self.assertEqual(handlers, {sig: signal.getsignal(sig) for sig in handlers})

    def test_signal_cancellation_wins_over_child_zero_exit(self):
        def cancel(command, cwd, log_path):
            self.fake_r(command, cwd, log_path)
            signal.raise_signal(signal.SIGTERM)
            return 0
        result = self.execute(cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["exit_code"], 143)
        self.assertEqual([s["status"] for s in result["steps"]], ["cancelled", "blocked"])
        self.assertEqual(len(self.calls), 1)

    def test_unsupported_directory_fsync_does_not_break_host_backed_runs(self):
        actual_fsync = os.fsync
        unsupported = []
        def mounted_fsync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                unsupported.append(descriptor)
                raise OSError(errno.EINVAL, "Directory sync unsupported by host mount")
            return actual_fsync(descriptor)
        with patch("nipat_scientific.executor.os.fsync", side_effect=mounted_fsync):
            result = self.execute()
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(unsupported)
        self.assertEqual(result, self.saved())

    def test_unexpected_preparation_error_is_a_failed_run(self):
        with patch("nipat_scientific.executor.prepare_dnp", side_effect=RuntimeError("unexpected adapter fault")):
            result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["error"]["code"], "execution.internal")
        self.assertEqual([s["status"] for s in result["steps"]], ["failed", "blocked"])
        self.assertEqual(result, self.saved())

    def test_imported_tables_execute_without_dnp(self):
        source = self.inputs / "provided.tsv"
        source.write_text("chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\nchr1\t10\t11\t300\t0\t0\n", encoding="utf-8")
        self.plan["samples"] = [{"id": "imported", "kind": "dnp-table", "path": str(source)}]
        self.plan["steps"] = [self.plan["steps"][0]]
        self.plan["steps"][0]["inputs"]["samples"] = [{"sample": "imported"}]
        result = self.execute()
        self.assertEqual(result["status"], "succeeded")
        artifact = result["steps"][0]["artifacts"]["contamination-tables"][0]
        self.assertEqual(artifact["sample"], "imported")
        self.assertEqual(artifact["source"], {"sample": "imported"})

    def test_subprocess_log_and_exact_argv_preserve_special_characters(self):
        log = self.root / "process.log"
        code = _run_process([sys.executable, "-c", "import sys; print(sys.argv[1]); print('error', file=sys.stderr)",
                             "literal $() ; ' quoted"], self.root, log, _Cancellation())
        self.assertEqual(code, 0)
        self.assertIn("literal $() ; ' quoted", log.read_text())
        self.assertIn("error", log.read_text())

    def test_cancellation_terminates_r_process_group_including_descendant(self):
        marker = self.root / "child-finished"
        ready = self.root / "child-ready"
        child_code = (
            "import pathlib, signal, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"pathlib.Path({str(ready)!r}).write_text('ready'); "
            "time.sleep(3); "
            f"pathlib.Path({str(marker)!r}).write_text('orphan')"
        )
        parent_code = (
            "import subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
            "time.sleep(30)"
        )
        cancellation = _Cancellation()
        def cancel_when_ready():
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            cancellation.receive(signal.SIGTERM, None)
        worker = threading.Thread(target=cancel_when_ready)
        worker.start()
        code = _run_process([sys.executable, "-c", parent_code], self.root, self.root / "process.log", cancellation)
        worker.join(timeout=6)
        self.assertEqual(code, 143)
        self.assertTrue(ready.exists())
        time.sleep(3.1)
        self.assertFalse(marker.exists(), "cancelled scientific descendants must not outlive the plan")


if __name__ == "__main__":
    unittest.main()
