import copy
import json
from pathlib import Path
import tempfile
import unittest

from windows_trust import PYTHON_INPUT, requires_windows_trust, verify


class WindowsTrustTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "windows-trust-check.json"
        self.manifest = {"version": "0.8.20", "source_commit": "a" * 40}
        self.archive = "app/.distribution/python-3.12.10-embed-amd64.zip"
        self.inventory = json.dumps({"source_commit": "a" * 40, "files": [
            {"path": "NIPAT.exe", "sha256": "b" * 64},
            {"path": "installer/windows/NipatActivityNative.dll", "sha256": "c" * 64},
            {"path": "installer/windows/bootstrap.ps1", "sha256": "d" * 64},
            {"path": self.archive[4:], "sha256": PYTHON_INPUT["sha256"]},
        ]}).encode()
        files = []
        for path, digest in (("app/NIPAT.exe", "b"),
                             ("app/installer/windows/NipatActivityNative.dll", "c"),
                             ("app/installer/windows/bootstrap.ps1", "d"),
                             ("setup/NIPAT-Setup.exe", "f")):
            files.append({"path": path, "sha256": digest * 64, "size": 12,
                          "signature_status": "NotSigned", "signer": None})
        for entry in PYTHON_INPUT["executable_files"]:
            files.append({"path": self.archive + "!/" + entry["path"], "sha256": entry["sha256"],
                          "size": entry["size"], "signature_status": "Valid",
                          "signer": {"subject": "CN=Python Software Foundation", "thumbprint": "a" * 40,
                                     "public_key_oid": "1.2.840.113549.1.1.1"}})
        self.report = {"schema_version": 1, **self.manifest, "installer_sha256": "f" * 64,
                       "scope": "authenticode-inventory", "assessment": "unsigned-components-present",
                       "smart_app_control": {"status": "not-performed"},
                       "uninstaller": {"status": "not-inspected", "reason": "Generated during installation."},
                       "embedded_archives": [{"path": self.archive, "sha256": PYTHON_INPUT["sha256"],
                                              "size": PYTHON_INPUT["size"]}],
                       "counts": {"Valid": len(PYTHON_INPUT["executable_files"]), "NotSigned": 4}, "files": files}

    def check(self, report=None):
        self.path.write_text(json.dumps(self.report if report is None else report))
        return verify(self.path, self.manifest, "f" * 64, self.inventory)

    def test_preserves_unsigned_status_without_sac_claim(self):
        result = self.check()
        self.assertEqual(result["assessment"], "unsigned-components-present")
        self.assertEqual(result["smart_app_control"], "not-performed")
        self.assertEqual(result["counts"], {"Valid": 31, "NotSigned": 4})

    def test_version_boundary_preserves_historical_releases(self):
        for version in ("0.8.9", "0.8.14", "0.8.19"):
            self.assertFalse(requires_windows_trust(version))
        for version in ("0.8.20", "0.8.20rc1", "0.8.21", "0.9.0", "1.0.0"):
            self.assertTrue(requires_windows_trust(version))
        with self.assertRaises(ValueError):
            requires_windows_trust("0.8.20\n")

    def test_changed_identity_or_false_trust_claim_is_rejected(self):
        for key, value in (("schema_version", True), ("source_commit", "0" * 40),
                           ("version", "0.8.14"), ("installer_sha256", "0" * 64),
                           ("smart_app_control", {"status": "passed"}),
                           ("assessment", "trusted"), ("counts", {"Valid": 8, "NotSigned": 0}),
                           ("uninstaller", {"status": "passed", "reason": "It compiled."})):
            changed = copy.deepcopy(self.report)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(changed)

    def test_missing_modified_duplicate_or_extra_executable_is_rejected(self):
        mutations = []
        changed = copy.deepcopy(self.report)
        changed["files"].pop(1)
        mutations.append(changed)
        changed = copy.deepcopy(self.report)
        changed["files"][0]["sha256"] = "0" * 64
        mutations.append(changed)
        changed = copy.deepcopy(self.report)
        changed["files"].append(copy.deepcopy(changed["files"][0]))
        mutations.append(changed)
        changed = copy.deepcopy(self.report)
        changed["files"][0]["path"] = "app/uninventoried.exe"
        mutations.append(changed)
        for changed in mutations:
            with self.subTest(files=changed["files"]), self.assertRaises(ValueError):
                self.check(changed)

    def test_invalid_signature_and_invented_signer_are_rejected(self):
        for status in ("HashMismatch", "NotTrusted", "UnknownError", "NotSupportedFileFormat"):
            changed = copy.deepcopy(self.report)
            changed["files"][0]["signature_status"] = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.check(changed)
        changed = copy.deepcopy(self.report)
        changed["files"][4]["signer"] = None
        with self.assertRaises(ValueError):
            self.check(changed)
        changed = copy.deepcopy(self.report)
        changed["files"][0]["signer"] = changed["files"][4]["signer"]
        with self.assertRaises(ValueError):
            self.check(changed)

    def test_embedded_python_must_match_inventoried_zip_and_safe_members(self):
        changed = copy.deepcopy(self.report)
        changed["embedded_archives"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.check(changed)
        for path in (self.archive + "!/../python.exe", self.archive + "!/python.txt", "app/../python.exe"):
            changed = copy.deepcopy(self.report)
            changed["files"][4]["path"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.check(changed)

    def test_each_archived_executable_is_required_even_if_totals_are_adjusted(self):
        for entry in PYTHON_INPUT["executable_files"]:
            changed = copy.deepcopy(self.report)
            changed["files"] = [item for item in changed["files"]
                                if item["path"] != self.archive + "!/" + entry["path"]]
            changed["counts"]["Valid"] -= 1
            with self.subTest(member=entry["path"]), self.assertRaises(ValueError):
                self.check(changed)

    def test_modified_archived_executable_is_rejected(self):
        for key, value in (("sha256", "0" * 64), ("size", 1)):
            changed = copy.deepcopy(self.report)
            changed["files"][4][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(changed)

    def test_archived_inventory_tracks_the_distribution_pin(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "trust_test_distribution", Path(__file__).resolve().parents[2] / "scripts/distribution_support.py")
        distribution = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(distribution)
        self.assertEqual(PYTHON_INPUT["file"], distribution.PYTHON_NAME)
        self.assertEqual(PYTHON_INPUT["sha256"], distribution.PYTHON_SHA256)


if __name__ == "__main__":
    unittest.main()
