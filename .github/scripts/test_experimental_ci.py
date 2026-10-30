"""Experimental build evidence must never stand in for stable or desktop approval."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


verify = load("verify_experimental_installers")
source = load("verify_experimental_source")
downloads = load("experimental_downloads")


class ExperimentalIdentityTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "schema_version": 1, "version": "0.8.0a1", "release_tag": "v0.8.0a1",
            "source_commit": "a" * 40, "installation_profile": dict(verify.PROFILE),
            "assets": {"rootfs": {}, "scientific_image": {"sha256": "b" * 64}},
        }

    def test_isolated_prerelease_identity_is_accepted(self):
        verify.validate_identity(self.manifest, "a" * 40)
        source.validate_dispatch("workflow_dispatch", "refs/heads/experiment/0.8-portability",
                                 "0.8.0a1", verify.PROFILE)

    def test_stable_or_wrong_source_cannot_enter_experimental_contract(self):
        for field, value in (("version", "0.8.0"), ("version", "0.7.2"),
                             ("source_commit", "c" * 40), ("release_tag", "v0.7.2"),
                             ("installation_profile", {**verify.PROFILE, "channel": "desktop"})):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                verify.validate_identity({**self.manifest, field: value}, "a" * 40)

    def test_pr_push_main_and_nonexperimental_dispatch_are_rejected(self):
        for event, ref in (("pull_request", "refs/pull/42/merge"),
                           ("push", "refs/heads/experiment/0.8-portability"),
                           ("workflow_dispatch", "refs/heads/main"),
                           ("workflow_dispatch", "refs/heads/unreviewed")):
            with self.subTest(event=event, ref=ref), self.assertRaises(ValueError):
                source.validate_dispatch(event, ref, "0.8.0a1", verify.PROFILE)

    def test_mac_package_is_bound_to_architecture_source_archive_and_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            package = folder / "NIPAT-Experimental-0.8.0a1-macos-arm64.pkg"
            package.write_bytes(b"package verified on native runner")
            report = {
                "verified": True, "platform": "darwin", "architecture": "arm64", "version": "0.8.0a1",
                "source_commit": "a" * 40, "scientific_asset_sha256": "b" * 64,
                "runtime_vm_qualified": False, "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            }
            path = folder / "macos-package-verification.json"
            path.write_text(json.dumps(report))
            verify.verify_macos(folder, "arm64", self.manifest)
            for key, value in (("verified", 1), ("architecture", "x86_64"), ("source_commit", "d" * 40),
                               ("scientific_asset_sha256", "e" * 64), ("package_sha256", "f" * 64),
                               ("runtime_vm_qualified", True), ("runtime_vm_qualified", 0)):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    path.write_text(json.dumps({**report, key: value}))
                    verify.verify_macos(folder, "arm64", self.manifest)
            path.write_text(json.dumps(report))
            package.write_bytes(b"replaced after verification")
            with self.assertRaises(ValueError):
                verify.verify_macos(folder, "arm64", self.manifest)


class DownloadIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "publication_authorized": False, "desktop_acceptance": False,
            "windows": {"file": "NIPAT-Setup.exe", "sha256": "a" * 64},
            "macos": {"arm64": {"file": "arm64.pkg", "sha256": "b" * 64},
                      "x86_64": {"file": "intel.pkg", "sha256": "c" * 64}},
        }
        self.environment = {}
        for prefix, digest in (("WINDOWS", "a"), ("ARM64", "b"), ("INTEL", "c")):
            self.environment[prefix + "_SHA256"] = digest * 64
            self.environment[prefix + "_URL"] = "https://github.com/GregorioDalia/nipat-desktop/actions/runs/123/artifacts/456"

    def test_all_three_direct_uploads_must_match_verified_bytes(self):
        self.assertEqual(len(downloads.download_rows(self.record, self.environment)), 3)
        for prefix in ("WINDOWS", "ARM64", "INTEL"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                downloads.download_rows(self.record, {**self.environment, prefix + "_SHA256": "d" * 64})

    def test_package_review_does_not_authorize_publication_or_desktop_acceptance(self):
        for field in ("publication_authorized", "desktop_acceptance"):
            changed = copy.deepcopy(self.record)
            changed[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                downloads.download_rows(changed, self.environment)


class WindowsExperimentalEvidenceTests(unittest.TestCase):
    """Exercise the whole experimental Windows verifier with independently bound inputs."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.windows, self.assets = root / "windows", root / "assets"
        self.windows.mkdir()
        self.assets.mkdir()
        self.sources = {
            "pyproject.toml": b'[project]\nversion = "0.8.0a1"\n',
            "installer/windows/install-profile.json": json.dumps(verify.PROFILE).encode(),
        }
        self.sources["distribution-files.txt"] = "\n".join(sorted({*self.sources, "distribution-files.txt"})).encode()
        self.manifest = {
            "schema_version": 1, "version": "0.8.0a1", "release_tag": "v0.8.0a1",
            "source_commit": "a" * 40, "installation_profile": dict(verify.PROFILE),
            "rootfs_provenance": {"source_commit": "a" * 40},
            "source_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in self.sources.items()},
            "assets": {},
        }
        for kind, stem in (("rootfs", "nipat-wsl-rootfs"), ("scientific_image", "nipat-scientific-runtime")):
            filename = f"{stem}-0.8.0a1-amd64.tar.gz"
            archive = self.assets / filename
            archive.write_bytes(kind.encode())
            self.manifest["assets"][kind] = {
                "file": filename, "sha256": verify.digest(archive), "size": archive.stat().st_size,
                "url": f"https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.0a1/{filename}",
            }
        raw = json.dumps(self.manifest).encode()
        for folder in (self.windows, self.assets):
            (folder / "installer-manifest.json").write_bytes(raw)
        setup = self.windows / "NIPAT-Setup.exe"
        launcher = self.windows / "NIPAT.exe"
        setup.write_bytes(b"MZ setup test fixture")
        launcher.write_bytes(b"MZ launcher test fixture")
        (self.windows / "SHA256SUMS").write_text(f"{verify.digest(setup)}  NIPAT-Setup.exe\n")
        runtime_hashes = {"installer-manifest.json": hashlib.sha256(raw).hexdigest()}
        runtime_hashes.update({value["file"]: value["sha256"] for value in self.manifest["assets"].values()})
        (self.assets / "SHA256SUMS").write_text("".join(f"{value}  {name}\n" for name, value in runtime_hashes.items()))
        self.record = {
            "schema_version": 1, "distribution": "self-contained-wsl", "version": "0.8.0a1",
            "source_commit": "a" * 40, "file": setup.name, "sha256": verify.digest(setup),
            "size": setup.stat().st_size, "installer_manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "launcher_sha256": verify.digest(launcher), "installation_profile": dict(verify.PROFILE),
            "embedded_assets": {key: {field: value[field] for field in ("file", "sha256", "size")}
                                for key, value in self.manifest["assets"].items()},
        }
        (self.windows / "installer-build.json").write_text(json.dumps(self.record))

    def verify(self):
        return verify.verify_windows(self.windows, self.assets, "a" * 40,
                                     read_source=lambda commit, name: self.sources[name])

    def test_accepts_the_exact_isolated_package_without_publication(self):
        manifest, installer = self.verify()
        self.assertEqual(manifest, self.manifest)
        self.assertEqual(installer["sha256"], self.record["sha256"])

    def test_modified_source_archive_or_installer_is_rejected(self):
        self.sources["pyproject.toml"] += b"# changed\n"
        with self.assertRaisesRegex(ValueError, "Source bytes differ"):
            self.verify()
        self.sources["pyproject.toml"] = b'[project]\nversion = "0.8.0a1"\n'
        archive = self.assets / self.manifest["assets"]["scientific_image"]["file"]
        archive.write_bytes(b"replacement scientific archive")
        with self.assertRaisesRegex(ValueError, "archive changed"):
            self.verify()
        archive.write_bytes(b"scientific_image")
        (self.windows / "NIPAT-Setup.exe").write_bytes(b"replacement setup")
        with self.assertRaisesRegex(ValueError, "checksum differs"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
