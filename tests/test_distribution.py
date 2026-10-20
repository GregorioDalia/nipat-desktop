import importlib.util
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_validation_bundle.py"
SPEC = importlib.util.spec_from_file_location("nipat_bundle", SCRIPT)
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class DistributionTests(unittest.TestCase):
    def make_project(self, root):
        project = root / "project"
        project.mkdir()
        for name in ("1_SETUP.cmd", "2_AVVIA.cmd", "nipat.cmd", "compose.yaml"):
            (project / name).write_text("test", encoding="utf-8")
        (project / "pyproject.toml").write_text('[project]\nversion = "0.2.0a1"\n', encoding="utf-8")
        (project / "src" / "nipat").mkdir(parents=True)
        (project / "src" / "nipat" / "cli.py").write_text("pass\n", encoding="utf-8")
        (project / "distribution-files.txt").write_text(
            "1_SETUP.cmd\n2_AVVIA.cmd\nnipat.cmd\ncompose.yaml\npyproject.toml\n"
            "src/nipat/cli.py\ndistribution-files.txt\n", encoding="utf-8",
        )
        return project

    def test_package_excludes_workspace_private_and_binary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)
            unwanted = [
                "data/sample.txt", "runs/private.txt", ".env", ".git/config",
                ".venv/Lib/secret.txt", "docs/sample.bam", "docs/.env",
                "src/nipat/__pycache__/cli.pyc", "docs/credentials.txt",
                "docs/secrets/token.json", "scripts/.runtime/python.exe",
                "docs/pazienti.tsv", "config/api_keys.json",
                "scientific/private_samples.txt", "scripts/debug_output.txt",
            ]
            for relative in unwanted:
                path = project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("must not ship", encoding="utf-8")
            (project / "SUNTO.md").write_text("Sunto", encoding="utf-8")
            (project / "scientific" / "vendor").mkdir(parents=True)
            (project / "scientific" / "vendor" / "LICENSE").write_text("Upstream license", encoding="utf-8")
            (project / "scientific" / "vendor" / "notice").write_text("Upstream notice", encoding="utf-8")
            with (project / "distribution-files.txt").open("a", encoding="utf-8") as manifest:
                manifest.write("SUNTO.md\nscientific/vendor/LICENSE\nscientific/vendor/notice\n")
            portable = root / "python.zip"
            portable.write_bytes(b"placeholder: validation of real archive is tested separately")
            output = root / "package.zip"
            with patch.object(bundle, "git_source", return_value={"available": False}):
                release = bundle.package_sources(project, output, portable)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                for relative in unwanted:
                    self.assertNotIn(f"nipat-desktop/{relative}", names)
                self.assertIn("nipat-desktop/SUNTO.md", names)
                self.assertIn("nipat-desktop/scientific/vendor/LICENSE", names)
                self.assertIn("nipat-desktop/scientific/vendor/notice", names)
                self.assertIn("nipat-desktop/src/nipat/cli.py", names)
                saved = json.loads(archive.read("nipat-desktop/release.json"))
                self.assertEqual(saved, release)
                self.assertEqual(saved["source_sha256"]["src/nipat/cli.py"], bundle.sha256_file(project / "src/nipat/cli.py"))

    def test_package_never_overwrites_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)
            output = root / "existing.zip"
            output.write_bytes(b"existing package")
            portable = root / "python.zip"
            portable.write_bytes(b"placeholder")
            with self.assertRaises(FileExistsError):
                bundle.package_sources(project, output, portable)
            self.assertEqual(output.read_bytes(), b"existing package")

    def test_wrong_python_checksum_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "python.zip"
            path.write_bytes(b"corrupted or different version")
            with self.assertRaisesRegex(ValueError, "checksum"):
                bundle.require_python_archive(path)

    def test_docker_export_uses_resolved_image_id_and_records_archive_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            image_id = "sha256:" + "a" * 64
            calls = []

            def docker(command, **kwargs):
                calls.append(command)
                if command[2] == "inspect":
                    return subprocess.CompletedProcess(command, 0, json.dumps([{
                        "Id": image_id, "Os": "linux", "Architecture": "amd64",
                    }]))
                Path(command[4]).write_bytes(b"docker image archive")
                return subprocess.CompletedProcess(command, 0)

            with patch.object(bundle.subprocess, "run", side_effect=docker):
                archive, metadata = bundle.export_runtime(temporary, "mutable:tag", temporary)
            self.assertEqual(calls[1][-1], image_id)
            self.assertEqual(metadata["image_id"], image_id)
            self.assertEqual(metadata["archive_sha256"], bundle.sha256_file(archive))
            self.assertEqual(metadata["archive_bytes"], archive.stat().st_size)

    def test_docker_export_rejects_incompatible_platform_before_saving(self):
        result = subprocess.CompletedProcess([], 0, json.dumps([{
            "Id": "sha256:" + "a" * 64, "Os": "linux", "Architecture": "arm64",
        }]))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(bundle.subprocess, "run", return_value=result) as run:
                with self.assertRaisesRegex(ValueError, "amd64"):
                    bundle.export_runtime(root, "runtime", root)
            self.assertEqual(run.call_count, 1)

    def test_listed_source_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self.make_project(root)
            outside = root / "private.txt"
            outside.write_text("private data", encoding="utf-8")
            link = project / "src" / "private.txt"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("Symlinks unavailable in this environment")
            with (project / "distribution-files.txt").open("a", encoding="utf-8") as manifest:
                manifest.write("src/private.txt\n")
            with self.assertRaisesRegex(ValueError, "simbolico"):
                bundle.source_files(project)

    def test_manifest_rejects_escape_duplicates_and_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory))
            manifest = project / "distribution-files.txt"
            valid = manifest.read_text(encoding="utf-8")
            for bad in ("../outside.txt", "/absolute.txt", "C:/private.txt",
                        "src\\private.txt", "src/./nipat/cli.py", "src//nipat/cli.py",
                        "nipat.cmd", "NIPAT.CMD", "not-existing.py", "data/sample.txt"):
                with self.subTest(entry=bad):
                    manifest.write_text(valid + bad + "\n", encoding="utf-8")
                    with self.assertRaises(ValueError):
                        bundle.source_files(project)


if __name__ == "__main__":
    unittest.main()
