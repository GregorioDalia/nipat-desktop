"""Exercise bounded SNP worker processes, state ownership and descendant cleanup."""

import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

from nipat_scientific.executor import _atomic_json, _Cancellation, execute_plan
from nipat_scientific.parallel import THREAD_LIMITS
from nipat_scientific.snp_parallel import execute_independent_snp_steps


FAKE_R = r'''
import json, os, pathlib, signal, subprocess, sys, time
args = sys.argv[1:]
if args[0] == "-e":
    tasks = int(args[-1])
    cap = int(os.environ.get("NIPAT_MAX_WORKERS") or tasks)
    print(json.dumps({"mode":"auto", "max_workers":cap, "workers":min(tasks,cap),
                      "tasks":tasks,"reason":"controlled-test-budget"}))
    raise SystemExit(0)
work = pathlib.Path.cwd()
(work / "observed-environment.json").write_text(json.dumps(dict(os.environ)))
mode = os.environ.get("SNP_FIXTURE_MODE", "normal")
if mode != "normal":
    child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(120)"])
    (work / "descendant.pid").write_text(str(child.pid))
    if mode == "fail" and "snp0" in str(work):
        time.sleep(.4)
        raise SystemExit(17)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(120)
time.sleep(.25)
out = pathlib.Path(args[args.index("--out")+1])
out.write_text("chr\tpos\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\tratio\tGL0\tGL1\tGL2\tGT\treads_discarded_for_indels\tratio_reads_discarded_for_indels\tcombined_bases\tcombined_counts\n"
               "chr1\t10\tA\tG\t1\t1\t0\t2\t0.5\t-9.21\t-1.386\t-9.21\t0/1\t0\t0\tA-G\t1-1\n")
summary = out.parent / "summary"
summary.mkdir()
(summary / "SNPcall_AllGenotypes.txt").write_text("chr\tpos\tREF\tALT\tGT_sample_0001\nchr1\t10\tA\tG\t0/1\n")
(summary / "resources.tsv").write_text("sample\tseconds\tresident_MB_start\tresident_MB_end\nsample_0001\t1\t10\t11\n")
(summary / "Unassigned_genotypes.pdf").write_bytes(b"%PDF-fixture\n")
plots = out.parent / "plots/sample_0001"
plots.mkdir(parents=True)
for name in ("N_genotypes", "Ref_read_count", "Alt_read_count", "Other_read_count"):
    (plots / f"sample_0001_{name}.pdf").write_bytes(b"%PDF-fixture\n")
'''


