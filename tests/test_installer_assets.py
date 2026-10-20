"""Exercise trust metadata, selective staging, and lossless asset exports."""

import copy
import gzip
import hashlib
import io
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "installer_assets", Path(__file__).resolve().parents[1]
    / "scripts" / "build_windows_installer_assets.py",
)
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)
PROVENANCE_SPEC = importlib.util.spec_from_file_location(
    "runtime_provenance", Path(__file__).resolve().parents[1]
    / "installer" / "runtime" / "write-provenance.py",
)
provenance = importlib.util.module_from_spec(PROVENANCE_SPEC)
PROVENANCE_SPEC.loader.exec_module(provenance)

COMMIT = "a" * 40
SCIENTIFIC = "sha256:" + "b" * 64
ROOTFS = "sha256:" + "c" * 64


class InstallerAssetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "pyproject.toml").write_text(
            '[project]\nversion = "0.3.0a1"\n', encoding="utf-8",
        )
        (self.project / "README.md").write_text("Approved source\n", encoding="utf-8")
        (self.project / "distribution-files.txt").write_text(
            "distribution-files.txt\npyproject.toml\nREADME.md\n", encoding="utf-8",
        )
        (self.project / "private-local.txt").write_text("not selected", encoding="utf-8")
        self.rootfs = self.root / "rootfs.tar.gz"
        self.scientific = self.root / "scientific.tar.gz"
        self.rootfs.write_bytes(gzip.compress(b"rootfs fixture", mtime=0))
        self.scientific.write_bytes(gzip.compress(b"scientific fixture", mtime=0))
        self.provenance = {
            "schema_version": 1, "vendor": "nipat-desktop", "source_commit": COMMIT,
            "base_image": "debian@sha256:" + "d" * 64,
        }
        self.manifest = assets.make_manifest(
            self.project, source_commit=COMMIT, runtime_image=SCIENTIFIC,
            rootfs=self.rootfs, scientific_image=self.scientific,
            rootfs_provenance=self.provenance,
        )
        self.manifest_path = self.root / assets.MANIFEST_NAME
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.python_archive = self.root / "python.zip"
        self.python_archive.write_bytes(b"python archive fixture")

    def test_manifest_identifies_exact_sources_and_assets(self):
        assets.validate_manifest(self.manifest)
        self.assertEqual(self.manifest["source_commit"], COMMIT)
        self.assertEqual(self.manifest["runtime_image"], SCIENTIFIC)
        self.assertEqual(set(self.manifest["source_sha256"]), {
            "distribution-files.txt", "pyproject.toml", "README.md",
        })
        for key, path in [("rootfs", self.rootfs), ("scientific_image", self.scientific)]:
            entry = self.manifest["assets"][key]
            self.assertEqual(entry["sha256"], assets.bundle.sha256_file(path))
            self.assertEqual(entry["size"], path.stat().st_size)
            self.assertEqual(entry["url"],
                             "https://github.com/GregorioDalia/nipat-desktop/releases/"
                             f"download/v0.3.0a1/{path.name}")

    def test_manifest_and_stage_accept_noncanonical_project_root(self):
        prior_directory = Path.cwd()
        try:
            os.chdir(self.root)
            manifest = assets.make_manifest(
                Path("project"), source_commit=COMMIT, runtime_image=SCIENTIFIC,
                rootfs=self.rootfs, scientific_image=self.scientific,
                rootfs_provenance=self.provenance,
            )
            self.assertEqual(manifest["source_sha256"], self.manifest["source_sha256"])
            with patch.object(assets.bundle, "require_python_archive"):
                app = assets.stage_app(Path("project"), self.manifest_path,
                                       self.root / "relative-stage", self.python_archive)
            self.assertTrue((app / "README.md").is_file())
        finally:
            os.chdir(prior_directory)

    def test_manifest_rejects_provenance_from_another_source(self):
        provenance = dict(self.provenance, source_commit="e" * 40)
        with self.assertRaisesRegex(ValueError, "provenienza"):
            assets.make_manifest(
                self.project, source_commit=COMMIT, runtime_image=SCIENTIFIC,
                rootfs=self.rootfs, scientific_image=self.scientific,
                rootfs_provenance=provenance,
            )

    def test_engine_notices_match_installed_version_and_record_exact_bytes(self):
        payloads = (b"license fixture", b"notice fixture")
        with patch.object(provenance.urllib.request, "urlopen", side_effect=[
            io.BytesIO(content) for content in payloads
        ]) as request:
            record = provenance.collect_engine_notices(
                "Docker version 29.9.1, build dfc520d", self.root / "engine-docs",
            )
        self.assertEqual(record["source_tag"], "docker-v29.9.1")
        self.assertEqual([call.args[0] for call in request.call_args_list], [
            "https://raw.githubusercontent.com/moby/moby/docker-v29.9.1/LICENSE",
            "https://raw.githubusercontent.com/moby/moby/docker-v29.9.1/NOTICE",
        ])
        for entry, content in zip(record["files"], payloads):
            self.assertEqual(Path(entry["path"]).read_bytes(), content)
            self.assertEqual(entry["sha256"], hashlib.sha256(content).hexdigest())

    def test_engine_notices_fail_clearly_when_version_or_upstream_is_unavailable(self):
        with self.assertRaisesRegex(ValueError, "Cannot identify"):
            provenance.collect_engine_notices("unknown", self.root / "engine-docs")
        with patch.object(provenance.urllib.request, "urlopen", side_effect=OSError("not found")):
            with self.assertRaisesRegex(ValueError, "Cannot preserve.*docker-v29.9.1/LICENSE"):
                provenance.collect_engine_notices(
                    "Docker version 29.9.1, build dfc520d", self.root / "engine-docs",
                )

    def test_asset_rejects_empty_uncompressed_and_oversized_files(self):
        path = self.root / "invalid.tar.gz"
        for content in (b"", b"not gzip"):
            path.write_bytes(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                assets.asset_metadata(path, "v0.3.0a1")
        with patch.object(assets, "MAX_ASSET_BYTES", self.rootfs.stat().st_size):
            with self.assertRaisesRegex(ValueError, "2 GiB"):
                assets.asset_metadata(self.rootfs, "v0.3.0a1")

    def test_manifest_rejects_untrusted_or_invalid_download_metadata(self):
        mutations = [
            ("url", "https://other.example/rootfs.tar.gz"),
            ("file", "../rootfs.tar.gz"),
            ("sha256", "b" * 63),
            ("size", 2 * 1024**3),
            ("size", True),
        ]
        for key, value in mutations:
            manifest = copy.deepcopy(self.manifest)
            manifest["assets"]["rootfs"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                assets.validate_manifest(manifest)
        for key, value in [("source_commit", "main"), ("runtime_image", "latest"),
                           ("release_tag", "v0.4.0")]:
            manifest = dict(self.manifest, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                assets.validate_manifest(manifest)

    def test_stage_copies_only_verified_allowlist_and_embedded_manifest(self):
        with patch.object(assets.bundle, "require_python_archive") as verify_python:
            app = assets.stage_app(self.project, self.manifest_path,
                                   self.root / "stage", self.python_archive)
        verify_python.assert_called_once_with(self.python_archive)
        self.assertFalse((app / "private-local.txt").exists())
        self.assertEqual((app / "README.md").read_text(), "Approved source\n")
        self.assertEqual((app / ".distribution" / assets.MANIFEST_NAME).read_bytes(),
                         self.manifest_path.read_bytes())
        release = json.loads((app / "release.json").read_text())
        self.assertEqual(release["source_git"]["commit"], COMMIT)
        self.assertEqual(release["runtime"]["image_id"], SCIENTIFIC)

    def test_stage_rejects_modified_sources_before_creating_output(self):
        (self.project / "README.md").write_text("changed", encoding="utf-8")
        stage = self.root / "stage"
        with self.assertRaisesRegex(ValueError, "sorgenti"):
            assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
        self.assertFalse(stage.exists())

    def test_stage_never_overwrites_existing_destination(self):
        stage = self.root / "stage"
        stage.mkdir()
        sentinel = stage / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with patch.object(assets.bundle, "require_python_archive"):
            with self.assertRaises(FileExistsError):
                assets.stage_app(self.project, self.manifest_path, stage, self.python_archive)
        self.assertEqual(sentinel.read_text(), "keep")

    def test_streamed_export_is_lossless_and_preserves_existing_target(self):
        target = self.root / "export.tar.gz"
        command = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'payload' * 1024)"]
        assets.gzip_export(command, target)
        self.assertEqual(gzip.decompress(target.read_bytes()), b"payload" * 1024)
        before = target.read_bytes()
        with self.assertRaises(FileExistsError):
            assets.gzip_export(command, target)
        self.assertEqual(target.read_bytes(), before)

    def test_failed_export_removes_only_new_partial_asset(self):
        target = self.root / "failure.tar.gz"
        command = [sys.executable, "-c",
                   "import sys; sys.stdout.write('partial'); sys.stderr.write('failure'); sys.exit(3)"]
        with self.assertRaisesRegex(RuntimeError, "failure"):
            assets.gzip_export(command, target)
        self.assertFalse(target.exists())

    def test_image_inspection_rejects_wrong_architecture(self):
        details = {"Id": SCIENTIFIC, "Os": "linux", "Architecture": "arm64"}
        with patch.object(assets.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, json.dumps([details]), "")):
            with self.assertRaisesRegex(ValueError, "amd64"):
                assets.inspect_image("image:mutable-tag")

    def test_export_uses_immutable_ids_and_never_starts_exported_container(self):
        identifier = "f" * 64
        commands = []
        exported = []

        def run(command, **kwargs):
            commands.append(command)
            if command[:2] == ["docker", "create"]:
                output = identifier
            elif command[:2] == ["docker", "run"]:
                output = json.dumps(self.provenance)
            else:
                output = ""
            return subprocess.CompletedProcess(command, 0, output, "")

        def export(command, destination):
            exported.append(command)
            destination.write_bytes(gzip.compress(b"export fixture", mtime=0))

        with patch.object(assets.bundle, "git_source", return_value={"commit": COMMIT, "dirty": False}), \
             patch.object(assets, "inspect_image", side_effect=[{"Id": SCIENTIFIC}, {"Id": ROOTFS}]), \
             patch.object(assets.subprocess, "run", side_effect=run), \
             patch.object(assets, "gzip_export", side_effect=export):
            output = assets.export_assets(
                self.project, self.root / "assets", source_commit=COMMIT,
                scientific_reference="scientific:tag", rootfs_reference="rootfs:tag",
            )
        self.assertEqual(exported, [["docker", "image", "save", SCIENTIFIC],
                                    ["docker", "container", "export", identifier]])
        self.assertIn(["docker", "create", ROOTFS], commands)
        self.assertIn(["docker", "container", "rm", "--force", identifier], commands)
        self.assertFalse(any("start" in command for command in commands))
        manifest = json.loads(output.read_text())
        self.assertEqual(manifest["rootfs_provenance"]["rootfs_image_id"], ROOTFS)
        assets.validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
