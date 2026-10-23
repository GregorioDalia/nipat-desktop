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
            source.write_bytes(f"# Fixture {workflow}\n".encode())
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
        })
        self.assertEqual(metadata["preparation"]["interface"], "workflow-preparation-v1")
        hashes = metadata["preparation"]["file_sha256"]
        self.assertEqual(len(hashes), 8)
        self.assertIn("engine/main.py", hashes)
        self.assertIn("lib/nipat_scientific/contamination.py", hashes)
        self.assertIn("lib/nipat_scientific/snp.py", hashes)
        self.assertIn("lib/nipat_scientific/dnp.py", hashes)
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
