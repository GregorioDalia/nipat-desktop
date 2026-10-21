"""Verify the single-EXE Docker staging and its release evidence without Windows."""

import gzip
import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "docker_installer", Path(__file__).resolve().parents[1] / "scripts/build_docker_installer.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class DockerInstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        project = self.root / "project"
        project.mkdir()
        sources = {
            "pyproject.toml": '[project]\nversion = "0.4.1"\n',
            "compose.yaml": "services: {}\n", "1_SETUP.cmd": "@echo off\n",
            "2_AVVIA.cmd": "@echo off\n", "nipat.cmd": "@echo off\n", "LICENSE": "fixture\n",
            "installer/windows/NIPAT-DockerDesktop.iss": "[Setup]\nDiskSpanning=no\n",
        }
        sources["distribution-files.txt"] = "\n".join(sorted({*sources, "distribution-files.txt"})) + "\n"
        for name, content in sources.items():
            destination = project / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
        self.launcher = self.root / "NIPAT.exe"
        pe = bytearray(128)
        pe[:2] = b"MZ"
        struct.pack_into("<I", pe, 0x3C, 64)
        pe[64:68] = b"PE\x00\x00"
        struct.pack_into("<H", pe, 68, 0x8664)
        struct.pack_into("<H", pe, 88, 0x20B)
        self.launcher.write_bytes(pe)
        python = self.root / installer.bundle.PYTHON_NAME
        python.write_bytes(b"python fixture")
        self.addCleanup(patch.stopall)
        patch.object(installer.bundle, "PYTHON_SHA256", hashlib.sha256(python.read_bytes()).hexdigest()).start()
        patch.object(installer.bundle, "git_source", return_value={
            "commit": "a" * 40, "dirty": False, "available": True,
        }).start()
        scientific = self.root / "scientific.tar.gz"
        rootfs = self.root / "rootfs.tar.gz"
        scientific.write_bytes(gzip.compress(b"scientific fixture", mtime=0))
        rootfs.write_bytes(gzip.compress(b"rootfs fixture", mtime=0))
        self.manifest = installer.assets.make_manifest(
            project, source_commit="a" * 40, runtime_image="sha256:" + "b" * 64,
            rootfs=rootfs, scientific_image=scientific,
            rootfs_provenance={"schema_version": 1, "vendor": "nipat-desktop", "source_commit": "a" * 40},
        )
        self.manifest_path = self.root / "installer-manifest.json"
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        runtime = {
            "schema_version": 1, "image_id": self.manifest["runtime_image"],
            "source_reference": "v0.4.1", "os": "linux", "architecture": "amd64",
            "archive_sha256": installer.bundle.sha256_file(scientific),
            "archive_bytes": scientific.stat().st_size, "source_commit": "a" * 40,
            "installer_manifest_sha256": installer.bundle.sha256_file(self.manifest_path),
        }
        self.package = self.root / "NIPAT-DockerDesktop-0.4.1-windows-x64.zip"
        installer.bundle.package_sources(project, self.package, python, scientific, runtime, self.launcher)
        self.refresh_package_record()
        self.stage = self.root / "stage"
        self.arguments = (self.package, self.manifest_path, self.launcher, self.stage)

    def refresh_package_record(self):
        record = {
            "schema_version": 1, "version": "0.4.1", "source_commit": "a" * 40,
            "file": self.package.name, "size": self.package.stat().st_size,
            "sha256": installer.bundle.sha256_file(self.package),
            "launcher_sha256": installer.bundle.sha256_file(self.launcher),
        }
        (self.root / "package-build.json").write_text(json.dumps(record), encoding="utf-8")

    def rewrite_package(self, transform):
        with zipfile.ZipFile(self.package) as archive:
            files = [(entry, archive.read(entry.filename)) for entry in archive.infolist()]
        with zipfile.ZipFile(self.package, "w") as archive:
            for entry, data in files:
                name, data = transform(entry.filename, data)
                archive.writestr(name, data)
        self.refresh_package_record()

    def test_verified_bundle_stages_and_records_the_exact_inputs(self):
        record = installer.stage_package(*self.arguments)
        self.assertEqual(record, installer.verify_stage(*self.arguments))
        self.assertEqual((self.stage / "app" / installer.MARKER_NAME).read_bytes(), installer.MARKER_BYTES)
        self.assertFalse((self.stage / "app/.runtime/backend.json").exists())
        recipe = (self.stage / installer.FILES_INCLUDE).read_text(encoding="utf-8")
        self.assertEqual(recipe.count('Hash: "'), len(record["staged_files_sha256"]))
        runtime_line = next(line for line in recipe.splitlines() if "runtime.tar" in line)
        self.assertIn("nocompression solidbreak", runtime_line)
        self.assertNotIn("recursesubdirs", recipe)
        output = self.root / "output"
        output.mkdir()
        (output / installer.INSTALLER_NAME).write_bytes(b"MZ compiled fixture")
        evidence = json.loads(installer.record_installer(*self.arguments, output).read_text(encoding="utf-8"))
        self.assertEqual(evidence["staged_files_sha256"], record["staged_files_sha256"])
        self.assertEqual(evidence["package_sha256"], installer.bundle.sha256_file(self.package))
        self.assertEqual(evidence["sha256"], installer.bundle.sha256_file(output / installer.INSTALLER_NAME))

    def test_unexpected_or_traversing_zip_member_is_rejected_before_extraction(self):
        self.rewrite_package(lambda name, data: ("nipat-desktop/../../outside" if name.endswith("LICENSE") else name, data))
        with self.assertRaisesRegex(ValueError, "non previsti"):
            installer.stage_package(*self.arguments)
        self.assertFalse(self.stage.exists())
        self.assertFalse((self.root / "outside").exists())

    def test_modified_sources_are_rejected_even_with_updated_zip_hash(self):
        self.rewrite_package(lambda name, data: (name, b"tampered" if name.endswith("LICENSE") else data))
        with self.assertRaisesRegex(ValueError, "Checksum.*LICENSE"):
            installer.stage_package(*self.arguments)
        self.assertFalse(self.stage.exists())

    def test_other_runtime_metadata_is_rejected(self):
        def modify(name, data):
            if name.endswith(".distribution/runtime.json"):
                value = json.loads(data)
                value["image_id"] = "sha256:" + "c" * 64
                data = json.dumps(value).encode()
            return name, data
        self.rewrite_package(modify)
        with self.assertRaisesRegex(ValueError, "metadati"):
            installer.stage_package(*self.arguments)

    def test_different_tested_launcher_is_rejected(self):
        self.launcher.write_bytes(self.launcher.read_bytes() + b"different")
        self.refresh_package_record()
        with self.assertRaisesRegex(ValueError, "metadati"):
            installer.stage_package(*self.arguments)

    def test_changed_stage_or_inno_recipe_cannot_produce_evidence(self):
        installer.stage_package(*self.arguments)
        for relative in ("app/LICENSE", "app/.distribution/docker-desktop.json", installer.FILES_INCLUDE):
            with self.subTest(relative=relative):
                path = self.stage / relative
                original = path.read_bytes()
                path.write_bytes(original + b"modified")
                with self.assertRaises(ValueError):
                    installer.verify_stage(*self.arguments)
                path.write_bytes(original)
        (self.stage / "app/untracked.txt").write_text("not approved", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non previsti"):
            installer.verify_stage(*self.arguments)

    def test_staging_refuses_existing_directory(self):
        self.stage.mkdir()
        (self.stage / "existing.txt").write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            installer.stage_package(*self.arguments)
        self.assertEqual((self.stage / "existing.txt").read_text(), "keep")

    def test_split_or_non_executable_installer_is_rejected(self):
        installer.stage_package(*self.arguments)
        output = self.root / "output"
        output.mkdir()
        executable = output / installer.INSTALLER_NAME
        executable.write_bytes(b"MZ compiled fixture")
        companion = output / "data.BIN"
        companion.write_bytes(b"split")
        with self.assertRaisesRegex(ValueError, "senza file .bin"):
            installer.record_installer(*self.arguments, output)
        companion.unlink()
        executable.write_bytes(b"not an executable")
        with self.assertRaisesRegex(ValueError, "eseguibile Windows"):
            installer.record_installer(*self.arguments, output)
        executable.write_bytes(b"MZ compiled fixture")
        verified = installer.verify_stage(*self.arguments)
        with patch.object(installer, "verify_stage", return_value=verified), \
                patch.object(installer, "MAX_BYTES", executable.stat().st_size):
            with self.assertRaisesRegex(ValueError, ">= 2 GiB"):
                installer.record_installer(*self.arguments, output)
        self.assertFalse((output / installer.EVIDENCE_NAME).exists())

    def test_windows_and_inno_ambiguous_paths_are_rejected(self):
        for name in ("../outside", "absolute:file", "dir\\file", 'bad"name', "trailing./file", "NUL.txt", "{app}/file", "dir/*"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                installer._path(name)


if __name__ == "__main__":
    unittest.main()
