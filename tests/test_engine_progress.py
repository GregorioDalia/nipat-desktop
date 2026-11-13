"""Progress boundaries remain available without a performance observer."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nipat_scientific import progress


class EngineProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "progress"
        self.env = patch.dict(os.environ, {"NIPAT_PROGRESS_DIR": str(self.root)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def events(self):
        return [json.loads(line) for path in self.root.glob("*.jsonl")
                for line in path.read_text().splitlines()]

    def test_context_and_exact_counter_without_diagnostics(self):
        with progress.context("dnp-call", step_id="dnp", sample_ids=["sample_0001"]):
            with progress.phase("dnp-processing"):
                progress.emit("progress", "dnp-processing", completed=3, total=7, unit="loci")
        events = self.events()
        self.assertEqual([x["event"] for x in events], ["start", "progress", "end"])
        self.assertEqual([x["sequence"] for x in events], [1, 2, 3])
        self.assertEqual(events[1]["completed"], 3)
        self.assertEqual(events[1]["total"], 7)
        self.assertEqual(events[1]["sample_ids"], ["sample_0001"])
        self.assertTrue(all(progress.validate_event(x) for x in events))
        self.assertNotIn("percentage", events[1])
        self.assertNotIn("eta", events[1])

    def test_cancellation_and_nonzero_result_outcomes(self):
        with progress.context("snp-call"):
            with self.assertRaises(KeyboardInterrupt), progress.phase("pileup"):
                raise KeyboardInterrupt
            with progress.phase("r-execution") as state:
                state["outcome"] = "failed"
        self.assertEqual([x["outcome"] for x in self.events() if x["event"] == "end"],
                         ["cancelled", "failed"])

    def test_disabled_unavailable_and_malformed_never_affect_science(self):
        with patch.dict(os.environ, {"NIPAT_PROGRESS_DIR": ""}):
            with progress.phase("r-execution"):
                pass
        self.assertFalse(self.root.exists())
        self.root.write_text("not a directory")
        with progress.context("dnp-call"), progress.phase("r-execution"):
            progress.emit("progress", "loci", completed=2, total=1, unit="loci")
        self.assertEqual(self.root.read_text(), "not a directory")

    def test_native_aliases_map_to_original_plan_sample_identities(self):
        with progress.context("dnp-call", step_id="dnp", sample_ids=["donor_b"],
                              sample_map={"sample_0001": "donor_b"}):
            progress.emit("start", "dnp-indexed-pileup", sample_ids=["sample_0001"])
        self.assertEqual(self.events()[0]["sample_ids"], ["donor_b"])

    def test_context_restores_environment_and_unique_invocations(self):
        before = dict(os.environ)
        for _ in range(2):
            with progress.context("dnp-call", step_id="same"):
                progress.emit("start", "r-execution")
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(len(list(self.root.glob("*.jsonl"))), 2)

    def test_file_limit_and_symlink_are_nonfatal(self):
        with patch.object(progress, "MAX_FILE_BYTES", 100), progress.context("dnp-call"):
            progress.emit("start", "r-execution")
        self.assertFalse(self.root.exists())
        real = Path(self.tmp.name) / "real"
        real.mkdir()
        try:
            self.root.symlink_to(real, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symbolic links is unavailable on this platform")
        with progress.context("dnp-call"):
            progress.emit("start", "r-execution")
        self.assertEqual(list(real.iterdir()), [])

    def test_validator_rejects_control_text_partial_counters_and_bool_counts(self):
        with progress.context("dnp-call"):
            progress.emit("start", "r-execution")
        event = self.events()[0]
        for changed in ({"completed": 1}, {"completed": True, "total": 3, "unit": "loci"},
                        {"sample_ids": ["evil\x1b[2J"]}, {"sequence": 0},
                        {"event": "end"}, {"eta": 30}):
            with self.subTest(changed=changed):
                self.assertFalse(progress.validate_event(event | changed))


class StandaloneProgressTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        module = Path(__file__).resolve().parents[1] / "engine" / "main.py"
        spec = importlib.util.spec_from_file_location("progress_test_engine", module)
        self.engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.engine)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.events_dir = self.root / "progress"
        self.enterContext(patch.dict(os.environ, {"NIPAT_PROGRESS_DIR": str(self.events_dir),
                                                 "NIPAT_PERFORMANCE_DIR": ""}))
        self.enterContext(patch.object(self.engine, "verify_bundle", return_value={"workflows": {
            name: {"script": name + ".R"} for name in self.engine.SCRIPT_PATHS}}))
        self.enterContext(patch.object(self.engine, "preparation_root", return_value=self.root))
        # main temporarily prepends the bundled library to Python's import path.
        import sys
        self.enterContext(patch.object(sys, "path", list(sys.path)))
        from contextlib import redirect_stdout, redirect_stderr
        import io
        self.enterContext(redirect_stdout(io.StringIO()))
        self.errors = io.StringIO()
        self.enterContext(redirect_stderr(self.errors))

    def events(self):
        return [json.loads(line) for path in self.events_dir.glob("*.jsonl")
                for line in path.read_text().splitlines()]

    def test_all_standalone_workflows_enter_request_sample_context(self):
        from types import SimpleNamespace
        for workflow, function in (("dnp-call", "dnp.prepare_dnp"), ("snp-call", "snp.prepare_snp"),
                                   ("contamination", "contamination.prepare_contamination"), ("cpi", "cpi.prepare_cpi"), ("cpin", "cpin.prepare_cpin")):
            with self.subTest(workflow=workflow):
                request = self.root / (workflow + ".json")
                request.write_text(json.dumps({"workflow": workflow, "marker_type": "DNP", "work_dir": str(self.root / workflow / "work"), "presentation": {
                    "samples": {"sample_0001": "original.bam"}}}))
                prepared = (SimpleNamespace(native_arguments=[], working_dir=Path.cwd(), preparation_command=None)
                            if workflow in {"snp-call", "dnp-call"} else [])
                def execute(*args):
                    self.assertEqual(os.environ["NIPAT_PROGRESS_WORKFLOW"], workflow)
                    self.assertEqual(json.loads(os.environ["NIPAT_PROGRESS_SAMPLE_IDS"]), ["sample_0001"])
                    return 0
                with patch("nipat_scientific." + function, return_value=prepared), \
                        patch.object(self.engine, "run_validated_request", side_effect=execute):
                    self.assertEqual(self.engine.main(["execute", workflow, "--request", str(request)]), 0)
        events = self.events()
        self.assertEqual({row["workflow"] for row in events}, set(self.engine.SCRIPT_PATHS))
        self.assertTrue(all(row["sample_ids"] == ["sample_0001"] for row in events))
        self.assertEqual(len(events), 10)

    def test_invalid_json_still_returns_engine_error_without_traceback(self):
        request = self.root / "invalid.json"
        request.write_text("{broken")
        self.assertEqual(self.engine.main(["execute", "dnp-call", "--request", str(request)]), 2)
        self.assertIn("NIPAT scientific engine:", self.errors.getvalue())
        self.assertEqual(self.events(), [])

    def test_r_nonzero_and_cancellation_events_match_real_exit_outcome(self):
        import signal
        request = {"workflow": "snp-call", "work_dir": str(self.root), "out_dir": str(self.root / "output")}
        for cancel, code in ((False, 17), (True, 0)):
            def process(command, cwd, log, cancellation):
                if cancel:
                    cancellation.receive(signal.SIGTERM, None)
                return code
            with progress.context("snp-call", sample_ids=["sample_0001"]), \
                    patch("nipat_scientific.presentation.prepare_presentation", return_value=[]), \
                    patch("nipat_scientific.executor._run_process", side_effect=process):
                result = self.engine.run_validated_request(request, Path("snp.R"), [])
                self.assertEqual(result, 143 if cancel else 17)
        ends = [row["outcome"] for row in self.events() if row["phase"] == "r-execution" and row["event"] == "end"]
        self.assertCountEqual(ends, ["failed", "cancelled"])
