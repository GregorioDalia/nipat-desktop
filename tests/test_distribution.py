import hashlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "distribution_support.py"
SPEC = importlib.util.spec_from_file_location("nipat_distribution_support", SCRIPT)
distribution = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(distribution)


class DistributionTests(unittest.TestCase):
    def make_project(self, root):
        project = root / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nversion = "0.5.0a1"\n', encoding="utf-8")
        (project / "src" / "nipat").mkdir(parents=True)
        (project / "src" / "nipat" / "cli.py").write_text("pass\n", encoding="utf-8")
        (project / "distribution-files.txt").write_text(
            "pyproject.toml\nsrc/nipat/cli.py\ndistribution-files.txt\n", encoding="utf-8",
        )
        return project

    def test_only_approved_sources_are_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory))
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
            (project / "scientific" / "vendor").mkdir(parents=True)
            (project / "scientific" / "vendor" / "LICENSE").write_text("Upstream license", encoding="utf-8")
            with (project / "distribution-files.txt").open("a", encoding="utf-8") as manifest:
                manifest.write("scientific/vendor/LICENSE\n")
            names = {path.relative_to(project.resolve()).as_posix()
                     for path in distribution.source_files(project)}
            self.assertEqual(names, {"pyproject.toml", "src/nipat/cli.py", "distribution-files.txt",
                                     "scientific/vendor/LICENSE"})
            self.assertFalse(names.intersection(unwanted))

    def test_wrong_python_checksum_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "python.zip"
            path.write_bytes(b"corrupted or different version")
            with self.assertRaisesRegex(ValueError, "checksum"):
                distribution.require_python_archive(path)

    def test_verified_requested_python_archive_requires_no_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "python.zip"
            contents = b"verified archive fixture"
            path.write_bytes(contents)
            with patch.object(distribution, "PYTHON_SHA256", hashlib.sha256(contents).hexdigest()), \
                 patch.object(distribution.urllib.request, "urlopen", side_effect=AssertionError("No download expected")):
                self.assertEqual(distribution.python_archive(root, path, root), path)

    def test_downloaded_python_archive_is_verified_before_use(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            temporary = root / "temporary"
            temporary.mkdir()
            contents = b"downloaded archive fixture"
            with patch.object(distribution, "PYTHON_SHA256", hashlib.sha256(contents).hexdigest()), \
                 patch.object(distribution.urllib.request, "urlopen", return_value=io.BytesIO(contents)) as download:
                result = distribution.python_archive(root, None, temporary)
            self.assertEqual(result.read_bytes(), contents)
            download.assert_called_once_with(distribution.PYTHON_URL, timeout=120)
            result.unlink()
            with patch.object(distribution.urllib.request, "urlopen", return_value=io.BytesIO(b"tampered archive")):
                with self.assertRaisesRegex(ValueError, "checksum"):
                    distribution.python_archive(root, None, temporary)

    def test_git_provenance_records_clean_and_modified_source(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory))
            subprocess.run(["git", "init", "--quiet", str(project)], check=True)
            subprocess.run(["git", "add", "."], cwd=project, check=True)
            subprocess.run(["git", "-c", "user.name=NIPAT Test", "-c", "user.email=test@example.invalid",
                            "commit", "--quiet", "-m", "Fixture"], cwd=project, check=True)
            clean = distribution.git_source(project)
            self.assertTrue(clean["available"])
            self.assertFalse(clean["dirty"])
            self.assertRegex(clean["commit"], r"^[a-f0-9]{40}$")
            (project / "src/nipat/cli.py").write_text("changed\n", encoding="utf-8")
            changed = distribution.git_source(project)
            self.assertTrue(changed["dirty"])
            self.assertEqual(changed["commit"], clean["commit"])

    def test_source_archive_without_git_has_explicit_unknown_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory))
            self.assertEqual(distribution.git_source(project), {
                "available": False, "commit": None, "dirty": None,
            })

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
                distribution.source_files(project)

    def test_manifest_rejects_escape_duplicates_and_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.make_project(Path(directory))
            manifest = project / "distribution-files.txt"
            valid = manifest.read_text(encoding="utf-8")
            for bad in ("../outside.txt", "/absolute.txt", "C:/private.txt",
                        "src\\private.txt", "src/./nipat/cli.py", "src//nipat/cli.py",
                        "pyproject.toml", "PYPROJECT.TOML", "not-existing.py", "data/sample.txt"):
                with self.subTest(entry=bad):
                    manifest.write_text(valid + bad + "\n", encoding="utf-8")
                    with self.assertRaises(ValueError):
                        distribution.source_files(project)


if __name__ == "__main__":
    unittest.main()
