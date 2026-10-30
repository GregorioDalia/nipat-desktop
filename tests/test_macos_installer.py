"""Cross-platform package contracts; these fixtures do not qualify a macOS VM."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]


def module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT / path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


builder = module("test_mac_builder", "scripts/build_macos_installer.py")
verifier = module("test_mac_verifier", "scripts/verify_macos_package.py")
launcher = module("test_mac_launcher", "installer/macos/launch.py")


def archive(path: Path, entries: list[tuple[str, bytes | None, str | None]]) -> Path:
    with tarfile.open(path, "w:gz") as output:
        for name, data, link in entries:
            member = tarfile.TarInfo(name)
            member.mode = 0o755
            if link is not None:
                member.type = tarfile.SYMTYPE
                member.linkname = link
                output.addfile(member)
            elif data is None:
                member.type = tarfile.DIRTYPE
                output.addfile(member)
            else:
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))
    return path


class MacInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self):
        if os.name == "nt":
            self.skipTest("macOS payload fixtures preserve POSIX symlinks and executable modes")
        project = self.root / "project"
        project.mkdir()
        for relative, contents in {
            "installer/macos/NIPAT.command": "#!/bin/sh\nexit 0\n",
            "src/nipat/__init__.py": '__version__ = "0.8.0a1"\n',
            "LICENSE": "Fixture license\n",
        }.items():
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        files = sorted(path for path in project.rglob("*") if path.is_file())
        scientific = self.root / "nipat-scientific.tar.gz"
        scientific.write_bytes(b"\x1f\x8bfixture-scientific-content")
        common = {
            "version": "0.8.0a1", "release_tag": "v0.8.0a1", "source_commit": "a" * 40,
            "runtime_image": "sha256:" + "b" * 64,
            "source_sha256": {path.relative_to(project).as_posix(): builder.bundle.sha256_file(path)
                              for path in files},
            "assets": {"scientific_image": {
                "file": scientific.name, "sha256": builder.bundle.sha256_file(scientific),
                "size": scientific.stat().st_size}},
        }
        python = archive(self.root / "python.tar.gz", [
            ("python/bin/python3.12", b"fixture native python", None),
            ("python/lib/python3.12/LICENSE.txt", b"Fixture Python license", None),
            ("python/bin/python3", None, "python3.12")])
        lima = archive(self.root / "lima.tar.gz", [
            ("bin/limactl", b"fixture native lima", None),
            ("share/doc/lima/LICENSE", b"Fixture Lima license", None)])
        dependencies = json.loads((PROJECT / "installer/macos/dependencies.json").read_text())
        payload = self.root / "payload"
        app = builder.stage_payload(project, payload, common, files, scientific,
                                    {"workflows": {}}, "arm64", python, lima, dependencies)
        executable = app / "Contents/MacOS/NIPAT"
        executable.write_bytes(b"fixture native launcher")
        executable.chmod(0o755)
        record = {
            **{field: common[field] for field in ("version", "source_commit", "runtime_image")},
            "architecture": "arm64", "runtime_vm_qualified": False,
            "scientific_asset_sha256": common["assets"]["scientific_image"]["sha256"],
            "payload_inventory": builder.payload_inventory(payload),
        }
        return payload, app, common, record

    def test_bundles_sources_dependencies_and_identical_scientific_archive(self):
        payload, app, common, record = self.fixture()
        actual = verifier.verify_payload(payload, common, record)
        self.assertEqual(actual["channel"], "experimental08")
        self.assertEqual(actual["architecture"], "arm64")
        self.assertFalse(actual["runtime_vm_qualified"])
        self.assertTrue((app / "Contents/Resources/python/bin/python3").is_symlink())
        self.assertTrue((app / "Contents/Resources/python/lib/python3.12/LICENSE.txt").is_file())
        self.assertTrue((app / "Contents/Resources/lima/share/doc/lima/LICENSE").is_file())

    def test_vendored_python_dependency_notices_are_unmodified(self):
        notices = PROJECT / "installer/macos/licenses/python-build-standalone"
        provenance = builder.read_json(notices / "provenance.json")
        self.assertGreaterEqual(len(provenance["files_sha256"]), 10)
        for name, expected in provenance["files_sha256"].items():
            self.assertEqual(builder.bundle.sha256_file(notices / name), expected, name)

    def test_changed_scientific_archive_cannot_pass_package_verification(self):
        payload, app, common, record = self.fixture()
        scientific = app / "Contents/Resources/app/.distribution/assets/nipat-scientific.tar.gz"
        scientific.write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "scientific archive"):
            verifier.verify_payload(payload, common, record)

    def test_changed_source_cannot_pass_package_verification(self):
        payload, app, common, record = self.fixture()
        (app / "Contents/Resources/app/src/nipat/__init__.py").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "source mismatch"):
            verifier.verify_payload(payload, common, record)

    def test_changed_dependency_cannot_pass_package_verification(self):
        payload, app, common, record = self.fixture()
        (app / "Contents/Resources/lima/bin/limactl").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            verifier.verify_payload(payload, common, record)

    def test_missing_launcher_rejected_even_if_inventory_matches(self):
        payload, app, common, record = self.fixture()
        (app / "Contents/MacOS/NIPAT").unlink()
        record["payload_inventory"] = builder.payload_inventory(payload)
        with self.assertRaisesRegex(ValueError, "launcher is missing"):
            verifier.verify_payload(payload, common, record)

    def test_wrong_source_or_image_identity_rejected(self):
        payload, app, common, record = self.fixture()
        common["runtime_image"] = "sha256:" + "c" * 64
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            verifier.verify_payload(payload, common, record)

    def test_archive_rejects_traversal_without_writing_outside_destination(self):
        path = archive(self.root / "unsafe.tar.gz", [("../outside", b"bad", None)])
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            builder.safe_extract(path, self.root / "extract")
        self.assertFalse((self.root / "outside").exists())

    def test_archive_rejects_link_escape(self):
        for index, link in enumerate(("../../../outside", "/tmp/outside")):
            path = archive(self.root / f"unsafe{index}.tar.gz", [("bin/python", None, link)])
            with self.assertRaisesRegex(ValueError, "link escapes"):
                builder.safe_extract(path, self.root / f"extract{index}")

    def test_archive_rejects_special_files(self):
        path = self.root / "fifo.tar.gz"
        with tarfile.open(path, "w:gz") as output:
            item = tarfile.TarInfo("fifo")
            item.type = tarfile.FIFOTYPE
            output.addfile(item)
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            builder.safe_extract(path, self.root / "extract")

    def test_dependency_digest_is_verified_before_extraction(self):
        path = self.root / "dependency.tar.gz"
        path.write_bytes(b"changed")
        entry = {"file": path.name, "size": path.stat().st_size, "sha256": "0" * 64,
                 "url": "https://github.com/lima-vm/lima/releases/download/v2.2.1/file.tar.gz"}
        with self.assertRaisesRegex(ValueError, "checksum/size"):
            builder.dependency_archive(entry, self.root, path)

    def test_package_rejects_stable_version_and_has_explicit_os_architecture(self):
        with self.assertRaises(ValueError):
            builder.package_version("0.7.2")
        with self.assertRaises(ValueError):
            builder.package_version("0.8.0")
        for architecture in ("arm64", "x86_64"):
            parsed = ET.fromstring(builder.distribution_xml("0.8.0a1", architecture))
            self.assertEqual(parsed.find("options").get("hostArchitectures"), architecture)
            self.assertEqual(parsed.find("allowed-os-versions/os-version").get("min"), "14.0")

    def test_pins_have_architecture_specific_verified_upstream_assets(self):
        pins = builder.read_json(PROJECT / "installer/macos/dependencies.json")
        self.assertEqual(set(pins["architectures"]), {"arm64", "x86_64"})
        for entries in pins["architectures"].values():
            for entry in entries.values():
                self.assertRegex(entry["sha256"], r"^[a-f0-9]{64}$")
                self.assertGreater(entry["size"], 1_000_000)
                self.assertTrue(entry["url"].startswith("https://github.com/"))

    def test_lima_entitlement_survives_code_signing(self):
        valid = plistlib.dumps({"com.apple.security.virtualization": True})
        verifier.require_virtualization_entitlement(valid, b"Executable=limactl\n")
        verifier.require_virtualization_entitlement(b"", b"Executable=limactl\n" + valid)
        for payload in (b"", plistlib.dumps({}),
                        plistlib.dumps({"com.apple.security.virtualization": False})):
            with self.assertRaisesRegex(ValueError, "virtualization entitlement"):
                verifier.require_virtualization_entitlement(payload, b"")

    def test_launcher_does_not_inherit_other_nipat_or_container_configuration(self):
        app = self.root / "Application/Contents/Resources/app"
        inherited = {"NIPAT_BACKEND": "wsl", "DOCKER_HOST": "tcp://remote", "LIMA_HOME": "/stable/lima",
                     "PYTHONPATH": "/untrusted", "TERM": "xterm-256color"}
        with patch.object(launcher.Path, "home", return_value=self.root / "user"):
            env = launcher.environment(app, app.parent, inherited)
        self.assertEqual(env["NIPAT_BACKEND"], "lima")
        self.assertEqual(env["LIMA_HOME"], str(self.root / "user/.nipat08/lima"))
        self.assertEqual(env["NIPAT_WORKSPACE_DIR"], str(self.root / "user/Library/Application Support/NIPAT-Experimental08"))
        self.assertNotIn("DOCKER_HOST", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["TERM"], "xterm-256color")

    def test_launcher_validates_source_inventory_before_running_code(self):
        payload, app, common, record = self.fixture()
        source = app / "Contents/Resources/app"
        self.assertEqual(launcher.load_manifest(source)["version"], "0.8.0a1")
        (source / "LICENSE").write_text("changed")
        with self.assertRaisesRegex(ValueError, "modificato"):
            launcher.load_manifest(source)

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "root-owned fixture requires root")
    def test_interrupted_installation_marker_blocks_launch(self):
        state = self.root / "installer-state"
        state.mkdir(mode=0o755)
        (state / "activity.lock").touch(mode=0o644)
        (state / "update-in-progress").touch(mode=0o644)
        with self.assertRaisesRegex(ValueError, "incompleta"):
            with launcher.installation_session(state):
                self.fail("An interrupted package must not launch")

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "root-owned fixture requires root")
    def test_runtime_removal_cannot_interrupt_an_active_cli_session(self):
        state = self.root / "installer-state"
        state.mkdir(mode=0o755)
        (state / "activity.lock").touch(mode=0o644)
        with launcher.installation_session(state):
            with self.assertRaisesRegex(ValueError, "sessione NIPAT"):
                with launcher.installation_session(state, exclusive=True):
                    self.fail("Maintenance must not interrupt an active CLI")
        with launcher.installation_session(state, exclusive=True):
            pass


if __name__ == "__main__":
    unittest.main()
