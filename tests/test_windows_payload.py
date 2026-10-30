"""Guard staged-client evidence; the Linux test below is not a Windows install."""

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("windows_payload_check", ROOT / "scripts/verify_windows_payload.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class WindowsPayloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.app = self.root / "app"
        self.app.mkdir()

    def write(self, name, content):
        path = self.app / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def package(self):
        source = "src/nipat/__init__.py"
        self.write(source, '__version__ = "0.7.0a1"\n')
        self.write("NIPAT.exe", "fixture launcher")
        self.write("installer/windows/EnableWsl.exe", "fixture helper")
        archive = self.write(f".distribution/{check.PYTHON_ARCHIVE}", "fixture archive")
        self.addCleanup(patch.stopall)
        patch.object(check, "PYTHON_SHA256", check.digest(archive)).start()
        manifest = {"schema_version": 1, "source_commit": "a" * 40, "version": "0.7.0a1",
                    "runtime_image": "sha256:" + "b" * 64,
                    "source_sha256": {source: check.digest(self.app / source)}}
        manifest_path = self.write(".distribution/installer-manifest.json", json.dumps(manifest))
        release = {"schema_version": 1, "package_version": manifest["version"],
                   "source_git": {"commit": manifest["source_commit"], "dirty": False, "available": True},
                   "source_sha256": manifest["source_sha256"], "installer_manifest_sha256": check.digest(manifest_path),
                   "runtime": {"image_id": manifest["runtime_image"]},
                   "python": {"version": "3.12.10", "architecture": "amd64", "archive_sha256": check.PYTHON_SHA256}}
        self.write("release.json", json.dumps(release))
        self.reinventory(manifest)
        return manifest

    def reinventory(self, manifest):
        entries = [{"path": path.relative_to(self.app).as_posix(), "sha256": check.digest(path)}
                   for path in sorted(self.app.rglob("*")) if path.is_file() and path.name != "application-files.json"]
        inventory = {"schema_version": 1, "installation_channel": "experimental08",
                     "source_commit": manifest["source_commit"], "files": entries}
        self.write(".distribution/application-files.json", json.dumps(inventory))

    def test_payload_rejects_tampering_even_if_source_is_reinventoried(self):
        manifest = self.package()
        self.assertEqual(check.verify_payload(self.app)[0], manifest)
        self.write("src/nipat/__init__.py", "changed\n")
        with self.assertRaisesRegex(ValueError, "Changed packaged file"):
            check.verify_payload(self.app)
        self.reinventory(manifest)
        with self.assertRaisesRegex(ValueError, "Source digest mismatch"):
            check.verify_payload(self.app)

    def test_release_cannot_claim_another_source_even_with_updated_inventory(self):
        manifest = self.package()
        release = check.read_json(self.app / "release.json")
        for key, value in (("package_version", "0.6.0"), ("installer_manifest_sha256", "c" * 64),
                           ("source_git", {"commit": "c" * 40, "dirty": False, "available": True})):
            with self.subTest(key=key):
                altered = copy.deepcopy(release)
                altered[key] = value
                self.write("release.json", json.dumps(altered))
                self.reinventory(manifest)
                with self.assertRaisesRegex(ValueError, "Release metadata"):
                    check.verify_payload(self.app)

    def test_inventory_cannot_omit_or_duplicate_payload_files(self):
        self.package()
        inventory = check.read_json(self.app / ".distribution/application-files.json")
        for entries in (inventory["files"][:-1], inventory["files"] + [inventory["files"][0]]):
            with self.subTest(entries=len(entries)):
                self.write(".distribution/application-files.json", json.dumps({**inventory, "files": entries}))
                with self.assertRaises(ValueError):
                    check.verify_payload(self.app)

    def test_payload_paths_cannot_escape_or_use_windows_aliases(self):
        self.write("file.txt", "contents")
        for relative in ("../file.txt", "/file.txt", "a/../file.txt", "file.txt ", "file.txt:stream", "a\\file.txt"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                check.payload_file(self.app, relative)

    @unittest.skipIf(__import__("os").name == "nt", "Native Linux harness; real embedded Windows smoke runs in installer CI")
    def test_real_relocated_client_dry_runs_and_rejects_false_success_or_writable_inputs(self):
        # Run genuine CLI subprocesses from copied sources using the native dry-run
        # transport. Only the Windows host/embedded-Python bridge is outside scope.
        shutil.copytree(ROOT / "src", self.app / "src", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "compose.yaml", self.app / "compose.yaml")
        manifest = {"version": __import__("nipat").__version__, "source_commit": "a" * 40,
                    "runtime_image": "sha256:" + "b" * 64}
        self.write("release.json", json.dumps({"source_git": {"commit": manifest["source_commit"]}}))
        original_run = subprocess.run

        def native_run(*args, **kwargs):
            environment = kwargs["env"].copy()
            environment["NIPAT_BACKEND"] = "native"
            environment["PYTHONPATH"] = str(self.app / "src")
            return original_run(*args, **{**kwargs, "env": environment})

        with patch.object(check.subprocess, "run", side_effect=native_run):
            check.exercise_client(self.app, self.root, manifest)
        run = self.root / "runs/dnp-contamination-cpi"
        originals = [self.root / "external inputs $ ,= è" / name for name in ("mother.bam", "father.bam")]
        arguments = {"workflows": ["dnp-call", "contamination", "cpi", "snp-call", "snp-call"],
                     "mode": "bam", "originals": originals, "commit": manifest["source_commit"]}
        record_path = run / "run.json"
        record = check.read_json(record_path)
        record_path.write_text(json.dumps({**record, "status": "succeeded"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must not report scientific success"):
            check.verify_plan(run, **arguments)
        record_path.write_text(json.dumps(record), encoding="utf-8")
        compose_path = run / "work/engine-compose.json"
        compose = check.read_json(compose_path)
        for mount in compose["services"]["scientific"]["volumes"]:
            if mount["target"].startswith("/workspace/inputs/"):
                mount["read_only"] = False
                break
        compose_path.write_text(json.dumps(compose), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unexpected writable mount"):
            check.verify_plan(run, **arguments)


if __name__ == "__main__":
    unittest.main()
