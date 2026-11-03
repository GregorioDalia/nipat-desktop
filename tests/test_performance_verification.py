"""The real-container check must reject missing or inconsistent measurement evidence."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("verify_performance", SCRIPTS / "verify_performance.py")
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class PerformanceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    def engine(self, *, cgroup=None, status="complete"):
        directory = self.root / "performance/engine"
        sample = {"cgroup": cgroup or {"version": 2, "memory_current_bytes": 4096,
                                      "cpu": {"usage_usec": 125}}, "elapsed_seconds": 0.01}
        self.write(directory / "samples.jsonl", sample)
        phases = [{"phase": phase, "event": "end", "duration_seconds": 0.1} for phase in
                  ("preparation", "r-execution", "output-validation", "presentation-finalization")]
        (directory / "phases.jsonl").write_text("".join(json.dumps(row) + "\n" for row in phases),
                                                 encoding="utf-8")
        self.write(directory / "summary.json", {
            "interface": "performance-diagnostics-v1", "status": status,
            "samples": 1, "phase_events": len(phases), "errors": [], "truncated": [],
        })
        return directory

    def external(self, *, samples=None, status="completed", count=None):
        samples = [] if samples is None else samples
        self.write(self.root / "performance/summary.json", {
            "source": "docker-cli-stats", "status": status, "reason": "test",
            "sample_count": len(samples) if count is None else count, "container_id": "a" * 64,
        })
        (self.root / "performance/container-samples.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in samples), encoding="utf-8")

    def test_kernel_high_water_mark_is_optional_without_inventing_a_peak(self):
        self.engine()
        result = verification.check_engine_evidence(self.root)
        self.assertEqual(result["samples"], 1)
        self.assertTrue(result["memory_observed"])
        self.assertTrue(result["cpu_observed"])

    def test_cgroup_v1_cpu_counter_is_an_accepted_alternative(self):
        self.engine(cgroup={"version": 1, "memory_current_bytes": 4096, "cpu_usage_ns": 125000})
        self.assertEqual(verification.check_engine_evidence(self.root)["cgroup_versions"], [1])

    def test_successful_scientific_run_does_not_hide_incomplete_diagnostics(self):
        self.engine(status="incomplete")
        with self.assertRaisesRegex(ValueError, "did not complete"):
            verification.check_engine_evidence(self.root)

    def test_missing_cpu_cannot_pass_as_measured_zero(self):
        self.engine(cgroup={"version": 2, "memory_current_bytes": 4096, "cpu": None})
        with self.assertRaisesRegex(ValueError, "No actual cgroup CPU"):
            verification.check_engine_evidence(self.root)

    def test_missing_memory_cannot_pass_as_measured_zero(self):
        self.engine(cgroup={"version": 2, "memory_current_bytes": None, "cpu": {"usage_usec": 125}})
        with self.assertRaisesRegex(ValueError, "No actual cgroup memory"):
            verification.check_engine_evidence(self.root)

    def test_lost_phase_events_are_rejected(self):
        directory = self.engine()
        (directory / "phases.jsonl").write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "consistent evidence"):
            verification.check_engine_evidence(self.root)

    def test_short_run_may_have_no_external_sample_but_must_say_unavailable(self):
        self.external(status="unavailable")
        self.assertEqual(verification.check_external_evidence(self.root)["sample_count"], 0)
        with self.assertRaisesRegex(ValueError, "no external samples"):
            verification.check_external_evidence(self.root, require_samples=True)
        self.external(status="completed")
        with self.assertRaisesRegex(ValueError, "not explicitly reported"):
            verification.check_external_evidence(self.root)

    def test_stale_summary_cannot_hide_lost_external_samples(self):
        self.external(samples=[{"cpu_percent": 10, "memory_cache_adjusted_bytes": 4096}], count=2)
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            verification.check_external_evidence(self.root)

    def test_oom_retained_partial_observations_are_accepted(self):
        self.external(samples=[{"cpu_percent": 10, "memory_cache_adjusted_bytes": 4096}], status="partial")
        self.assertEqual(verification.check_external_evidence(self.root, require_samples=True)["status"],
                         "partial")


if __name__ == "__main__":
    unittest.main()
