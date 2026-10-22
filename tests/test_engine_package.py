from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
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
        self.root = Path(self.temporary.name)
        (self.root / "engine").mkdir()
        shutil.copyfile(MODULE_PATH, self.root / "engine" / "main.py")
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


if __name__ == "__main__":
    unittest.main()
