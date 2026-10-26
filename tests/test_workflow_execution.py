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
from nipat_scientific.plan import PlanValidationError


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
        for workflow in ("dnp-call", "contamination", "cpi"):
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
        elif Path(command[1]).name == "contamination.R":
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
        else:
            output = Path(command[command.index("--out_dir") + 1])
            pairs = next(argument.split("=", 1)[1] for argument in command if argument.startswith("--pairs="))
            cutoff_argument = next((argument.split("=", 1)[1] for argument in command
                                    if argument.startswith("--cutoff_map=")), None)
            cutoffs = [None] if cutoff_argument is None else [
                item.split("=", 1)[0] for item in cutoff_argument.split(",")
            ]
            columns = ["Pair", "N_sites_mother", "N_sites_father", "Median_fetal_fraction_raw",
                       "Median_fetal_fraction_percent", "Max_logCPI", "Min_logCPI",
                       "Median_logCPI", "Mean_logCPI", "CPI_medianFF"]
            if cutoff_argument is not None:
                columns.insert(1, "Cutoff")
            plots = output / "plots"
            plots.mkdir()
            with (output / "Summary_FetalFraction_CPI.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                for pair in pairs.split(","):
                    mother, father = pair.split(":")
                    native_pair = f"Mother{mother}-Father{father}_DNPs"
                    for cutoff in cutoffs:
                        row = {name: "NA" for name in columns}
                        row.update(Pair=native_pair, N_sites_mother="0", N_sites_father="0")
                        if cutoff is not None:
                            row["Cutoff"] = cutoff
                        writer.writerow(row)
                    (plots / f"{native_pair}_CPIplot.pdf").write_bytes(b"%PDF-1.7\nfixture\n")
            (plots / "All_CPIplots.pdf").write_bytes(b"%PDF-1.7\nfixture\n")
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

    def add_cpi(self, *, mode="all", imported=False, shared_father=False):
        popfreq = self.inputs / "popfreq.tsv"
        popfreq.write_text("chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\nchr1\t10\t11\t0.7\t0.3\n", encoding="utf-8")
        if imported:
            # Original filenames deliberately contradict the declared roles.
            registry = []
            for number, (identifier, filename) in enumerate((
                    ("maternal_A", "Father_original.txt"), ("paternal_A", "Mother_original.txt"),
                    ("maternal_B", "unclassified sample.txt")), 1):
                path = self.inputs / filename
                path.write_text(
                    "chr\tpos1\tpos2\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\n"
                    f"chr1\t10\t11\tAA\tGG\t{number * 100}\t0\t0\t{number * 100}\n", encoding="utf-8",
                )
                registry.append({"id": identifier, "kind": "dnp-table", "path": str(path)})
            self.plan["samples"] = registry
            self.plan["steps"] = []
            pairs = [{"id": "family_A", "mother": {"sample": "maternal_A"}, "father": {"sample": "paternal_A"}}]
            if shared_father:
                pairs.append({"id": "family_B", "mother": {"sample": "maternal_B"}, "father": {"sample": "paternal_A"}})
        else:
            pairs = [{"id": "family_A", "mother": {"step": "dnp", "output": "dnp-tables", "sample": "donor_a"},
                      "father": {"step": "dnp", "output": "dnp-tables", "sample": "donor_b"}}]
        cutoffs = [] if mode == "all" else ([{"label": "", "path": str(self.inputs / "panel.tsv")}]
                                            if mode == "panel" else [
                                                {"label": "Full", "path": str(self.inputs / "panel.tsv")},
                                                {"label": "Subset", "path": str(self.inputs / "panel.tsv")},
                                            ])
        step = {"id": "cpi", "workflow": "cpi", "inputs": {
            "pairs": pairs, "popfreq": str(popfreq), "cutoffs": cutoffs,
        }, "parameters": {"err_const": 0.0025, "cutoff_mode": mode}}
        self.plan["steps"].append(step)
        return step

    def cpi_request(self):
        return json.loads((self.run / "steps/cpi/request.json").read_text(encoding="utf-8"))

    def test_complete_chain_runs_cpi_from_dnp_not_contamination_output(self):
        cpi = self.add_cpi()
        result = self.execute()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["execution_order"], ["dnp", "contamination", "cpi"])
        request = self.cpi_request()
        self.assertEqual(request["err_const"], 0.0025)
        self.assertEqual(self.calls[-1][self.calls[-1].index("--err_const") + 1], "0.0025")
        self.assertTrue(all("steps/dnp/output/individual_outputs" in item["path"] for item in request["samples"]))
        pair = result["steps"][2]["artifacts"]["cpi-pairs"][0]
        self.assertEqual(pair["pair"], "family_A")
        self.assertEqual(pair["mother"], cpi["inputs"]["pairs"][0]["mother"])
        self.assertEqual(pair["father"], cpi["inputs"]["pairs"][0]["father"])
        self.assertEqual(pair["native_pair"], "Mothers0001-Fathers0002_DNPs")
        self.assertEqual(pair["summary_rows"], [{"row": 1, "cutoff": None}])
        self.assertEqual(result, self.saved())

    def test_dnp_to_cpi_does_not_require_contamination(self):
        self.add_cpi(mode="panel")
        self.plan["steps"] = [step for step in self.plan["steps"] if step["workflow"] != "contamination"]
        result = self.execute()
        self.assertEqual(result["execution_order"], ["dnp", "cpi"])
        self.assertEqual(result["status"], "succeeded")
        artifact = result["steps"][1]["artifacts"]["cpi-pairs"][0]
        self.assertEqual(artifact["summary_rows"], [{"row": 1, "cutoff": str(self.run / "steps/cpi/work/DNPpanel.txt")}])

    def test_imported_cpi_shared_father_is_staged_once_and_roles_are_explicit(self):
        self.add_cpi(imported=True, shared_father=True, mode="named")
        before = {p.name: p.read_bytes() for p in self.inputs.iterdir()}
        result = self.execute()
        self.assertEqual(result["status"], "succeeded")
        request = self.cpi_request()
        self.assertEqual(request["pairs"], "s0001:s0002,s0003:s0002")
        self.assertEqual([item["name"] for item in request["samples"]],
                         ["Mothers0001.txt", "Fathers0002.txt", "Mothers0003.txt"])
        self.assertEqual(len(list((self.run / "steps/cpi/work/inputs").iterdir())), 3)
        pairs = result["steps"][0]["artifacts"]["cpi-pairs"]
        self.assertEqual([pair["pair"] for pair in pairs], ["family_A", "family_B"])
        self.assertEqual([pair["native_pair"] for pair in pairs],
                         ["Mothers0001-Fathers0002_DNPs", "Mothers0003-Fathers0002_DNPs"])
        self.assertEqual([entry["cutoff"] for entry in pairs[0]["summary_rows"]], ["Full", "Subset"])
        for original, staged in (("Father_original.txt", "Mothers0001.txt"),
                                 ("Mother_original.txt", "Fathers0002.txt"),
                                 ("unclassified sample.txt", "Mothers0003.txt")):
            self.assertEqual((self.inputs / original).read_bytes(), (self.run / "steps/cpi/work/inputs" / staged).read_bytes())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.inputs.iterdir()})

    def test_cpi_missing_or_invalid_external_input_fails_before_any_analysis(self):
        original = copy.deepcopy(self.plan)
        for mutation in ("population_missing", "population_schema", "cutoff_missing", "imported_schema"):
            with self.subTest(mutation=mutation):
                self.plan = copy.deepcopy(original)
                self.run = self.root / f"run_{mutation}"
                step = self.add_cpi(mode="named", imported=mutation == "imported_schema")
                if mutation == "population_missing":
                    step["inputs"]["popfreq"] = str(self.inputs / "missing.tsv")
                elif mutation == "population_schema":
                    Path(step["inputs"]["popfreq"]).write_text("chr\tpos1\tpos2\n", encoding="utf-8")
                elif mutation == "cutoff_missing":
                    step["inputs"]["cutoffs"][0]["path"] = str(self.inputs / "missing.tsv")
                else:
                    (self.inputs / "Father_original.txt").write_text("chr\tpos1\tpos2\n", encoding="utf-8")
                with self.assertRaises(ValidationError):
                    self.execute()
                self.assertFalse(self.run.exists())
                self.assertFalse(self.calls)

    def test_cpi_original_case_colliding_basenames_do_not_collide_in_staging(self):
        self.add_cpi(imported=True)
        self.plan["samples"] = self.plan["samples"][:2]
        for sample, directory, name in zip(self.plan["samples"], ("first", "second"),
                                           ("SAMPLE.txt", "sample.txt"), strict=True):
            destination = self.inputs / directory / name
            destination.parent.mkdir()
            Path(sample["path"]).rename(destination)
            sample["path"] = str(destination)
        result = self.execute()
        self.assertEqual(result["status"], "succeeded")
        request = self.cpi_request()
        self.assertEqual([item["name"] for item in request["samples"]], ["Mothers0001.txt", "Fathers0002.txt"])
        for item in request["samples"]:
            self.assertEqual(Path(item["path"]).read_bytes(),
                             (self.run / "steps/cpi/work/inputs" / item["name"]).read_bytes())

    def test_cpi_case_ambiguous_pair_ids_and_role_conflicts_are_preflight_errors(self):
        step = self.add_cpi(imported=True, shared_father=True)
        step["inputs"]["pairs"][1]["id"] = "FAMILY_a"
        with self.assertRaises(PlanValidationError) as caught:
            self.execute()
        self.assertEqual(caught.exception.code, "plan.duplicate")
        self.assertFalse(self.run.exists())
        step["inputs"]["pairs"][1]["id"] = "family_B"
        step["inputs"]["pairs"][1]["mother"] = {"sample": "paternal_A"}
        with self.assertRaises(PlanValidationError) as caught:
            self.execute()
        self.assertEqual(caught.exception.code, "plan.roles")
        self.assertFalse(self.run.exists())

    def test_cpi_cutoff_map_path_delimiters_are_rejected_before_mkdir(self):
        self.add_cpi(imported=True, mode="panel")
        self.run = self.root / "run,unsafe"
        with self.assertRaises(PlanExecutionError) as caught:
            self.execute()
        self.assertEqual(caught.exception.code, "execution.alias")
        self.assertFalse(self.run.exists())

    def test_cpi_missing_outputs_or_wrong_pair_cutoff_are_not_success(self):
        for mutation in ("summary_missing", "pair_missing", "combined_missing", "wrong_pair", "wrong_cutoff",
                         "duplicate_row", "missing_column", "invalid_pdf", "unexpected_pdf", "outside_pdf"):
            with self.subTest(mutation=mutation):
                self.run = self.root / f"cpi_{mutation}"
                self.add_cpi(imported=True, mode="named")
                def malformed(command, cwd, log_path):
                    self.fake_r(command, cwd, log_path)
                    output = Path(command[command.index("--out_dir") + 1])
                    summary = output / "Summary_FetalFraction_CPI.csv"
                    plots = output / "plots"
                    plot = plots / "Mothers0001-Fathers0002_DNPs_CPIplot.pdf"
                    if mutation == "summary_missing":
                        summary.unlink()
                    elif mutation == "pair_missing":
                        plot.unlink()
                    elif mutation == "combined_missing":
                        (plots / "All_CPIplots.pdf").unlink()
                    elif mutation == "wrong_pair":
                        summary.write_text(summary.read_text().replace("Mothers0001", "MotherWrong"))
                    elif mutation == "wrong_cutoff":
                        summary.write_text(summary.read_text().replace("Full", "Wrong"))
                    elif mutation == "duplicate_row":
                        with summary.open("a") as handle:
                            handle.write(summary.read_text().splitlines()[1] + "\n")
                    elif mutation == "missing_column":
                        summary.write_text(summary.read_text().replace("CPI_medianFF", "Unknown"))
                    elif mutation == "invalid_pdf":
                        plot.write_bytes(b"not a pdf")
                    elif mutation == "unexpected_pdf":
                        (plots / "unregistered.pdf").write_bytes(b"%PDF-1.7\n")
                    else:
                        external = self.root / "outside.pdf"
                        external.write_bytes(plot.read_bytes())
                        plot.unlink()
                        plot.symlink_to(external)
                    return 0
                result = self.execute(malformed)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"]["code"], "execution.output")
                self.assertEqual(result["steps"][0]["artifacts"], {})

    def test_cpi_all_mode_rejects_cutoff_column(self):
        self.add_cpi(imported=True)
        def malformed(command, cwd, log_path):
            self.fake_r(command, cwd, log_path)
            summary = Path(command[command.index("--out_dir") + 1]) / "Summary_FetalFraction_CPI.csv"
            lines = summary.read_text().splitlines()
            summary.write_text(lines[0] + ",Cutoff\n" + "\n".join(line + ",ALL" for line in lines[1:]) + "\n")
            return 0
        result = self.execute(malformed)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "execution.output")

    def test_cpi_failure_and_cancellation_preserve_completed_analyses(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                self.run = self.root / ("cpi_cancelled" if cancelled else "cpi_failed")
                if not any(step["workflow"] == "cpi" for step in self.plan["steps"]):
                    self.add_cpi()
                    later = copy.deepcopy(self.plan["steps"][0])
                    later["id"] = "zzz_contamination"
                    self.plan["steps"].append(later)
                def stop_cpi(command, cwd, log_path):
                    if Path(command[1]).name != "cpi.R":
                        return self.fake_r(command, cwd, log_path)
                    if cancelled:
                        raise KeyboardInterrupt
                    log_path.write_text("R failure", encoding="utf-8")
                    return 41
                result = self.execute(stop_cpi)
                self.assertEqual([step["status"] for step in result["steps"]],
                                 ["succeeded", "succeeded", "cancelled" if cancelled else "failed", "blocked"])
                self.assertEqual(result["exit_code"], 130 if cancelled else 41)
                self.assertEqual(result["steps"][2]["pair_mapping"], [{
                    "pair": "family_A", "native_pair": "Mothers0001-Fathers0002_DNPs",
                    "mother": {"step": "dnp", "output": "dnp-tables", "sample": "donor_a"},
                    "father": {"step": "dnp", "output": "dnp-tables", "sample": "donor_b"},
                }])
                self.assertTrue((self.run / "steps/dnp/output/individual_outputs/full_output_sample_0001.txt").is_file())
                self.assertFalse((self.run / "steps/zzz_contamination").exists())
                self.assertEqual(result, self.saved())

    def test_completed_cpi_run_cannot_be_reused(self):
        self.add_cpi(imported=True, shared_father=True)
        self.execute()
        snapshot = {str(p.relative_to(self.run)): p.read_bytes() for p in self.run.rglob("*") if p.is_file()}
        with self.assertRaises(PlanExecutionError):
            self.execute()
        self.assertEqual(snapshot, {str(p.relative_to(self.run)): p.read_bytes() for p in self.run.rglob("*") if p.is_file()})

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
