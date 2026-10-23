"""A review build must bind Linux acceptance evidence to both installer inputs."""

import copy
import hashlib
import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("verify_set", Path(__file__).with_name("verify_installer_set.py"))
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class InstallationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.manifest_bytes = b"reviewed shared manifest"
        self.manifest = {"source_commit": "a" * 40, "assets": {"scientific_image": {"sha256": "b" * 64}}}
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


if __name__ == "__main__":
    unittest.main()