@unittest.skipUnless(os.name == "posix", "Scientific batch execution runs inside Linux")
class SnpParallelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nipat-snp-batch-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        executable = self.bin / "Rscript"
        executable.write_text(f"#!{sys.executable}\n" + textwrap.dedent(FAKE_R), encoding="utf-8")
        executable.chmod(0o755)
        self.script = self.root / "SNPcall.R"
        self.script.write_text("# fixture executable is supplied by PATH\n")
        panel = self.root / "panel.tsv"
        panel.write_text("chr\tpos\tref\talt\nchr1\t10\tA\tG\n")
        self.plan = {"schema_version": 1, "samples": [], "steps": []}
        for index in range(3):
            pileup = self.root / f"sample{index}.pileup"
            pileup.write_text("chr1\t10\tA\t2\t.G\tII\tread1,read2\n")
            self.plan["samples"].append({"id": f"sample{index}", "kind": "snp-pileup", "path": str(pileup)})
            self.plan["steps"].append({"id": f"snp{index}", "workflow": "snp-call",
                "inputs": {"sample": f"sample{index}", "panel": str(panel), "reference": None},
                "parameters": {"mode": "pileup"}})
        self.environment = {"PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                            "NIPAT_PARALLEL_CHILD": "", "NIPAT_EXECUTION_MODE": "auto", "NIPAT_MAX_WORKERS": ""}

    def execute(self, run, **environment):
        with patch.dict(os.environ, {**self.environment, **environment}), \
                patch("nipat_scientific.snp_summary.finalize_snp_summaries", return_value=[]):
            return execute_plan(self.plan, run_dir=run, script_paths={"snp-call": self.script})

    def table_values(self, state, run):
        return {record["id"]: (run / record["artifacts"]["snp-tables"][0]["path"]).read_bytes()
                for record in state["steps"]}

    def test_three_samples_auto_and_manual_two_equal_serial_without_nested_workers(self):
        serial_dir = self.root / "serial"
        serial = self.execute(serial_dir, NIPAT_EXECUTION_MODE="serial")
        self.assertEqual(serial["status"], "succeeded", serial)
        expected = self.table_values(serial, serial_dir)
        self.assertFalse((serial_dir / "parallel/snp").exists())
        for mode, cap, expected_workers in (("auto", "", 3), ("manual", "2", 2)):
            run = self.root / mode
            state = self.execute(run, NIPAT_MAX_WORKERS=cap)
            self.assertEqual(state["status"], "succeeded", state)
            self.assertEqual(expected, self.table_values(state, run))
            self.assertEqual(state, json.loads((run / "workflow-state.json").read_text()))
            self.assertEqual(state["snp_parallel"]["workers"], expected_workers)
            events = [json.loads(line) for file in (run / "parallel/snp").glob("worker-*.jsonl")
                      for line in file.read_text().splitlines()]
            intervals = sorted((row["observed_at_unix"], 1 if row["event"] == "task-start" else -1)
                               for row in events if row["event"] in {"task-start", "task-end"})
            active = maximum = 0
            for _timestamp, change in intervals:
                active += change
                maximum = max(maximum, active)
            self.assertEqual(active, 0)
            self.assertEqual(maximum, expected_workers)
            for record in state["steps"]:
                observed = json.loads((run / record["work_dir"] / "observed-environment.json").read_text())
                self.assertEqual(observed["NIPAT_PARALLEL_CHILD"], "1")
                self.assertEqual(observed["NIPAT_MAX_WORKERS"], "1")
                self.assertTrue(all(observed[key] == "1" for key in THREAD_LIMITS))
                worker_state = json.loads((run / "parallel/snp" / f"state-{record['id']}.json").read_text())
                self.assertEqual(record, worker_state)

    def test_ineligible_plans_never_query_a_budget_or_launch_workers(self):
        scenarios = [({"NIPAT_EXECUTION_MODE": "serial"}, self.plan),
                     ({"NIPAT_MAX_WORKERS": "1"}, self.plan),
                     ({"NIPAT_PARALLEL_CHILD": "1"}, self.plan),
                     ({}, {"steps": self.plan["steps"][:1]}),
                     ({}, {"steps": [{"workflow": "cpi"}, *self.plan["steps"]]})]
        with patch("nipat_scientific.snp_parallel._query_budget") as budget:
            for environment, plan in scenarios:
                with self.subTest(environment=environment, plan=plan), patch.dict(os.environ, {**self.environment, **environment}):
                    self.assertFalse(execute_independent_snp_steps(plan, {}, self.root / "unused", {}, _Cancellation(),
                                     atomic_json=_atomic_json))
            budget.assert_not_called()

    def test_state_replacement_during_worker_execution_cannot_abort_the_batch(self):
        # A host-mounted filesystem need not let the coordinator open a record
        # while its worker is replacing it. Model that condition at the read
        # boundary, with real worker processes and independently checked tables.
        original_popen = subprocess.Popen
        original_read = Path.read_text
        workers = {}

        def start(command, *args, **kwargs):
            process = original_popen(command, *args, **kwargs)
            if "--worker" in command:
                identifier = Path(command[-1]).stem.removeprefix("job-")
                workers[f"state-{identifier}.json"] = process
            return process

        def read(path, *args, **kwargs):
            process = workers.get(path.name)
            if process is not None and process.poll() is None:
                raise PermissionError(errno.EACCES, "record is being replaced", str(path))
            return original_read(path, *args, **kwargs)

        run = self.root / "concurrent-replacement"
        with patch("nipat_scientific.snp_parallel.subprocess.Popen", side_effect=start), \
                patch.object(Path, "read_text", read):
            state = self.execute(run)
        self.assertEqual(state["status"], "succeeded", state)
        self.assertEqual(len(self.table_values(state, run)), 3)
        self.assertTrue(all(process.poll() == 0 for process in workers.values()))

    def test_final_state_visibility_recovers_without_restarting_workers(self):
        original_read = Path.read_text
        failures = {}

        def read(path, *args, **kwargs):
            if path.name.startswith("state-snp"):
                attempt = failures.get(path.name, 0)
                failures[path.name] = attempt + 1
                if attempt == 0:
                    raise FileNotFoundError(errno.ENOENT, "record temporarily unavailable", str(path))
                if attempt == 1:
                    return ""  # temporarily incomplete content must not be merged
            return original_read(path, *args, **kwargs)

        run = self.root / "delayed-visibility"
        with patch.object(Path, "read_text", read):
            state = self.execute(run)
        self.assertEqual(state["status"], "succeeded", state)
        self.assertEqual(len(self.table_values(state, run)), 3)
        self.assertEqual(len(list((run / "parallel/snp").glob("job-*.json"))), 3)
        self.assertEqual(set(failures), {"state-snp0.json", "state-snp1.json", "state-snp2.json"})

    def test_unreadable_final_state_fails_with_details_and_preserves_cleanup(self):
        original_read = Path.read_text
        for failure in ("missing", "malformed", "wrong-identity"):
            with self.subTest(failure=failure):
                def read(path, *args, **kwargs):
                    if path.name == "state-snp0.json":
                        if failure == "missing":
                            raise FileNotFoundError(errno.ENOENT, "record never became readable", str(path))
                        if failure == "malformed":
                            return "{broken"
                        record = json.loads(original_read(path, *args, **kwargs))
                        record["id"] = "another-sample"
                        return json.dumps(record)
                    return original_read(path, *args, **kwargs)

                run = self.root / failure
                with patch.object(Path, "read_text", read):
                    state = self.execute(run, NIPAT_MAX_WORKERS="2")
                self.assertEqual(state["status"], "failed", state)
                self.assertEqual(state["error"]["code"], "execution.worker_state")
                self.assertIn("state-snp0.json", state["error"]["message"])
                if failure != "wrong-identity":
                    self.assertIn("FileNotFoundError" if failure == "missing" else "JSONDecodeError",
                                  state["error"]["message"])
                self.assertEqual(state, json.loads((run / "workflow-state.json").read_text()))
                self.assertTrue(all(item["status"] not in {"pending", "running"}
                                    for item in state["steps"]))
                self.assertFalse((run / "snp_summary").exists())

    def test_insufficient_shared_budget_falls_back_to_serial_execution(self):
        run = self.root / "limited"
        with patch("nipat_scientific.snp_parallel._query_budget", return_value={"workers": 1, "tasks": 3, "reason": "memory"}):
            state = self.execute(run)
        self.assertEqual(state["status"], "succeeded", state)
        self.assertFalse(list((run / "parallel/snp").glob("job-*.json")))

    def assert_descendants_stopped(self, run):
        descendants = [int(file.read_text()) for file in run.rglob("descendant.pid")]
        self.assertGreaterEqual(len(descendants), 1)
        for pid in descendants:
            # A killed child can briefly remain a zombie until the host reaps it.
            status = Path(f"/proc/{pid}/stat")
            deadline = time.monotonic() + 3
            while status.exists() and status.read_text().split()[2] != "Z" and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(not status.exists() or status.read_text().split()[2] == "Z", f"Live orphan {pid}")

    def test_failure_stops_running_siblings_and_does_not_start_pending_sample(self):
        run = self.root / "failed"
        state = self.execute(run, NIPAT_MAX_WORKERS="2", SNP_FIXTURE_MODE="fail")
        self.assertEqual(state["status"], "failed", state)
        self.assertEqual(state["exit_code"], 17)
        self.assertEqual(state["steps"][0]["status"], "failed")
        self.assertEqual(state["steps"][0]["exit_code"], 17)
        self.assertEqual(state["steps"][1]["status"], "cancelled")
        self.assertEqual(state["steps"][2]["status"], "blocked")
        self.assertFalse((run / "steps/snp2").exists())
        self.assert_descendants_stopped(run)

    def test_cleanup_read_error_preserves_original_worker_failure_and_stops_siblings(self):
        original_read = Path.read_text

        def read(path, *args, **kwargs):
            if path.name == "state-snp1.json":
                raise PermissionError(errno.EACCES, "cancelled sibling state unavailable", str(path))
            return original_read(path, *args, **kwargs)

        run = self.root / "failed-with-unreadable-sibling"
        with patch.object(Path, "read_text", read):
            state = self.execute(run, NIPAT_MAX_WORKERS="2", SNP_FIXTURE_MODE="fail")
        self.assertEqual(state["status"], "failed", state)
        self.assertEqual(state["exit_code"], 17)
        self.assertEqual(state["error"]["code"], "execution.process")
        self.assertEqual([item["status"] for item in state["steps"]], ["failed", "cancelled", "blocked"])
        diagnostic = state["steps"][1]["state_read_error"]
        self.assertEqual(diagnostic["code"], "execution.worker_state")
        self.assertIn("PermissionError", diagnostic["message"])
        self.assertEqual(state, json.loads((run / "workflow-state.json").read_text()))
        self.assertFalse((run / "steps/snp2").exists())
        self.assert_descendants_stopped(run)

    def test_cancellation_persists_state_and_kills_stubborn_grandchildren(self):
        run = self.root / "cancelled"
        config = self.root / "config.json"
        config.write_text(json.dumps({"plan": self.plan, "run": str(run), "script": str(self.script)}))
        code = ("import json,sys; from pathlib import Path; from unittest.mock import patch; "
                "from nipat_scientific.executor import execute_plan; c=json.load(open(sys.argv[1])); "
                "p=patch('nipat_scientific.snp_summary.finalize_snp_summaries',return_value=[]); p.start(); "
                "execute_plan(c['plan'],run_dir=Path(c['run']),script_paths={'snp-call':Path(c['script'])})")
        environment = {**os.environ, **self.environment, "NIPAT_MAX_WORKERS": "2", "SNP_FIXTURE_MODE": "cancel"}
        with (self.root / "coordinator.log").open("wb") as log:
            coordinator = subprocess.Popen([sys.executable, "-c", code, str(config)], env=environment, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 10
                while len(list(run.rglob("descendant.pid"))) < 2 and coordinator.poll() is None and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertEqual(len(list(run.rglob("descendant.pid"))), 2)
                coordinator.send_signal(signal.SIGTERM)
                coordinator.wait(timeout=10)
            finally:
                if coordinator.poll() is None:
                    coordinator.kill()
                    coordinator.wait()
        state = json.loads((run / "workflow-state.json").read_text())
        self.assertEqual(state["status"], "cancelled", state)
        self.assertEqual(state["exit_code"], 143)
        self.assertEqual([item["status"] for item in state["steps"]], ["cancelled", "cancelled", "blocked"])
        self.assert_descendants_stopped(run)


if __name__ == "__main__":
    unittest.main()
