"""A review build must bind Linux acceptance evidence to both installer inputs."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("verify_set", Path(__file__).with_name("verify_installer_set.py"))
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class InstallationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.manifest_bytes = b"reviewed shared manifest"
        self.manifest = {"version": "0.6.0", "source_commit": "a" * 40,
                         "assets": {"scientific_image": {"sha256": "b" * 64}}}
        self.package = {"sha256": "c" * 64}
        self.evidence = {
            "schema_version": 1, "distribution": "native-linux-deb",
            "platform": "ubuntu-24.04-amd64", "scenario": "prepared-ci-runner",
            "source_commit": "a" * 40,
            "installer_manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest(),
            "package_sha256": "c" * 64, "runtime_archive_sha256": "b" * 64,
            "nonroot_uid": 1001, "resolved_runtime_image": "sha256:" + "d" * 64,
            "checks": dict.fromkeys(VERIFY.INSTALLATION_CHECKS, True),
        }

    def verify(self, evidence):
        VERIFY.verify_installation_check(evidence, self.manifest, self.manifest_bytes, self.package)

    def test_accepts_bound_nonroot_checks(self):
        self.verify(self.evidence)

    def test_07_requires_workflow_and_preference_evidence(self):
        for version in ("0.7.0a1", "0.7.0b1", "0.7.0rc1", "0.7.0", "0.7.5"):
            self.manifest["version"] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.verify(self.evidence)
            complete = copy.deepcopy(self.evidence)
            complete["checks"].update(dict.fromkeys(VERIFY.WORKFLOW_INSTALLATION_CHECKS, True))
            self.verify(complete)
            for check in VERIFY.WORKFLOW_INSTALLATION_CHECKS:
                for value in (None, False, 1, "true"):
                    changed = copy.deepcopy(complete)
                    if value is None:
                        del changed["checks"][check]
                    else:
                        changed["checks"][check] = value
                    with self.subTest(version=version, check=check, value=value), self.assertRaises(ValueError):
                        self.verify(changed)

    def test_06_contract_does_not_change_and_unreviewed_families_are_rejected(self):
        self.verify(self.evidence)
        extra = copy.deepcopy(self.evidence)
        extra["checks"].update(dict.fromkeys(VERIFY.WORKFLOW_INSTALLATION_CHECKS, True))
        with self.assertRaises(ValueError):
            self.verify(extra)
        for version in (None, [], "0.5.0a1", "0.8.0", "1.0.0", "0.7.0+local", "0.7.0\n"):
            self.manifest["version"] = version
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "review contract"):
                self.verify(self.evidence)

    def test_rejects_substituted_source_package_or_archive(self):
        for key in ("source_commit", "installer_manifest_sha256", "package_sha256", "runtime_archive_sha256"):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.evidence)
                changed[key] = "0" * len(changed[key])
                with self.assertRaises(ValueError):
                    self.verify(changed)

    def test_rejects_missing_failed_or_nonboolean_checks(self):
        for check in VERIFY.INSTALLATION_CHECKS:
            for value in (None, False, 1, "true"):
                with self.subTest(check=check, value=value):
                    changed = copy.deepcopy(self.evidence)
                    if value is None:
                        del changed["checks"][check]
                    else:
                        changed["checks"][check] = value
                    with self.assertRaises(ValueError):
                        self.verify(changed)

    def test_rejects_root_and_invalid_resolved_image(self):
        for key, values in (("nonroot_uid", (0, -1, True, "1001")),
                            ("resolved_runtime_image", ("latest", "", "sha256:bad")),
                            ("schema_version", (True, "1")),
                            ("scenario", ("fresh-desktop",)),
                            ("platform", ("ubuntu-22.04-amd64",))):
            for value in values:
                with self.subTest(key=key, value=value):
                    changed = copy.deepcopy(self.evidence)
                    changed[key] = value
                    with self.assertRaises(ValueError):
                        self.verify(changed)


class DependencyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.manifest_bytes = b"reviewed shared manifest"
        self.manifest = {"source_commit": "a" * 40, "assets": {"scientific_image": {"sha256": "b" * 64}}}
        self.package = {"sha256": "c" * 64}
        self.evidence = {
            "schema_version": 1, "distribution": "native-linux-deb",
            "platform": "ubuntu-24.04-amd64", "scenario": "clean-ubuntu-container",
            "source_commit": "a" * 40,
            "installer_manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest(),
            "package_sha256": "c" * 64, "runtime_archive_sha256": "b" * 64,
            "base_image": "ubuntu:24.04@sha256:" + "d" * 64,
            "dependency_packages": dict.fromkeys(
                ("python3.12", "docker.io", "docker-compose-v2", "nipat-desktop"), "1.2.3"),
            "checks": dict.fromkeys(VERIFY.DEPENDENCY_CHECKS, True),
        }

    def verify(self, evidence):
        VERIFY.verify_dependency_check(evidence, self.manifest, self.manifest_bytes, self.package)

    def test_accepts_bound_clean_container_dependency_check(self):
        self.verify(self.evidence)

    def test_rejects_unbound_or_misrepresented_scenarios(self):
        for key, value in (
            ("source_commit", "0" * 40), ("package_sha256", "0" * 64),
            ("installer_manifest_sha256", "0" * 64), ("runtime_archive_sha256", "0" * 64),
            ("scenario", "fresh-desktop"), ("base_image", "ubuntu:24.04"),
            ("schema_version", True), ("dependency_packages", {}),
        ):
            changed = copy.deepcopy(self.evidence)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(changed)

    def test_rejects_missing_failed_or_nonboolean_dependency_checks(self):
        for check in VERIFY.DEPENDENCY_CHECKS:
            for value in (None, False, 1, "true"):
                changed = copy.deepcopy(self.evidence)
                if value is None:
                    del changed["checks"][check]
                else:
                    changed["checks"][check] = value
                with self.subTest(check=check, value=value), self.assertRaises(ValueError):
                    self.verify(changed)


class WindowsClientEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.manifest_bytes = b"reviewed shared manifest"
        self.manifest = {
            "version": "0.7.0a1", "source_commit": "a" * 40,
            "source_sha256": {"src/nipat/cli.py": "c" * 64},
        }
        self.installer_sha256 = "d" * 64
        self.launcher_sha256 = "e" * 64
        self.bundle = VERIFY.load_module(
            "nipat_review_test_distribution", VERIFY.PROJECT / "scripts/distribution_support.py",
        )
        files = dict(self.manifest["source_sha256"])
        files.update({
            "release.json": "f" * 64, "NIPAT.exe": self.launcher_sha256,
            "installer/windows/EnableWsl.exe": "1" * 64,
            ".distribution/installer-manifest.json": hashlib.sha256(self.manifest_bytes).hexdigest(),
            f".distribution/{self.bundle.PYTHON_NAME}": self.bundle.PYTHON_SHA256,
        })
        self.inventory = {
            "schema_version": 1, "installation_channel": "desktop",
            "source_commit": self.manifest["source_commit"],
            "files": [{"path": path, "sha256": digest} for path, digest in files.items()],
        }
        self.inventory_bytes = json.dumps(self.inventory).encode("utf-8")
        self.evidence = {
            "schema_version": 1, "platform": "windows-amd64",
            "scenario": "staged-embedded-python-client", "version": self.manifest["version"],
            "source_commit": self.manifest["source_commit"],
            "installer_manifest_sha256": hashlib.sha256(self.manifest_bytes).hexdigest(),
            "installer_sha256": self.installer_sha256, "launcher_sha256": self.launcher_sha256,
            "application_inventory_sha256": hashlib.sha256(self.inventory_bytes).hexdigest(),
            "python_version": "3.12.10", "scientific_execution": False, "wsl_execution": False,
            "checks": dict.fromkeys(VERIFY.WINDOWS_CLIENT_CHECKS, True),
        }

    def verify(self, evidence, inventory_bytes=None):
        VERIFY.verify_windows_client_check(
            evidence, self.manifest, self.manifest_bytes,
            installer_sha256=self.installer_sha256, launcher_sha256=self.launcher_sha256,
            inventory_bytes=self.inventory_bytes if inventory_bytes is None else inventory_bytes,
        )

    def test_accepts_exact_client_checks_bound_to_compiled_installer_and_sources(self):
        self.verify(self.evidence)

    def test_rejects_replaced_build_identity_or_overstated_execution_scope(self):
        mutations = [
            ("schema_version", True), ("platform", "windows-arm64"),
            ("scenario", "fresh-desktop"), ("version", "0.7.0"),
            ("source_commit", "0" * 40), ("python_version", "3.13.0"),
            ("scientific_execution", True), ("wsl_execution", True),
            ("scientific_execution", 0), ("wsl_execution", 0),
            ("unreviewed_extra", True),
        ]
        mutations.extend((field, "0" * 64) for field in (
            "installer_manifest_sha256", "installer_sha256", "launcher_sha256",
            "application_inventory_sha256",
        ))
        for field, value in mutations:
            changed = copy.deepcopy(self.evidence)
            changed[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.verify(changed)
        missing = copy.deepcopy(self.evidence)
        del missing["scientific_execution"]
        with self.assertRaises(ValueError):
            self.verify(missing)

    def test_rejects_missing_failed_or_nonboolean_client_checks(self):
        for check in VERIFY.WINDOWS_CLIENT_CHECKS:
            for value in (None, False, 1, "true"):
                changed = copy.deepcopy(self.evidence)
                if value is None:
                    del changed["checks"][check]
                else:
                    changed["checks"][check] = value
                with self.subTest(check=check, value=value), self.assertRaises(ValueError):
                    self.verify(changed)
        changed = copy.deepcopy(self.evidence)
        changed["checks"]["wsl_installation"] = True
        with self.assertRaises(ValueError):
            self.verify(changed)

    def test_inventory_is_verified_even_when_its_evidence_hash_is_updated(self):
        mutations = []
        for field, value in (("source_commit", "0" * 40), ("schema_version", True),
                             ("installation_channel", "preview"), ("files", {})):
            changed = copy.deepcopy(self.inventory)
            changed[field] = value
            mutations.append((field, changed))
        for path in ("src/nipat/cli.py", "NIPAT.exe", ".distribution/installer-manifest.json",
                     f".distribution/{self.bundle.PYTHON_NAME}"):
            changed = copy.deepcopy(self.inventory)
            next(item for item in changed["files"] if item["path"] == path)["sha256"] = "0" * 64
            mutations.append((path, changed))
        changed = copy.deepcopy(self.inventory)
        changed["files"].pop()
        mutations.append(("missing file", changed))
        for path in ("extra.py", "src/nipat/cli.py", "SRC/NIPAT/CLI.PY"):
            changed = copy.deepcopy(self.inventory)
            changed["files"].append({"path": path, "sha256": "2" * 64})
            mutations.append(("extra or ambiguous file " + path, changed))
        for label, inventory in mutations:
            inventory_bytes = json.dumps(inventory).encode("utf-8")
            evidence = copy.deepcopy(self.evidence)
            evidence["application_inventory_sha256"] = hashlib.sha256(inventory_bytes).hexdigest()
            with self.subTest(mutation=label), self.assertRaises(ValueError):
                self.verify(evidence, inventory_bytes)


class VersionedInstallerSetTests(unittest.TestCase):
    def test_06_retains_legacy_windows_record_while_07_requires_client_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            windows, linux, assets = (root / name for name in ("windows", "linux", "assets"))
            for folder in (windows, linux, assets):
                folder.mkdir()
            manifest = {"version": "0.6.0", "source_commit": "a" * 40, "assets": {
                "scientific_image": {"file": "science.tar.gz", "sha256": "b" * 64, "size": 1},
            }}
            for folder in (linux, assets):
                (folder / "installer-manifest.json").write_bytes(b"same manifest")
            record = {"file": "nipat-desktop_0.6.0_amd64.deb", "sha256": "c" * 64}
            (linux / "linux-installer-build.json").write_text(json.dumps(record), encoding="utf-8")
            (linux / "SHA256SUMS").write_text(f"{record['sha256']}  {record['file']}\n", encoding="ascii")
            for name in ("linux-installation-check.json", "linux-dependency-check.json"):
                (linux / name).write_text("{}", encoding="utf-8")
            publisher = SimpleNamespace(prepare_assets=lambda *args: manifest, sha256=lambda path: "d" * 64)
            builder = SimpleNamespace(verify_package=lambda *args: record)
            with patch.object(VERIFY, "load_module", side_effect=lambda name, path: (
                    publisher if name == "nipat_review_publisher" else builder)), \
                    patch.object(VERIFY, "verify_installation_check"), \
                    patch.object(VERIFY, "verify_dependency_check"):
                result = VERIFY.verify_set(windows, linux, assets, root / "result06", "a" * 40)
                self.assertEqual(result["windows"], {"file": "NIPAT-Setup.exe", "sha256": "d" * 64})
                self.assertFalse(result["publication_authorized"])
                manifest["version"] = "0.7.0a1"
                with self.assertRaisesRegex(ValueError, "windows-client-check.json"):
                    VERIFY.verify_set(windows, linux, assets, root / "result07", "a" * 40)
                self.assertFalse((root / "result07").exists())



if __name__ == "__main__":
    unittest.main()
