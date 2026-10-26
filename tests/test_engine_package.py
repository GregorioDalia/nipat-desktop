from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "engine" / "main.py"
SPEC = importlib.util.spec_from_file_location("nipat_bundled_engine", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


class EnginePackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nipat engine ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "engine").mkdir()
        shutil.copyfile(MODULE_PATH, self.root / "engine" / "main.py")
        shutil.copytree(PROJECT_ROOT / "src" / "nipat_scientific",
                        self.root / "lib" / "nipat_scientific",
                        ignore=shutil.ignore_patterns("__pycache__"))
        scientific = self.root / "scientific"
        scientific.mkdir()
        lines = []
        for workflow, relative in engine.SCRIPT_PATHS.items():
            source = scientific / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            # The relocated bundle carries the actual reviewed sources, so the
            # source-bound catalog can be checked without a desktop checkout.
            shutil.copyfile(PROJECT_ROOT / "scientific" / relative, source)
            lines.append(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {relative}\n")
        self.manifest = scientific / "SHA256SUMS"
        self.manifest.write_text("".join(lines), encoding="utf-8")

    def call_main(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(engine, "BUNDLE_ROOT", self.root):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = engine.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_describe_verifies_and_identifies_each_source(self):
        code, output, errors = self.call_main(["describe", "--json"])
        self.assertEqual(code, 0, errors)
        metadata = json.loads(output)
        self.assertEqual(metadata["schema_version"], 1)
        self.assertEqual(metadata["interface"], "native-r-v1")
        self.assertEqual(metadata["manifest"]["sha256"],
                         hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.assertEqual(set(metadata["workflows"]), set(engine.SCRIPT_PATHS))
        self.assertEqual(metadata["workflow_interfaces"], {
            "contamination": "contamination-v1", "snp-call": "snp-call-v1", "dnp-call": "dnp-call-v1",
            "cpi": "cpi-v1",
        })
        self.assertEqual(metadata["plan_execution"], {
            "interface": "workflow-plan-execution-v1", "schema_version": 1,
            "workflows": ["dnp-call", "contamination", "cpi"], "scheduling": "sequential", "resume": False,
        })
        self.assertEqual(metadata["preparation"]["interface"], "workflow-preparation-v1")
        hashes = metadata["preparation"]["file_sha256"]
        self.assertEqual(len(hashes), 16)
        self.assertIn("engine/main.py", hashes)
        self.assertIn("lib/nipat_scientific/contamination.py", hashes)
        self.assertIn("lib/nipat_scientific/snp.py", hashes)
        self.assertIn("lib/nipat_scientific/dnp.py", hashes)
        self.assertIn("lib/nipat_scientific/cpi.py", hashes)
        self.assertIn("lib/nipat_scientific/catalog.py", hashes)
        self.assertIn("lib/nipat_scientific/plan.py", hashes)
        self.assertIn("lib/nipat_scientific/executor.py", hashes)
        for workflow in engine.SCRIPT_PATHS:
            self.assertIn(f"lib/nipat_scientific/catalog_data/{workflow}.json", hashes)
        for relative, digest in hashes.items():
            self.assertEqual(hashlib.sha256((self.root / relative).read_bytes()).hexdigest(), digest)
        for workflow, relative in engine.SCRIPT_PATHS.items():
            actual = metadata["workflows"][workflow]
            self.assertEqual(actual["script"], f"scientific/{relative}")
            self.assertEqual(actual["sha256"],
                             hashlib.sha256((self.root / actual["script"]).read_bytes()).hexdigest())

    def test_modified_or_missing_script_prevents_execution(self):
        source = self.root / "scientific" / engine.SCRIPT_PATHS["cpi"]
        for condition in ("modified", "missing"):
            with self.subTest(condition=condition):
                if condition == "modified":
                    source.write_text("# unexpected change\n", encoding="utf-8")
                else:
                    source.unlink()
                with patch.object(engine.os, "execvp") as execute:
                    code, _, errors = self.call_main(["run", "snp-call", "--", "--help"])
                self.assertEqual(code, 2)
                self.assertIn(engine.SCRIPT_PATHS["cpi"], errors)
                execute.assert_not_called()

    def test_missing_manifest_prevents_execution(self):
        self.manifest.unlink()
        with patch.object(engine.os, "execvp") as execute:
            code, _, errors = self.call_main(["run", "cpi", "--", "--help"])
        self.assertEqual(code, 2)
        self.assertIn("Cannot read scientific manifest", errors)
        execute.assert_not_called()

    def test_incomplete_duplicate_and_invalid_manifests_are_rejected(self):
        original = self.manifest.read_text(encoding="utf-8")
        cases = {
            "empty": "",
            "missing": "".join(original.splitlines(keepends=True)[1:]),
            "duplicate": original + original.splitlines(keepends=True)[0],
            "invalid digest": original.replace(original[:64], "not-a-sha256", 1),
            "unexpected path": original + f"{'0' * 64}  ../outside.R\n",
        }
        for label, contents in cases.items():
            with self.subTest(case=label):
                self.manifest.write_text(contents, encoding="utf-8")
                with patch.object(engine.os, "execvp") as execute:
                    code, _, _ = self.call_main(["run", "cpi", "--", "--help"])
                self.assertEqual(code, 2)
                execute.assert_not_called()

    def test_script_symlink_cannot_escape_bundle(self):
        source = self.root / "scientific" / engine.SCRIPT_PATHS["cpi"]
        external = self.root / "outside.R"
        external.write_bytes(source.read_bytes())
        source.unlink()
        try:
            source.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("Creating symbolic links is unavailable on this platform.")
        with patch.object(engine.os, "execvp") as execute:
            code, _, errors = self.call_main(["run", "cpi", "--", "--help"])
        self.assertEqual(code, 2)
        self.assertIn("escapes its bundle", errors)
        execute.assert_not_called()

    def test_native_arguments_are_forwarded_without_a_shell(self):
        native = ["--pileup_dir", "/inputs/sample files", "--pairs", "A:A,B:B", "--literal=$(echo x)"]
        with patch.object(engine.os, "execvp", side_effect=SystemExit(37)) as execute:
            with self.assertRaises(SystemExit) as exited:
                self.call_main(["run", "cpi", "--", *native])
        self.assertEqual(exited.exception.code, 37)
        execute.assert_called_once_with("Rscript", [
            "Rscript", str(self.root / "scientific" / engine.SCRIPT_PATHS["cpi"]), *native,
        ])

    def test_missing_rscript_produces_a_clear_failure(self):
        with patch.object(engine.os, "execvp", side_effect=FileNotFoundError("Rscript")):
            code, _, errors = self.call_main(["run", "cpi"])
        self.assertEqual(code, 2)
        self.assertIn("Rscript", errors)

    def test_unknown_workflow_is_rejected_before_execution(self):
        with patch.object(engine.os, "execvp") as execute:
            with self.assertRaises(SystemExit) as exited:
                self.call_main(["run", "unknown"])
        self.assertEqual(exited.exception.code, 2)
        execute.assert_not_called()

    def test_bundle_location_does_not_depend_on_working_directory_or_pythonpath(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(self.root / "nonexistent host project")
        result = subprocess.run(
            [sys.executable, str(self.root / "engine" / "main.py"), "describe", "--json"],
            cwd=self.root / "engine", env=environment, capture_output=True, text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["interface"], "native-r-v1")

    def test_missing_bundled_preparation_module_does_not_fall_back_to_host(self):
        (self.root / "lib" / "nipat_scientific" / "contamination.py").unlink()
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        result = subprocess.run(
            [sys.executable, str(self.root / "engine" / "main.py"), "describe", "--json"],
            cwd=self.root, env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Cannot read preparation module: contamination.py", result.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX fixture exercises the in-image preparation entry point.")
    def test_relocated_execute_prepares_inputs_and_preserves_r_exit_code(self):
        inputs = self.root / "selected"
        inputs.mkdir()
        panel = inputs / "panel.txt"
        panel.write_text("pos2\tchr\tpos1\n101\tchr1\t100\n", encoding="utf-8")
        sample = inputs / "sample.tsv"
        sample.write_text("chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\n"
                          "chr1\t100\t101\t95\t5\t0\n", encoding="utf-8")
        results = self.root / "results"
        (results / "work").mkdir(parents=True)
        (results / "output").mkdir()
        request = results / "work" / "request.json"
        request.write_text(json.dumps({
            "schema_version": 1, "workflow": "contamination", "panel": str(panel),
            "samples": [{"path": str(sample), "name": "sample with spaces.txt"}],
            "work_dir": str(results / "work"), "out_dir": str(results / "output"),
        }), encoding="utf-8")
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        fake_rscript = fake_bin / "Rscript"
        fake_rscript.write_text(
            "#!/bin/sh\n"
            '[ "$#" -eq 4 ] || exit 99\n'
            '[ -f "$2" ] || exit 98\n'
            '[ -f "$3/sample with spaces.txt" ] || exit 97\n'
            '[ -d "$4" ] || exit 96\n'
            "exit 37\n", encoding="utf-8",
        )
        fake_rscript.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
        environment["PYTHONPATH"] = str(self.root / "absent application")
        result = subprocess.run(
            [sys.executable, str(self.root / "engine" / "main.py"), "execute",
             "contamination", "--request", str(request)], cwd=inputs, env=environment,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual((results / "work/inputs/sample with spaces.txt").read_bytes(),
                         sample.read_bytes())
        self.assertIn("DNP001\tchr1\t100\t101", (results / "work/DNPpanel.txt").read_text())

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture exercises container process replacement.")
    def test_process_replacement_preserves_rscript_exit_status_and_arguments(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        fake_rscript = fake_bin / "Rscript"
        fake_rscript.write_text(
            "#!/bin/sh\n"
            '[ "$#" -eq 3 ] || exit 99\n'
            '[ "$2" = "argument with spaces" ] || exit 98\n'
            '[ "$3" = "literal;value" ] || exit 97\n'
            "exit 37\n",
            encoding="utf-8",
        )
        fake_rscript.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
        result = subprocess.run(
            [sys.executable, str(self.root / "engine" / "main.py"), "run", "cpi", "--",
             "argument with spaces", "literal;value"],
            cwd=self.root, env=environment, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 37, result.stderr)

    def test_repository_scientific_manifest_matches_all_supported_workflows(self):
        metadata = engine.verify_bundle(PROJECT_ROOT)
        self.assertEqual(set(metadata["workflows"]), set(engine.SCRIPT_PATHS))

    def relocated_command(self, *arguments, extra_env=None):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        environment.update(extra_env or {})
        return subprocess.run(
            [sys.executable, str(self.root / "engine/main.py"), *arguments],
            cwd=self.root / "engine", env=environment, capture_output=True,
            text=True, check=False, timeout=15,
        )

    def test_relocated_catalog_matches_sources_without_desktop_or_checkout(self):
        self.assertFalse((self.root / "src").exists())
        self.assertFalse((self.root / "lib/nipat").exists())
        result = self.relocated_command("catalog", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        catalog = json.loads(result.stdout)
        self.assertEqual(catalog["interface"], "scientific-catalog-v1")
        self.assertEqual(set(catalog["workflows"]), set(engine.SCRIPT_PATHS))
        for workflow, relative in engine.SCRIPT_PATHS.items():
            self.assertEqual(
                catalog["workflows"][workflow]["source"]["sha256"],
                hashlib.sha256((self.root / "scientific" / relative).read_bytes()).hexdigest(),
            )
        selected = self.relocated_command("catalog", "cpi", "--json")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual(set(json.loads(selected.stdout)["workflows"]), {"cpi"})

    def test_catalog_json_preserves_unicode_on_an_ascii_output_stream(self):
        result = self.relocated_command("catalog", "--json",
                                        extra_env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.isascii())
        expected = {
            workflow: json.loads((self.root / "lib/nipat_scientific/catalog_data" /
                                  f"{workflow}.json").read_text(encoding="utf-8"))
            for workflow in engine.SCRIPT_PATHS
        }
        self.assertFalse(json.dumps(expected, ensure_ascii=False).isascii())
        self.assertEqual(json.loads(result.stdout)["workflows"], expected)

    def test_missing_catalog_never_falls_back_to_checkout(self):
        path = self.root / "lib/nipat_scientific/catalog_data/cpi.json"
        path.unlink()
        result = self.relocated_command("catalog", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cpi.json", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_catalog_rejects_changed_source_even_with_updated_scientific_manifest(self):
        relative = engine.SCRIPT_PATHS["cpi"]
        source = self.root / "scientific" / relative
        source.write_bytes(source.read_bytes() + b"\n# Changed after the catalog review.\n")
        lines = [
            f"{hashlib.sha256((self.root / 'scientific' / path).read_bytes()).hexdigest()}  {path}\n"
            for path in engine.SCRIPT_PATHS.values()
        ]
        self.manifest.write_text("".join(lines), encoding="utf-8")
        result = self.relocated_command("catalog", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")

    def test_relocated_plan_validation_does_not_create_outputs_or_require_input_files(self):
        plan = {
            "schema_version": 1,
            "samples": [{"id": "sample_a", "kind": "bam", "path": "/absent/sample_a.bam"}],
            "steps": [{"id": "dnp", "workflow": "dnp-call", "inputs": {
                "samples": ["sample_a"], "reference": "/absent/reference.fa",
                "panel": "/absent/dnp.tsv",
            }, "parameters": {"parallel": False}}],
        }
        plan_file = self.root / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        before = {path.relative_to(self.root) for path in self.root.rglob("*")}
        result = self.relocated_command("validate-plan", "--plan", str(plan_file))
        self.assertEqual(result.returncode, 0, result.stderr)
        validated = json.loads(result.stdout)
        self.assertEqual(validated["execution_order"], ["dnp"])
        self.assertEqual(validated["plan"], plan)
        # Imports may populate Python's bytecode cache, but validation creates
        # neither work directories nor scientific outputs.
        after = {path.relative_to(self.root) for path in self.root.rglob("*")
                 if "__pycache__" not in path.parts}
        self.assertEqual(after, {path for path in before if "__pycache__" not in path.parts})
        plan["steps"][0]["workflow"] = "arbitrary-command"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        invalid = self.relocated_command("validate-plan", "--plan", str(plan_file))
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(invalid.stdout, "")

    def test_execute_plan_dispatches_only_verified_bundled_scripts_and_exit_code(self):
        plan_file = self.root / "plan.json"
        document = {"schema_version": 1, "samples": [], "steps": []}
        plan_file.write_text(json.dumps(document), encoding="utf-8")
        run_dir = self.root / "new-workflow"
        report = {"status": "failed", "exit_code": 37}
        with patch("nipat_scientific.executor.execute_plan", return_value=report) as execute:
            code, output, errors = self.call_main([
                "execute-plan", "--plan", str(plan_file), "--run-dir", str(run_dir), "--json",
            ])
        self.assertEqual(code, 37, errors)
        self.assertEqual(json.loads(output), report)
        execute.assert_called_once_with(document, run_dir=run_dir, script_paths={
            name: self.root / "scientific" / engine.SCRIPT_PATHS[name]
            for name in ("dnp-call", "contamination", "cpi")
        })
        self.assertFalse(run_dir.exists())

    def test_execute_plan_default_output_is_a_short_status_and_report_location(self):
        plan_file = self.root / "plan.json"
        plan_file.write_text("{}", encoding="utf-8")
        run_dir = self.root / "new-workflow"
        with patch("nipat_scientific.executor.execute_plan", return_value={
            "status": "failed", "exit_code": 37, "error": "Scientific child failed.",
        }):
            code, output, errors = self.call_main([
                "execute-plan", "--plan", str(plan_file), "--run-dir", str(run_dir),
            ])
        self.assertEqual(code, 37)
        self.assertEqual(output.splitlines(), ["Workflow: failed", f"Report: {run_dir / 'workflow-state.json'}"])
        self.assertIn("Scientific child failed.", errors)

    def test_execute_plan_malformed_json_does_not_create_a_run(self):
        plan_file = self.root / "plan.json"
        plan_file.write_text("{not JSON}", encoding="utf-8")
        run_dir = self.root / "new-workflow"
        with patch("nipat_scientific.executor.execute_plan") as execute:
            code, output, errors = self.call_main([
                "execute-plan", "--plan", str(plan_file), "--run-dir", str(run_dir),
            ])
        self.assertEqual(code, 2)
        self.assertIn("NIPAT scientific engine:", errors)
        self.assertEqual(output, "")
        execute.assert_not_called()
        self.assertFalse(run_dir.exists())

    def test_modified_source_prevents_plan_execution(self):
        source = self.root / "scientific" / engine.SCRIPT_PATHS["dnp-call"]
        source.write_bytes(source.read_bytes() + b"\n# changed\n")
        with patch("nipat_scientific.executor.execute_plan") as execute:
            code, _, errors = self.call_main([
                "execute-plan", "--plan", str(self.root / "absent-plan.json"),
                "--run-dir", str(self.root / "new-workflow"),
            ])
        self.assertEqual(code, 2)
        self.assertIn("does not match its manifest", errors)
        execute.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX fixture exercises the scientific image process runner.")
    def test_relocated_execute_plan_retains_real_child_failure_without_host_sources(self):
        inputs = self.root / "plan-inputs"
        inputs.mkdir()
        panel = inputs / "panel.tsv"
        panel.write_text("chr\tpos1\tpos2\nchr1\t100\t101\n", encoding="utf-8")
        sample = inputs / "sample.tsv"
        sample.write_text("chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\n"
                          "chr1\t100\t101\t95\t5\t0\n", encoding="utf-8")
        plan = {
            "schema_version": 1,
            "samples": [{"id": "sample_a", "kind": "dnp-table", "path": str(sample)}],
            "steps": [{"id": "contamination", "workflow": "contamination", "inputs": {
                "samples": [{"sample": "sample_a"}], "panel": str(panel),
            }, "parameters": {}}],
        }
        plan_file = inputs / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        fake_rscript = fake_bin / "Rscript"
        fake_rscript.write_text("#!/bin/sh\necho retained-scientific-diagnostic\nexit 37\n", encoding="utf-8")
        fake_rscript.chmod(0o755)
        run_dir = self.root / "workflow-results"
        result = self.relocated_command(
            "execute-plan", "--plan", str(plan_file), "--run-dir", str(run_dir), "--json",
            extra_env={"PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                       "PYTHONPATH": str(self.root / "absent-desktop")},
        )
        self.assertEqual(result.returncode, 37, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["steps"][0]["status"], "failed")
        self.assertEqual(report, json.loads((run_dir / "workflow-state.json").read_text()))
        self.assertIn("retained-scientific-diagnostic", (run_dir / report["steps"][0]["log"]).read_text())
        self.assertEqual((run_dir / "steps/contamination/work/inputs/table_0001.txt").read_bytes(),
                         sample.read_bytes())
        self.assertFalse((self.root / "src").exists())
        self.assertFalse((self.root / "lib/nipat").exists())

    def cpi_request(self):
        inputs = self.root / "CPI original inputs ,= è"
        inputs.mkdir()
        samples = []
        for number, name in enumerate(("A.txt", "--FatherB.txt")):
            path = inputs / f"alias_{number:04d}.tsv"
            path.write_bytes(b"chr pos1 pos2 REF ALT N_REF N_ALT N_Other total_count\r\n"
                             b"chr1 100 101 AC GT 98 2 0 100\r\n")
            samples.append({"path": str(path), "name": name})
        panel = inputs / "panel ,=.tsv"
        panel.write_text("chr\tpos1\tpos2\nchr1\t100\t101\n", encoding="utf-8")
        popfreq = inputs / "population ,=.tsv"
        popfreq.write_text("chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\nchr1\t100\t101\t0.8\t0.2\n",
                           encoding="utf-8")
        run = self.root / "CPI run è"
        request = {
            "schema_version": 1, "workflow": "cpi", "samples": samples,
            "pairs": " A : B ", "mother_prefix": "", "father_prefix": "--Father",
            "popfreq": str(popfreq), "cutoff_mode": "named",
            "cutoffs": [{"label": "-Panel è", "path": str(panel)}], "err_const": 0.01,
            "work_dir": str(run / "work"), "out_dir": str(run / "output"),
        }
        request_file = self.root / "cpi-request.json"
        request_file.write_text(json.dumps(request), encoding="utf-8")
        return request_file, request

    def cpi_tools(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        executable = fake_bin / "Rscript"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import argparse, json, os, sys\nfrom pathlib import Path\n"
            "parser = argparse.ArgumentParser()\n"
            "for key in ('pileup_dir','out_dir','pairs','mother_prefix','father_prefix','popfreq','err_const','cutoff_map'):\n"
            "    parser.add_argument('--' + key, required=True)\n"
            "args = parser.parse_args(sys.argv[2:])\n"
            "samples = {p.name: p.read_bytes().hex() for p in Path(args.pileup_dir).iterdir()}\n"
            "Path(os.environ['CPI_TEST_EVENTS']).write_text(json.dumps({\n"
            "    'argv': sys.argv, 'args': vars(args), 'samples': samples,\n"
            "    'output': Path(args.out_dir).is_dir(),\n"
            "    'panel': Path(args.cutoff_map.split('=', 1)[1]).read_text(),\n"
            "}))\n"
            "sys.exit(37)\n", encoding="utf-8",
        )
        executable.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
        environment["PYTHONPATH"] = str(self.root / "absent application")
        environment["CPI_TEST_EVENTS"] = str(self.root / "cpi-events.json")
        return environment

    @unittest.skipIf(os.name == "nt", "POSIX fixture exercises the Linux image entry point.")
    def test_relocated_cpi_stages_and_preserves_native_values_and_r_exit(self):
        request_file, request = self.cpi_request()
        environment = self.cpi_tools()
        result = subprocess.run(
            [sys.executable, str(self.root / "engine/main.py"), "execute", "cpi",
             "--request", str(request_file)], cwd=self.root / "engine", env=environment,
            capture_output=True, text=True, check=False, timeout=10,
        )
        self.assertEqual(result.returncode, 37, result.stderr)
        event = json.loads(Path(environment["CPI_TEST_EVENTS"]).read_text())
        self.assertEqual(event["argv"][1], str(self.root / "scientific" / engine.SCRIPT_PATHS["cpi"]))
        self.assertEqual(event["args"], {
            "pileup_dir": str(Path(request["work_dir"]) / "inputs"), "out_dir": request["out_dir"],
            "pairs": "A:B", "mother_prefix": "", "father_prefix": "--Father",
            "popfreq": request["popfreq"], "err_const": "0.01",
            "cutoff_map": f"-Panel è={Path(request['work_dir']) / 'cutoff_001.tsv'}",
        })
        self.assertEqual(event["samples"], {
            item["name"]: Path(item["path"]).read_bytes().hex() for item in request["samples"]
        })
        self.assertTrue(event["output"])
        self.assertEqual(event["panel"], "n°DNP\tchr\tpos1\tpos2\nDNP001\tchr1\t100\t101\n")

    @unittest.skipIf(os.name == "nt", "POSIX fixture exercises the Linux image entry point.")
    def test_invalid_cpi_request_prevents_r_and_native_staging(self):
        request_file, request = self.cpi_request()
        request["err_const"] = -1
        request_file.write_text(json.dumps(request), encoding="utf-8")
        environment = self.cpi_tools()
        result = subprocess.run(
            [sys.executable, str(self.root / "engine/main.py"), "execute", "cpi",
             "--request", str(request_file)], cwd=self.root, env=environment,
            capture_output=True, text=True, check=False, timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("non negativa", result.stderr)
        self.assertFalse(Path(environment["CPI_TEST_EVENTS"]).exists())
        self.assertFalse(Path(request["work_dir"]).parent.exists())

    def dnp_request(self, parallel=False):
        # Container aliases are deliberately shell-safe even when the bundled
        # application, source panel and run root have arbitrary user names.
        temporary = tempfile.TemporaryDirectory(prefix="nipat_dnp_aliases_")
        self.addCleanup(temporary.cleanup)
        inputs = Path(temporary.name).resolve()
        panel = self.root / "selected panel = à.txt"
        panel.write_text("chr1 100 101 ac gt\n", encoding="utf-8")
        samples = []
        for number in range(1, 3):
            sample_id = f"sample_{number:04d}"
            bam = inputs / f"{sample_id}.bam"
            bam.write_bytes(f"BAM fixture {number}".encode())
            samples.append({"path": str(bam), "sample_id": sample_id})
        reference = inputs / "genome.fa"
        reference.write_text(">chr1\nACGT\n", encoding="utf-8")
        Path(str(reference) + ".fai").write_text("chr1\t4\t6\t4\t5\n", encoding="utf-8")
        run = self.root / "run with spaces = à"
        request = {
            "schema_version": 1, "workflow": "dnp-call", "panel": str(panel),
            "samples": samples, "reference": str(reference), "parallel": parallel,
            "work_dir": str(run / "work"), "out_dir": str(run / "output"),
        }
        request_file = self.root / "dnp-request.json"
        request_file.write_text(json.dumps(request), encoding="utf-8")
        return request_file, request

    def dnp_tools(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        executable = fake_bin / "Rscript"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\nfrom pathlib import Path\n"
            "Path(os.environ['DNP_TEST_EVENTS']).write_text(json.dumps({\n"
            "    'argv': sys.argv, 'cwd': str(Path.cwd()),\n"
            "    'panel': Path('work/DNP_list.txt').read_text(),\n"
            "    'bamlist': Path('work/bamlist.txt').read_text(),\n"
            "    'output': Path('output').is_dir(),\n"
            "}))\n"
            "sys.exit(37)\n", encoding="utf-8",
        )
        executable.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
        environment["PYTHONPATH"] = str(self.root / "absent application")
        environment["DNP_TEST_EVENTS"] = str(self.root / "dnp-events.json")
        return environment

    @unittest.skipIf(os.name == "nt", "POSIX fixture exercises the Linux image entry point.")
    def test_relocated_dnp_uses_run_root_native_arguments_and_preserves_r_exit_code(self):
        request_file, request = self.dnp_request(parallel=True)
        environment = self.dnp_tools()
        result = subprocess.run(
            [sys.executable, str(self.root / "engine/main.py"), "execute", "dnp-call",
             "--request", str(request_file)], cwd=self.root / "engine", env=environment,
            capture_output=True, text=True, check=False, timeout=10,
        )
        self.assertEqual(result.returncode, 37, result.stderr)
        event = json.loads(Path(environment["DNP_TEST_EVENTS"]).read_text())
        self.assertEqual(event["cwd"], str(Path(request["work_dir"]).parent))
        self.assertEqual(event["argv"][1:], [
            str(self.root / "scientific" / engine.SCRIPT_PATHS["dnp-call"]),
            "--bamlist=work/bamlist.txt", "--DNPs=work/DNP_list.txt",
            "--out=output", f"--reference={request['reference']}", "--parallel",
        ])
        self.assertEqual(event["panel"], "chr1\t100\t101\tAC\tGT\n")
        self.assertEqual(event["bamlist"].splitlines(), [item["path"] for item in request["samples"]])
        self.assertTrue(event["output"])
        self.assertEqual(Path(request["panel"]).read_text(), "chr1 100 101 ac gt\n")

    @unittest.skipIf(os.name == "nt", "POSIX fixture exercises the Linux image entry point.")
    def test_invalid_dnp_request_prevents_r_and_native_staging(self):
        request_file, request = self.dnp_request()
        request["parallel"] = "false"
        request_file.write_text(json.dumps(request), encoding="utf-8")
        environment = self.dnp_tools()
        result = subprocess.run(
            [sys.executable, str(self.root / "engine/main.py"), "execute", "dnp-call",
             "--request", str(request_file)], cwd=self.root, env=environment,
            capture_output=True, text=True, check=False, timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("booleana", result.stderr)
        self.assertFalse(Path(environment["DNP_TEST_EVENTS"]).exists())
        self.assertFalse(Path(request["work_dir"]).parent.exists())

    def snp_request(self, mode="bam"):
        inputs = self.root / "selected SNP inputs"
        inputs.mkdir()
        panel = inputs / "panel.tsv"
        panel.write_text("pos\tref\talt\nchr1:100\tA\tC\n", encoding="utf-8")
        bam = inputs / "sample.bam"
        bam.write_bytes(b"samtools fixture")
        reference = inputs / "genome.fa"
        reference.write_text(">chr1\n" + "A" * 200 + "\n", encoding="utf-8")
        Path(str(reference) + ".fai").write_text("chr1\t200\t6\t200\t201\n", encoding="utf-8")
        pileup = inputs / "pileup.txt"
        pileup.write_text("chr1\t100\tA\t1\t.\tI\tread1\n", encoding="utf-8")
        request = {
            "schema_version": 1, "workflow": "snp-call", "mode": mode,
            "panel": str(panel), "bam": str(bam) if mode == "bam" else None,
            "reference": str(reference) if mode == "bam" else None,
            "pileup": str(pileup) if mode == "pileup" else None,
            "work_dir": str(self.root / "snp-results/work"),
            "out_dir": str(self.root / "snp-results/output"),
        }
        request_file = self.root / "snp-request.json"
        request_file.write_text(json.dumps(request), encoding="utf-8")
        return request_file, request

    def snp_tools(self, samtools_body):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        header = (
            f"#!{sys.executable}\n"
            "import json, os, sys\nfrom pathlib import Path\n"
            "with Path(os.environ['SNP_TEST_EVENTS']).open('a') as log:\n"
            "    log.write(json.dumps(sys.argv) + '\\n')\n"
        )
        for name, body in (("samtools", samtools_body), ("Rscript", "sys.exit(37)\n")):
            executable = fake_bin / name
            executable.write_text(header + body, encoding="utf-8")
            executable.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
        environment["PYTHONPATH"] = str(self.root / "absent application")
        environment["SNP_TEST_EVENTS"] = str(self.root / "events.jsonl")
        return environment

    def run_snp_request(self, request_file, environment):
        return subprocess.run(
            [sys.executable, str(self.root / "engine/main.py"), "execute", "snp-call",
             "--request", str(request_file)], cwd=self.root, env=environment,
            capture_output=True, text=True, check=False, timeout=10,
        )

    def snp_events(self):
        path = self.root / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    @unittest.skipIf(os.name == "nt", "POSIX executables exercise the Linux image entry point.")
    def test_relocated_snp_bam_executes_samtools_then_r_with_original_options(self):
        request_file, request = self.snp_request()
        environment = self.snp_tools(
            "Path(sys.argv[sys.argv.index('-o') + 1]).write_text('chr1\\t100\\tA\\t1\\t.\\tI\\tread1\\n')\n"
        )
        result = self.run_snp_request(request_file, environment)
        self.assertEqual(result.returncode, 37, result.stderr)
        commands = self.snp_events()
        self.assertEqual([Path(command[0]).name for command in commands], ["samtools", "Rscript"])
        self.assertEqual(commands[0][1:], [
            "mpileup", "-f", request["reference"], "-l", request["work_dir"] + "/snp_regions.bed",
            "--output-QNAME", "--no-output-ins", "--no-output-del", "--no-output-ends",
            "-o", request["work_dir"] + "/pileup.txt", request["bam"],
        ])
        self.assertEqual(commands[1][1:], [
            str(self.root / "scientific" / engine.SCRIPT_PATHS["snp-call"]),
            "--pileup", request["work_dir"] + "/pileup.txt", "--snplist", request["panel"],
            "--out", request["out_dir"] + "/SNPcall_output.txt",
        ])
        self.assertEqual(Path(request["work_dir"], "snp_regions.bed").read_text(), "chr1\t98\t101\n")

    @unittest.skipIf(os.name == "nt", "POSIX executables exercise the Linux image entry point.")
    def test_snp_existing_pileup_skips_samtools(self):
        request_file, request = self.snp_request(mode="pileup")
        result = self.run_snp_request(request_file, self.snp_tools("sys.exit(99)\n"))
        self.assertEqual(result.returncode, 37, result.stderr)
        commands = self.snp_events()
        self.assertEqual([Path(command[0]).name for command in commands], ["Rscript"])
        self.assertEqual(commands[0][commands[0].index("--pileup") + 1], request["pileup"])
        self.assertEqual(list(Path(request["work_dir"]).iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX executables exercise the Linux image entry point.")
    def test_snp_samtools_failure_preserves_exit_code_without_starting_r(self):
        request_file, request = self.snp_request()
        result = self.run_snp_request(request_file, self.snp_tools("sys.exit(17)\n"))
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual([Path(c[0]).name for c in self.snp_events()], ["samtools"])
        self.assertTrue(Path(request["work_dir"], "snp_regions.bed").is_file())
        self.assertEqual(list(Path(request["out_dir"]).iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX executables exercise the Linux image entry point.")
    def test_snp_generated_pileup_must_be_valid_before_r(self):
        request_file, request = self.snp_request()
        environment = self.snp_tools(
            "Path(sys.argv[sys.argv.index('-o') + 1]).write_text('chr1\\t100\\tA\\t1\\t.\\tI\\n')\n"
        )
        result = self.run_snp_request(request_file, environment)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("7 colonne", result.stderr)
        self.assertEqual([Path(c[0]).name for c in self.snp_events()], ["samtools"])
        self.assertTrue(Path(request["work_dir"], "pileup.txt").is_file())
        self.assertEqual(list(Path(request["out_dir"]).iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX executables exercise the Linux image entry point.")
    def test_snp_success_without_usable_pileup_never_starts_r(self):
        request_file, request = self.snp_request()
        environment = self.snp_tools(
            "if os.environ['SNP_TEST_PILEUP_MODE'] == 'empty':\n"
            "    Path(sys.argv[sys.argv.index('-o') + 1]).write_text('')\n"
        )
        for mode in ("missing", "empty"):
            with self.subTest(mode=mode):
                case = {**request, "work_dir": str(self.root / mode / "work"),
                        "out_dir": str(self.root / mode / "output")}
                request_file.write_text(json.dumps(case), encoding="utf-8")
                environment["SNP_TEST_PILEUP_MODE"] = mode
                Path(environment["SNP_TEST_EVENTS"]).unlink(missing_ok=True)
                result = self.run_snp_request(request_file, environment)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual([Path(c[0]).name for c in self.snp_events()], ["samtools"])
                self.assertEqual(list(Path(case["out_dir"]).iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX signals exercise the Linux container supervisor.")
    def test_snp_cancellation_reaches_samtools_and_prevents_r_even_if_child_returns_zero(self):
        request_file, request = self.snp_request()
        environment = self.snp_tools(
            "import signal, time\n"
            "def stop(signum, frame):\n"
            "    Path(os.environ['SNP_TEST_EVENTS'] + '.signal').write_text(str(signum))\n"
            "    sys.exit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "Path(os.environ['SNP_TEST_EVENTS'] + '.ready').write_text('ready')\n"
            "while True: time.sleep(0.1)\n"
        )
        process = subprocess.Popen(
            [sys.executable, str(self.root / "engine/main.py"), "execute", "snp-call",
             "--request", str(request_file)], env=environment, cwd=self.root,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            ready = Path(environment["SNP_TEST_EVENTS"] + ".ready")
            deadline = time.monotonic() + 5
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "samtools fixture did not become ready")
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 128 + signal.SIGTERM, stdout + stderr)
            self.assertEqual(Path(environment["SNP_TEST_EVENTS"] + ".signal").read_text(), str(signal.SIGTERM))
            self.assertEqual([Path(c[0]).name for c in self.snp_events()], ["samtools"])
            self.assertEqual(list(Path(request["out_dir"]).iterdir()), [])
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
