import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location("publisher", Path(__file__).with_name("publish_windows_release.py"))
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)
COMMIT = "a" * 40


class ReleaseGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.setup = self.root / "setup"
        self.runtime = self.root / "runtime"
        self.setup.mkdir()
        self.runtime.mkdir()
        self.sources = {"distribution-files.txt": b"distribution-files.txt\nREADME.md\n", "README.md": b"approved\n"}
        self.manifest = {
            "schema_version": 1, "version": "0.3.0a1", "release_tag": "v0.3.0a1", "source_commit": COMMIT,
            "rootfs_provenance": {"source_commit": COMMIT},
            "source_sha256": {n: hashlib.sha256(b).hexdigest() for n, b in self.sources.items()}, "assets": {},
        }
        (self.setup / "NIPAT-Setup.exe").write_bytes(b"installer fixture")
        for key, stem in (("rootfs", "nipat-wsl-rootfs"), ("scientific_image", "nipat-scientific-runtime")):
            name = f"{stem}-0.3.0a1-amd64.tar.gz"
            path = self.runtime / name
            path.write_bytes(key.encode())
            self.manifest["assets"][key] = {"file": name, "size": path.stat().st_size, "sha256": publisher.sha256(path),
                "url": f"https://github.com/{publisher.REPO}/releases/download/v0.3.0a1/{name}"}
        self.write_manifests()

    def write_manifests(self):
        data = json.dumps(self.manifest).encode()
        for folder in (self.setup, self.runtime):
            (folder / publisher.MANIFEST).write_bytes(data)
        for folder, names in ((self.setup, ["NIPAT-Setup.exe"]), (self.runtime,
            [publisher.MANIFEST] + [a["file"] for a in self.manifest["assets"].values()])):
            (folder / "SHA256SUMS").write_text("".join(f"{publisher.sha256(folder/n)}  {n}\n" for n in names))

    def prepare(self, desktop=None):
        return publisher.prepare_assets(self.setup, self.runtime, self.root / "release", COMMIT,
                                        read_source=lambda commit, name: self.sources[name], desktop=desktop)

    def make_dual_package(self):
        self.manifest["version"] = "0.3.0a2"
        self.manifest["release_tag"] = "v0.3.0a2"
        self.manifest["runtime_image"] = "sha256:" + "b" * 64
        for entry in self.manifest["assets"].values():
            old = entry["file"]
            entry["file"] = old.replace("0.3.0a1", "0.3.0a2")
            entry["url"] = entry["url"].replace("0.3.0a1", "0.3.0a2")
            (self.runtime / old).rename(self.runtime / entry["file"])
        self.write_manifests()
        self.desktop = self.root / "desktop"
        self.desktop.mkdir()
        self.package_name = "NIPAT-DockerDesktop-0.3.0a2-windows-x64.zip"
        launcher = b"MZ launcher fixture"
        (self.setup / "NIPAT.exe").write_bytes(launcher)
        python_archive = b"portable Python fixture"
        python_hash = hashlib.sha256(python_archive).hexdigest()
        pin = patch.object(publisher, "PYTHON_SHA256", python_hash)
        pin.start()
        self.addCleanup(pin.stop)
        scientific = self.manifest["assets"]["scientific_image"]
        runtime = {
            "schema_version": 1, "image_id": self.manifest["runtime_image"],
            "source_reference": "v0.3.0a2", "os": "linux", "architecture": "amd64",
            "archive_sha256": scientific["sha256"], "archive_bytes": scientific["size"],
            "source_commit": COMMIT, "installer_manifest_sha256": publisher.sha256(self.setup / publisher.MANIFEST),
        }
        release = {
            "schema_version": 1, "package_version": "0.3.0a2",
            "source_git": {"commit": COMMIT, "dirty": False, "available": True},
            "source_sha256": self.manifest["source_sha256"], "runtime": runtime,
            "launcher": {"file": "NIPAT.exe", "sha256": hashlib.sha256(launcher).hexdigest(), "size": len(launcher)},
            "python": {"version": "3.12.10", "architecture": "amd64", "archive_sha256": python_hash},
        }
        self.package_entries = {"nipat-desktop/" + name: contents for name, contents in self.sources.items()}
        self.package_entries.update({
            "nipat-desktop/release.json": json.dumps(release).encode(),
            "nipat-desktop/NIPAT.exe": launcher,
            "nipat-desktop/.distribution/" + publisher.PYTHON_NAME: python_archive,
            "nipat-desktop/.distribution/runtime.tar": (self.runtime / scientific["file"]).read_bytes(),
            "nipat-desktop/.distribution/runtime.json": json.dumps(runtime).encode(),
        })
        self.write_package()

    def write_package(self):
        path = self.desktop / self.package_name
        with zipfile.ZipFile(path, "w") as archive:
            for name, contents in self.package_entries.items():
                archive.writestr(name, contents)
        evidence = {
            "schema_version": 1, "version": "0.3.0a2", "source_commit": COMMIT,
            "file": self.package_name, "sha256": publisher.sha256(path), "size": path.stat().st_size,
            "launcher_sha256": publisher.sha256(self.setup / "NIPAT.exe"),
        }
        (self.desktop / "package-build.json").write_text(json.dumps(evidence), encoding="utf-8")
        self.write_installer_evidence()

    def write_installer_evidence(self):
        installer = self.setup / "NIPAT-Setup.exe"
        evidence = {
            "schema_version": 1, "distribution": "self-contained-wsl",
            "version": self.manifest["version"], "source_commit": COMMIT,
            "file": "NIPAT-Setup.exe", "sha256": publisher.sha256(installer), "size": installer.stat().st_size,
            "installer_manifest_sha256": publisher.sha256(self.setup / publisher.MANIFEST),
            "launcher_sha256": publisher.sha256(self.setup / "NIPAT.exe"),
            "embedded_assets": {
                key: {field: self.manifest["assets"][key][field] for field in ("file", "sha256", "size")}
                for key in ("rootfs", "scientific_image")
            },
        }
        (self.setup / "installer-build.json").write_text(json.dumps(evidence), encoding="utf-8")

    def test_combines_both_checksum_lists_without_losing_exe(self):
        self.prepare()
        result = publisher.checksums(self.root / "release/SHA256SUMS")
        self.assertEqual(len(result), 4)
        self.assertIn("NIPAT-Setup.exe", result)
        self.assertEqual(len(list((self.root / "release").iterdir())), 5)

    def test_rejects_corrupt_asset_before_staging(self):
        asset = self.manifest["assets"]["scientific_image"]["file"]
        (self.runtime / asset).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "hash/size mismatch"):
            self.prepare()
        self.assertFalse((self.root / "release").exists())

    def test_rejects_wrong_exe_checksum(self):
        (self.setup / "NIPAT-Setup.exe").write_bytes(b"different exe")
        with self.assertRaisesRegex(ValueError, "Installer checksum"):
            self.prepare()

    def test_rejects_mixed_build_manifests(self):
        (self.runtime / publisher.MANIFEST).write_text("{}")
        with self.assertRaisesRegex(ValueError, "manifests differ"):
            self.prepare()

    def test_rejects_changed_source_and_missing_source_entry(self):
        self.sources["README.md"] = b"different source"
        with self.assertRaisesRegex(ValueError, "Source hash mismatch"):
            self.prepare()
        del self.manifest["source_sha256"]["README.md"]
        self.write_manifests()
        with self.assertRaisesRegex(ValueError, "source list"):
            self.prepare()

    def test_rejects_wrong_rootfs_provenance(self):
        self.manifest["rootfs_provenance"]["source_commit"] = "b" * 40
        self.write_manifests()
        with self.assertRaisesRegex(ValueError, "Rootfs source mismatch"):
            self.prepare()

    def test_new_release_requires_and_publishes_verified_docker_zip(self):
        self.make_dual_package()
        with self.assertRaisesRegex(ValueError, "Docker Desktop package is required"):
            self.prepare()
        self.assertFalse((self.root / "release").exists())
        self.prepare(desktop=self.desktop)
        result = publisher.checksums(self.root / "release/SHA256SUMS")
        self.assertEqual(len(result), 5)
        self.assertIn(self.package_name, result)
        self.assertNotIn("NIPAT.exe", result)  # It is included in each package, not a standalone release asset.
        self.assertEqual((self.root / "release" / self.package_name).read_bytes(),
                         (self.desktop / self.package_name).read_bytes())

    def test_new_release_requires_self_contained_installer_build_evidence(self):
        self.make_dual_package()
        (self.setup / "installer-build.json").unlink()
        with self.assertRaisesRegex(ValueError, "Missing self-contained installer build evidence"):
            self.prepare(desktop=self.desktop)
        self.assertFalse((self.root / "release").exists())

    def test_rejects_installer_bound_to_different_embedded_assets(self):
        self.make_dual_package()
        path = self.setup / "installer-build.json"
        evidence = json.loads(path.read_text())
        evidence["embedded_assets"]["rootfs"]["sha256"] = "0" * 64
        path.write_text(json.dumps(evidence))
        with self.assertRaisesRegex(ValueError, "installer build evidence mismatch"):
            self.prepare(desktop=self.desktop)

    def test_rejects_installer_companion_data_slices(self):
        self.make_dual_package()
        (self.setup / "NIPAT-Setup-1.BIN").write_bytes(b"external payload")
        with self.assertRaisesRegex(ValueError, "companion data slices"):
            self.prepare(desktop=self.desktop)

    def test_rejects_installer_evidence_from_another_build(self):
        self.make_dual_package()
        path = self.setup / "installer-build.json"
        original = json.loads(path.read_text())
        for key, value in (("sha256", "0" * 64), ("source_commit", "e" * 40),
                           ("installer_manifest_sha256", "f" * 64), ("distribution", "download-only")):
            with self.subTest(key=key):
                evidence = copy.deepcopy(original)
                evidence[key] = value
                path.write_text(json.dumps(evidence))
                with self.assertRaisesRegex(ValueError, "installer build evidence mismatch"):
                    self.prepare(desktop=self.desktop)

    def test_installer_size_limit_is_checked_before_hashing(self):
        limit = (self.setup / "NIPAT-Setup.exe").stat().st_size
        with patch.object(publisher, "MAX_ASSET_BYTES", limit), \
                self.assertRaisesRegex(ValueError, ">= 2 GiB file: NIPAT-Setup.exe"):
            self.prepare()
        self.assertFalse((self.root / "release").exists())

    def test_rejects_docker_zip_corruption_against_build_evidence(self):
        self.make_dual_package()
        with (self.desktop / self.package_name).open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "build hash/source/version"):
            self.prepare(desktop=self.desktop)
        self.assertFalse((self.root / "release").exists())

    def test_rejects_docker_source_different_from_verified_commit(self):
        self.make_dual_package()
        self.package_entries["nipat-desktop/README.md"] = b"changed source"
        self.write_package()
        with self.assertRaisesRegex(ValueError, "content hash mismatch: README"):
            self.prepare(desktop=self.desktop)

    def test_rejects_extra_docker_files_even_with_matching_outer_hash(self):
        self.make_dual_package()
        self.package_entries["nipat-desktop/data/patient.txt"] = b"unapproved data"
        self.write_package()
        with self.assertRaisesRegex(ValueError, "unexpected files"):
            self.prepare(desktop=self.desktop)

    def test_rejects_docker_launcher_different_from_wsl_launcher(self):
        self.make_dual_package()
        self.package_entries["nipat-desktop/NIPAT.exe"] = b"MZ different binary"
        self.write_package()
        with self.assertRaisesRegex(ValueError, "Docker launcher size|content hash mismatch: NIPAT"):
            self.prepare(desktop=self.desktop)

    def test_rejects_different_scientific_archive_inside_docker_package(self):
        self.make_dual_package()
        data = self.package_entries["nipat-desktop/.distribution/runtime.tar"]
        self.package_entries["nipat-desktop/.distribution/runtime.tar"] = b"x" * len(data)
        self.write_package()
        with self.assertRaisesRegex(ValueError, "content hash mismatch: .distribution/runtime.tar"):
            self.prepare(desktop=self.desktop)

    def test_rejects_mixed_docker_package_release_metadata(self):
        self.make_dual_package()
        entry = "nipat-desktop/release.json"
        original = json.loads(self.package_entries[entry])
        for key, changed in (("source_git", {"commit": "d" * 40, "dirty": False, "available": True}),
                             ("package_version", "0.3.0a1"), ("runtime", {}), ("python", {})):
            with self.subTest(key=key):
                release = copy.deepcopy(original)
                release[key] = changed
                self.package_entries[entry] = json.dumps(release).encode()
                self.write_package()
                with self.assertRaises(ValueError):
                    self.prepare(desktop=self.desktop)

    def test_real_bundle_builder_matches_publication_protocol(self):
        self.make_dual_package()
        script = Path(__file__).resolve().parents[2] / "scripts/build_validation_bundle.py"
        spec = importlib.util.spec_from_file_location("release_bundle_integration", script)
        bundle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bundle)
        self.sources.update({name: b"fixture\n" for name in
                             ("1_SETUP.cmd", "2_AVVIA.cmd", "nipat.cmd", "compose.yaml")})
        self.sources["pyproject.toml"] = b'[project]\nversion = "0.3.0a2"\n'
        self.sources["distribution-files.txt"] = ("\n".join(sorted(self.sources)) + "\n").encode()
        project = self.root / "project"
        project.mkdir()
        for name, content in self.sources.items():
            (project / name).write_bytes(content)
        self.manifest["source_sha256"] = {name: hashlib.sha256(content).hexdigest()
                                          for name, content in self.sources.items()}
        scientific = self.manifest["assets"]["scientific_image"]
        scientific_path = self.runtime / scientific["file"]
        scientific_path.write_bytes(gzip.compress(b"scientific fixture", mtime=0))
        scientific.update(sha256=publisher.sha256(scientific_path), size=scientific_path.stat().st_size)
        self.write_manifests()
        header = bytearray(154)
        header[:2] = b"MZ"
        struct.pack_into("<I", header, 60, 128)
        header[128:132] = b"PE\0\0"
        struct.pack_into("<H", header, 132, 0x8664)
        struct.pack_into("<H", header, 152, 0x20B)
        launcher = self.setup / "NIPAT.exe"
        launcher.write_bytes(header)
        python_zip = self.root / "python.zip"
        python_zip.write_bytes(b"portable Python fixture")
        package = self.desktop / self.package_name
        package.unlink()
        with patch.object(bundle, "git_source", return_value={"commit": COMMIT, "dirty": False, "available": True}), \
                patch.object(bundle, "PYTHON_SHA256", publisher.PYTHON_SHA256):
            runtime, metadata = bundle.verified_installer_runtime(project, scientific_path, self.setup / publisher.MANIFEST)
            bundle.package_sources(project, package, python_zip, runtime, metadata, launcher)
        evidence = {
            "schema_version": 1, "version": "0.3.0a2", "source_commit": COMMIT,
            "file": self.package_name, "sha256": publisher.sha256(package), "size": package.stat().st_size,
            "launcher_sha256": publisher.sha256(launcher),
        }
        (self.desktop / "package-build.json").write_text(json.dumps(evidence), encoding="utf-8")
        self.write_installer_evidence()
        self.prepare(desktop=self.desktop)
        self.assertEqual(publisher.checksums(self.root / "release/SHA256SUMS")[self.package_name],
                         publisher.sha256(package))

    def test_build_must_be_successful_same_source_and_not_from_a_fork(self):
        run = {"id": 123, "head_sha": COMMIT, "status": "completed", "conclusion": "success", "event": "push",
               "path": ".github/workflows/windows-installer.yml", "repository": {"full_name": publisher.REPO},
               "head_repository": {"full_name": publisher.REPO}}
        publisher.validate_run(run, COMMIT, 123)
        for key, value in (("head_sha", "b" * 40), ("conclusion", "failure"), ("event", "pull_request"),
                           ("head_repository", {"full_name": "someone/fork"})):
            altered = copy.deepcopy(run)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                publisher.validate_run(altered, COMMIT, 123)

    def test_resume_requires_matching_draft_and_uploaded_digests(self):
        path = self.setup / "NIPAT-Setup.exe"
        files = {path.name: path}
        release = {"draft": True, "prerelease": True, "target_commitish": COMMIT,
                   "tag_name": "v0.3.0a1", "body": "notes", "assets": []}
        publisher.verify_uploaded(release, files, COMMIT, "v0.3.0a1", "notes")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            publisher.verify_uploaded(release, files, COMMIT, "v0.3.0a1", "notes", complete=True)
        release["assets"] = [{"name": path.name, "state": "uploaded", "size": path.stat().st_size,
                              "digest": f"sha256:{publisher.sha256(path)}"}]
        publisher.verify_uploaded(release, files, COMMIT, "v0.3.0a1", "notes", complete=True)
        release["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "integrity"):
            publisher.verify_uploaded(release, files, COMMIT, "v0.3.0a1", "notes")
        release["draft"] = False
        with self.assertRaisesRegex(ValueError, "not a draft"):
            publisher.verify_uploaded(release, files, COMMIT, "v0.3.0a1", "notes")

    def test_create_retains_response_id_without_waiting_for_release_list(self):
        payload = self.root / "create.json"
        response = {"id": 12345, "draft": True, "target_commitish": COMMIT}
        with patch.object(publisher, "command", return_value=json.dumps(response)) as call, \
                patch.object(publisher, "find_release", side_effect=AssertionError("list may be stale")):
            result = publisher.create_draft("v0.3.0a1", "0.3.0a1", COMMIT, "line one\nline two", payload)
        self.assertEqual(result["id"], 12345)
        sent = json.loads(payload.read_text())
        self.assertEqual(sent["target_commitish"], COMMIT)
        self.assertEqual(sent["body"], "line one\nline two")
        self.assertTrue(sent["draft"])
        self.assertTrue(sent["prerelease"])
        self.assertEqual(call.call_count, 1)


if __name__ == "__main__":
    unittest.main()
