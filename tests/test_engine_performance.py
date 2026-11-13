from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nipat_scientific import performance


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("engine_performance_test", ROOT / "engine/main.py")
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


class EnginePerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nipat-performance-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.cgroup = self.root / "cgroup"
        self.proc = self.root / "proc"
        self.cgroup.mkdir()
        (self.proc / "self").mkdir(parents=True)
        self.addCleanup(setattr, performance, "_ACTIVE", None)

    def membership(self, *, value="0::/\n", mounts=None):
        (self.proc / "self/cgroup").write_text(value)
        (self.proc / "self/mountinfo").write_text(mounts or
            "31 22 0:27 / /sys/fs/cgroup ro - cgroup2 cgroup rw\n")

    def metric(self, name, value, directory=None):
        path = (directory or self.cgroup) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value))

    def session(self, name="evidence", **kwargs):
        return performance.PerformanceSession(self.root / name, interval=3600,
            cgroup_root=self.cgroup, proc_root=self.proc, **kwargs)

    def test_cgroup_v2_reads_own_subtree_in_host_namespace(self):
        self.membership(value="0::/docker/analysis\n")
        self.metric("memory.current", "999999")
        nested = self.cgroup / "docker/analysis"
        self.metric("memory.current", "1234", nested)
        self.metric("memory.peak", "4321", nested)
        self.metric("memory.max", "max", nested)
        self.metric("cpu.stat", "usage_usec 2000\nuser_usec 1200\nsystem_usec 800\nnr_throttled 2\n", nested)
        self.metric("memory.events", "oom 1\noom_kill 1\n", nested)
        self.metric("io.stat", "8:0 rbytes=8192 wbytes=4096 rios=2 wios=1\n", nested)
        observed = performance.cgroup_sample(self.cgroup, self.proc)
        self.assertEqual(observed["memory_current_bytes"], 1234)
        self.assertEqual(observed["memory_peak_bytes"], 4321)
        self.assertEqual(observed["memory_limit"], "unlimited")
        self.assertEqual(observed["cpu"]["usage_usec"], 2000)
        self.assertEqual(observed["memory_events"]["oom_kill"], 1)
        self.assertEqual(observed["io_devices"][0]["rbytes"], 8192)
        self.assertIn("memory.stat", observed["unavailable"])

    def test_cgroup_private_namespace_mount_root(self):
        self.membership()
        self.metric("memory.current", "20")
        sample = performance.cgroup_sample(self.cgroup, self.proc)
        self.assertTrue(sample["available"])
        self.assertEqual(sample["memory_current_bytes"], 20)
        self.assertIsNone(sample["memory_peak_bytes"])

    def test_missing_membership_never_falls_back_to_host_root(self):
        self.metric("memory.current", "999999")
        observed = performance.cgroup_sample(self.cgroup, self.proc)
        self.assertFalse(observed["available"])
        self.assertNotIn("memory_current_bytes", observed)

    def test_mismatching_mount_and_traversal_are_unavailable(self):
        for membership in ("0::/elsewhere\n", "0::/docker/../../escape\n"):
            with self.subTest(membership=membership):
                self.membership(value=membership, mounts=
                    "31 22 0:27 /docker/analysis /sys/fs/cgroup ro - cgroup2 cgroup rw\n")
                self.assertFalse(performance.cgroup_sample(self.cgroup, self.proc)["available"])

    def test_cgroup_v1_combined_controller_mounts(self):
        self.membership(value="7:memory:/analysis\n6:cpu,cpuacct:/analysis\n", mounts=
            "31 22 0:27 / /sys/fs/cgroup/memory ro - cgroup cgroup rw,memory\n"
            "32 22 0:28 / /sys/fs/cgroup/cpu,cpuacct ro - cgroup cgroup rw,cpu,cpuacct\n")
        self.metric("memory/analysis/memory.usage_in_bytes", "100")
        self.metric("memory/analysis/memory.max_usage_in_bytes", "200")
        self.metric("cpu,cpuacct/analysis/cpuacct.usage", "300")
        observed = performance.cgroup_sample(self.cgroup, self.proc)
        self.assertEqual(observed["version"], 1)
        self.assertEqual(observed["memory_current_bytes"], 100)
        self.assertEqual(observed["memory_peak_bytes"], 200)
        self.assertEqual(observed["cpu_usage_ns"], 300)
        self.assertIsNone(observed["io_devices"])

    def test_proc_records_only_allowed_names_and_no_arguments(self):
        for pid, name in ((11, "R"), (12, "samtools"), (13, "private-patient")):
            directory = self.proc / str(pid)
            directory.mkdir()
            fields = ["S", "1", *(["0"] * 18)]
            fields[11], fields[12], fields[19] = "123", "45", "678"
            (directory / "comm").write_text(name)
            (directory / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))
            (directory / "status").write_text("VmRSS:\t42 kB\n")
            (directory / "io").write_text("read_bytes: 12\nwrite_bytes: 24\n")
            (directory / "cmdline").write_text("secret sample path.bam")
        sample = performance.process_sample(self.proc)
        self.assertEqual([item["name"] for item in sample["processes"]], ["R", "samtools"])
        self.assertEqual(sample["processes"][0]["rss_bytes"], 42 * 1024)
        self.assertEqual(sample["processes"][0]["user_cpu_ticks"], 123)
        self.assertNotIn("secret", json.dumps(sample))
        self.assertNotIn("private-patient", json.dumps(sample))
        self.assertNotIn("total_rss", sample)

    def test_disabled_session_has_no_sampling_or_artifacts(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(performance, "cgroup_sample") as sample:
            self.assertIsNone(performance.PerformanceSession.from_environment())
            with performance.phase("r-execution"):
                pass
            sample.assert_not_called()
        self.assertFalse((self.root / "evidence").exists())

    def test_incomplete_evidence_is_flushed_before_stop_and_phase_errors_propagate(self):
        self.membership()
        self.metric("memory.current", "123")
        self.metric("memory.peak", "456")
        session = self.session()
        session.start()
        self.addCleanup(session.stop)
        self.assertEqual(json.loads((session.directory / "summary.json").read_text())["status"], "incomplete")
        self.assertEqual(len((session.directory / "samples.jsonl").read_text().splitlines()), 1)
        with self.assertRaises(KeyboardInterrupt):
            with performance.phase("r-execution", workflow="dnp-call", step="dnp"):
                raise KeyboardInterrupt
        session.stop()
        summary = json.loads((session.directory / "summary.json").read_text())
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["sampled_memory_max_bytes"], 123)
        self.assertEqual(summary["observed_kernel_memory_peak_bytes"], 456)
        phases = [json.loads(line) for line in (session.directory / "phases.jsonl").read_text().splitlines()]
        self.assertEqual([item["event"] for item in phases], ["start", "end"])
        self.assertEqual(phases[-1]["outcome"], "raised")
        self.assertGreaterEqual(phases[-1]["duration_seconds"], 0)
        self.assertFalse(session.thread.is_alive())

    def test_missing_metrics_and_limits_are_explicit(self):
        session = self.session(max_sample_bytes=1, max_phase_bytes=1)
        session.start()
        with performance.phase("r-execution"):
            pass
        session.stop()
        summary = json.loads((session.directory / "summary.json").read_text())
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(set(summary["truncated"]), {"samples", "phases"})
        self.assertIsNone(summary["sampled_memory_max_bytes"])
        self.assertLessEqual((session.directory / "samples.jsonl").stat().st_size, 1)
        self.assertLessEqual((session.directory / "phases.jsonl").stat().st_size, 1)

    def test_existing_destination_is_not_overwritten_and_failure_is_nonfatal(self):
        existing = self.root / "evidence"
        existing.mkdir()
        sentinel = existing / "summary.json"
        sentinel.write_text("previous evidence")
        session = self.session()
        with contextlib.redirect_stderr(io.StringIO()):
            session.start()
            with performance.phase("r-execution"):
                pass
            session.stop()
        self.assertEqual(sentinel.read_text(), "previous evidence")
        self.assertEqual(session.summary["status"], "unavailable")
        self.assertIsNone(performance._ACTIVE)

    def test_symlink_destination_parent_is_rejected(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "linked"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        session = performance.PerformanceSession(link / "evidence")
        with contextlib.redirect_stderr(io.StringIO()):
            session.start()
            session.stop()
        self.assertFalse((real / "evidence").exists())

    def test_sampling_error_does_not_replace_scientific_execution(self):
        session = self.session()
        with patch.object(performance, "cgroup_sample", side_effect=OSError("disk issue")):
            session.start()
            with performance.phase("r-execution"):
                scientific_result = 17
            session.stop()
        self.assertEqual(scientific_result, 17)
        summary = json.loads((session.directory / "summary.json").read_text())
        self.assertEqual(summary["status"], "partial")
        self.assertIn("OSError", summary["errors"])

    def test_summary_write_failure_closes_observer_files_without_raising(self):
        session = self.session()
        session.start()
        handles = list(session.handles.values())
        with patch.object(session, "_save_summary", side_effect=OSError("full disk")), \
                contextlib.redirect_stderr(io.StringIO()):
            session.stop()
        self.assertTrue(all(handle.closed for handle in handles))
        self.assertFalse(session.thread.is_alive())
        self.assertEqual(json.loads((session.directory / "summary.json").read_text())["status"], "incomplete")

    def test_thread_start_failure_leaves_unavailable_summary(self):
        session = self.session()
        with patch.object(performance.threading.Thread, "start", side_effect=RuntimeError("thread unavailable")), \
                contextlib.redirect_stderr(io.StringIO()):
            session.start()
            session.stop()
        summary = json.loads((session.directory / "summary.json").read_text())
        self.assertEqual(summary["status"], "unavailable")
        self.assertIsNone(performance._ACTIVE)

    def test_engine_execute_keeps_native_command_and_return_code_with_diagnostics(self):
        request = self.root / "request.json"
        request.write_text(json.dumps({"workflow": "contamination", "marker_type": "DNP", "work_dir": str(self.root / "work"),
                                       "out_dir": str(self.root / "output")}))
        recorded = []
        for enabled in (False, True):
            environment = {"NIPAT_PERFORMANCE_DIR": str(self.root / "enabled")} if enabled else {}
            with patch.dict(os.environ, environment, clear=True), \
                    patch("nipat_scientific.contamination.prepare_contamination", return_value=["panel", "inputs", "outputs"]), \
                    patch("nipat_scientific.presentation.prepare_presentation", return_value=["Rscript", "science.R", "panel", "inputs", "outputs"]), \
                    patch("nipat_scientific.executor._run_process", return_value=23) as run:
                code = engine.main(["execute", "contamination", "--request", str(request)])
                recorded.append((code, run.call_args.args[:3]))
        self.assertEqual(recorded[0], recorded[1])
        self.assertEqual(recorded[1][0], 23)
        summary = json.loads((self.root / "enabled/summary.json").read_text())
        self.assertGreaterEqual(summary["samples"], 1)
        phases = [json.loads(line) for line in (self.root / "enabled/phases.jsonl").read_text().splitlines()]
        self.assertIn("preparation", {item["phase"] for item in phases})
        self.assertIn("r-execution", {item["phase"] for item in phases})
        self.assertNotIn("output-validation", {item["phase"] for item in phases})


if __name__ == "__main__":
    unittest.main()
