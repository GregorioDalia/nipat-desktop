"""Fail-closed checks for the external, installed-client acceptance driver."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("installed_suite", ROOT / "scripts/acceptance/installed_suite.py")
suite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(suite)
IMAGE = "sha256:" + "a" * 64


class InstalledSuiteTests(unittest.TestCase):
    def test_download_manifest_and_windows_wrapper_pin_the_exact_test_bundle(self):
        directory = ROOT / "scripts/acceptance"
        manifest = directory / "bundle-manifest.json"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(set(document["files"]), {"installed_suite.py", "installed_models.py",
                                                "installed_workflows.py", "fixtures.json"})
        for name, expected in document["files"].items():
            self.assertEqual(suite.digest(directory / name), expected, name)
        wrapper = (ROOT / "scripts/windows/test-installed-0850.ps1").read_text(encoding="utf-8")
        expected = re.search(r"\$ExpectedManifestSha256 = '([a-f0-9]{64})'", wrapper)
        self.assertIsNotNone(expected)
        self.assertEqual(expected.group(1), suite.digest(manifest))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / "app"
        self.app.mkdir()
        self.session = self.root / "acceptance"
        self.session.mkdir()
        self.driver = suite.Suite(self.app, self.session, "a" * 40)
        self.driver.image = IMAGE

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def record(self, path, **overrides):
        document = {"status": "succeeded", "engine_verification": "verified",
                    "runtime": {"image_id": IMAGE}, "commands": [{"status": "succeeded"}]}
        document.update(overrides)
        self.write(path / "run.json", document)
        return document

    def process_result(self, stdout="", stderr="", code=2):
        output, error = self.driver.logs / "out.log", self.driver.logs / "err.log"
        output.write_text(stdout, encoding="utf-8")
        error.write_text(stderr, encoding="utf-8")
        return {"stdout": str(output), "stderr": str(error), "returncode": code, "timed_out": False}

    def test_session_cannot_capture_or_write_the_application(self):
        with self.assertRaisesRegex(ValueError, "fuori"):
            suite.Suite(self.app, self.app / "test", "a" * 40)
        self.assertFalse((self.app / "test").exists())
        with self.assertRaises(ValueError):
            suite.Suite(self.app, self.root, "a" * 40)

    def test_cli_explicit_storage_mode_and_science_precede_command(self):
        command = list(map(str, self.driver.command(["--set", "cpi.min_fetal_reads=1", "cpi", "--pairs", "M:F"], "cap2")))
        self.assertEqual(command[command.index("--data-dir") + 1], str(self.driver.inputs))
        self.assertEqual(command[command.index("--runs-dir") + 1], str(self.driver.runs))
        self.assertEqual(command[command.index("--max-workers") + 1], "2")
        self.assertEqual(command[command.index("--input-hashes") + 1], "full")
        self.assertLess(command.index("--scientific-config"), command.index("cpi"))
        self.assertEqual(Path(command[command.index("-File") + 1]),
                         self.app.resolve() / "scripts/windows/run.ps1")

    def cli_arguments(self, arguments, mode=None):
        command = list(map(str, self.driver.command(arguments, mode)))
        return command[command.index("-File") + 2:]

    def test_every_probe_passes_the_real_cli_option_checks_before_runtime_access(self):
        from nipat import cli

        probes = (["doctor", "--runtime"], ["settings", "--json"],
                  ["resources", "inspect", "--json"],
                  ["runs", "stop", "--run", self.driver.runs / "owned", "--yes", "--json"])
        for arguments in probes:
            with self.subTest(command=arguments[0]):
                argv = self.cli_arguments(arguments)
                parsed = cli.build_parser().parse_args(argv)
                self.assertIsNone(parsed.input_hashes)
                self.assertIsNone(parsed.execution_mode)
                self.assertIsNone(parsed.max_workers)
                # main() performs semantic option validation before loading the
                # scientific configuration. Stop there, before any host/runtime
                # operations; the parser and its validation are real.
                with patch.object(cli, "load_scientific_config",
                                  side_effect=RuntimeError("option-validation-completed")):
                    with self.assertRaisesRegex(RuntimeError, "option-validation-completed"):
                        cli.main(argv)

    def test_settings_probe_runs_the_real_cli_without_analysis_only_flags(self):
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith("NIPAT_")
                       and key.upper() not in {"PYTHONHOME", "PYTHONPATH"}}
        environment.update(PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "nipat", *self.cli_arguments(["settings", "--json"])],
            cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        document = json.loads(result.stdout)
        expected = {"dnp-call", "snp-call", "contamination", "cpi", "cpin"}
        self.assertEqual(set(document["modules"]), expected)
        self.assertEqual(set(document["effective"]), expected)

    def test_probe_failure_surfaces_the_actual_diagnostic_in_the_report_error(self):
        for stdout, stderr, expected in (("", "Specific CLI rejection", "Specific CLI rejection"),
                                         ("PowerShell launcher error", "", "PowerShell launcher error"),
                                         ("", "", "nessun messaggio restituito")):
            with self.subTest(expected=expected):
                result = self.process_result(stdout=stdout, stderr=stderr, code=2)
                with patch.object(self.driver, "process", return_value=result):
                    with self.assertRaises(ValueError) as failure:
                        self.driver.probe("doctor", ["doctor", "--runtime"])
                self.assertIn(expected, str(failure.exception))
                self.assertIn("codice 2", str(failure.exception))
                self.assertIn(result["stderr"], str(failure.exception))
        result = self.process_result(stderr="DISCARDED_PREFIX" + "x" * 2500 + "FINAL_DIAGNOSTIC")
        with patch.object(self.driver, "process", return_value=result):
            with self.assertRaises(ValueError) as failure:
                self.driver.probe("doctor", ["doctor", "--runtime"])
        self.assertNotIn("DISCARDED_PREFIX", str(failure.exception))
        self.assertIn("FINAL_DIAGNOSTIC", str(failure.exception))

    def test_fixtures_verify_bytes_and_refuse_path_escape(self):
        content = "chr\tpos\nchr1\t2\n"
        valid = {"schema_version": 1, "source_commit": suite.BASE_COMMIT,
                 "files": {"snp_engine/fixture.tsv": {"content": content,
                            "sha256": hashlib.sha256(content.encode()).hexdigest()}}}
        source = self.root / "fixtures.json"
        self.write(source, valid)
        suite.extract_fixtures(source, self.root / "good")
        self.assertEqual((self.root / "good/snp_engine/fixture.tsv").read_text(), content)
        for index, name in enumerate(("../escape", "/absolute", "snp_engine/../escape", "snp_engine\\escape", "snp_engine/a:stream")):
            altered = copy.deepcopy(valid)
            altered["files"] = {name: next(iter(valid["files"].values()))}
            self.write(source, altered)
            with self.subTest(name=name), self.assertRaises(ValueError):
                suite.extract_fixtures(source, self.root / f"bad-{index}")
        altered = copy.deepcopy(valid)
        altered["files"]["snp_engine/fixture.tsv"]["content"] += "changed"
        self.write(source, altered)
        with self.assertRaisesRegex(ValueError, "Checksum"):
            suite.extract_fixtures(source, self.root / "tampered")

    def test_success_requires_actual_execution_and_same_local_image(self):
        run = self.driver.runs / "case"
        valid = self.record(run)
        self.assertEqual(suite.verify_run(run, IMAGE)["runtime_image"], IMAGE)
        for changes in ({"status": "planned"}, {"engine_verification": "not_run_dry_run"},
                        {"runtime": {"image_id": "sha256:" + "b" * 64}}, {"commands": []},
                        {"commands": [{"status": "failed"}]}):
            with self.subTest(changes=changes):
                self.write(run / "run.json", {**valid, **changes})
                with self.assertRaises(ValueError):
                    suite.verify_run(run, IMAGE)

    def test_expected_failure_requires_specific_error_not_infrastructure_or_success(self):
        run = self.driver.runs / "negative"
        result = self.process_result(stderr="N_REF deve essere intero non negativo")
        suite.verify_expected_failure(result, r"N_REF.*intero non negativo", run, IMAGE)
        for text in ("corrupt.bam failed", "Traceback: N_REF deve essere intero non negativo",
                     "out of memory; N_REF deve essere intero non negativo"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                suite.verify_expected_failure(self.process_result(stderr=text), r"N_REF.*intero non negativo", run, IMAGE)
        self.record(run)
        with self.assertRaises(ValueError):
            suite.verify_expected_failure(result, r"N_REF.*intero non negativo", run, IMAGE)
        self.record(run, status="failed", commands=[{"status": "failed"}])
        with self.assertRaises(ValueError):
            suite.verify_expected_failure({**result, "timed_out": True}, r"N_REF.*intero non negativo", run, IMAGE)

    def test_expected_bam_failure_reads_actual_engine_command_log(self):
        run = self.driver.runs / "corrupt"
        result = self.process_result(stderr="Esecuzione scientifica fallita; vedere run")
        self.record(run, status="failed", commands=[{"status": "failed"}])
        log = run / "output/workflow/steps/dnp/command.log"
        log.parent.mkdir(parents=True)
        log.write_text("samtools mpileup: fail to read the header of /inputs/corrupt.bam", encoding="utf-8")
        suite.verify_expected_failure(result, r"fail to read the header of", run, IMAGE)

    def test_input_change_or_new_file_fails_integrity(self):
        original = self.driver.inputs / "input.txt"
        original.write_text("original")
        before = suite.input_snapshot(self.driver.inputs)
        original.write_text("modified")
        with self.assertRaisesRegex(ValueError, "modificati"):
            self.driver.require_snapshot(before, suite.input_snapshot(self.driver.inputs))
        original.write_text("original")
        (self.driver.inputs / "new.txt").write_text("unexpected")
        with self.assertRaises(ValueError):
            self.driver.require_snapshot(before, suite.input_snapshot(self.driver.inputs))

    def test_scientific_comparison_ignores_work_and_detects_numeric_mutation(self):
        for name in ("serial", "auto"):
            run = self.driver.runs / name
            for relative, text in (("output/workflow/steps/snp/output/calls.tsv", "GL1\n-2.0\n"),
                                   ("output/workflow/steps/snp/work/paths.txt", name),
                                   ("output/presentation/labels.tsv", name),
                                   ("output/resources.tsv", name)):
                path = run / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        first = suite.scientific_tables(self.driver.runs / "serial")
        second = suite.scientific_tables(self.driver.runs / "auto")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        (self.driver.runs / "auto/output/workflow/steps/snp/output/calls.tsv").write_text("GL1\n-1.0\n")
        self.assertNotEqual(first, suite.scientific_tables(self.driver.runs / "auto"))

    def test_missing_parallel_case_blocks_comparison(self):
        self.driver.cases = [{"id": mode, "compare_group": "same"} for mode in ("serial", "auto", "cap2")]
        self.driver.report["cases"] = [{"id": "serial", "status": "PASS", "scientific_tables": {"x": "y"}}]
        self.driver.compare()
        self.assertEqual(self.driver.report["comparisons"][0]["status"], "BLOCKED")

    def test_oracle_failure_is_retained_and_later_case_can_run(self):
        def process(name, *args, **kwargs):
            self.record(self.driver.runs / name)
            return self.process_result(code=0)
        def failed(_):
            raise ValueError("expected CPI20, observed CPI2")
        cases = [{"id": name, "category": "numbers", "args": ["cpi"], "validate": validator}
                 for name, validator in (("wrong", failed), ("right", lambda _: {"CPI": 20}))]
        with patch.object(self.driver, "process", side_effect=process):
            for number, case in enumerate(cases, 1):
                self.driver.execute_case(case, number, len(cases))
        self.assertEqual([case["status"] for case in self.driver.report["cases"]], ["FAIL", "PASS"])
        self.assertIn("expected CPI20", self.driver.report["cases"][0]["error"])

    def test_empty_or_failed_suite_writes_readable_report_and_archive_without_false_pass(self):
        self.driver.report["checks"].append({"id": "runtime", "status": "FAIL", "error": "<script>bad</script>"})
        self.driver.finish()
        report = json.loads((self.session / "report.json").read_text())
        self.assertEqual(report["status"], "FAIL")
        markup = (self.session / "report.html").read_text()
        self.assertNotIn("<script>bad</script>", markup)
        self.assertIn("&lt;script&gt;bad", markup)
        with zipfile.ZipFile(self.session / "report.zip") as archive:
            self.assertIn("report.json", archive.namelist())
            self.assertEqual(json.loads(archive.read("report.json"))["status"], "FAIL")
        self.assertFalse((self.session / "report.zip.tmp").exists())

    def test_archive_does_not_follow_external_file_links(self):
        external = self.root / "private.txt"
        external.write_text("private data")
        link = self.driver.logs / "linked.txt"
        try:
            link.symlink_to(external)
        except OSError:
            self.skipTest("File links unavailable")
        self.driver.finish()
        with zipfile.ZipFile(self.session / "report.zip") as archive:
            self.assertNotIn("logs/linked.txt", archive.namelist())
        self.assertEqual(self.driver.report["archive_omissions"][0]["path"], "logs/linked.txt")


if __name__ == "__main__":
    unittest.main()
