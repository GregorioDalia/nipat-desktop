import copy
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "linux_dependency_check", Path(__file__).resolve().parents[1] / "scripts/verify_linux_dependencies.py",
)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class LinuxDependencyTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            "dependency_packages": dict.fromkeys(CHECK.PACKAGES, "1.2.3"),
            "checks": dict.fromkeys(CHECK.CHECKS, True),
        }

    def result_text(self, value=None):
        return "APT output\n" + CHECK.RESULT_MARKER + json.dumps(value or self.result) + "\n"

    def test_requires_one_complete_result(self):
        self.assertEqual(CHECK.parse_result(self.result_text()), self.result)
        for output in ("", self.result_text() * 2):
            with self.subTest(output=output), self.assertRaises(ValueError):
                CHECK.parse_result(output)
        for name in CHECK.CHECKS:
            for value in (False, None, "true", 1):
                changed = copy.deepcopy(self.result)
                changed["checks"][name] = value
                with self.subTest(check=name, value=value), self.assertRaises(ValueError):
                    CHECK.parse_result(self.result_text(changed))

    def test_rejects_missing_required_dependencies(self):
        for package in CHECK.PACKAGES:
            changed = copy.deepcopy(self.result)
            del changed["dependency_packages"][package]
            with self.subTest(package=package), self.assertRaises(ValueError):
                CHECK.parse_result(self.result_text(changed))

    def test_preview_package_does_not_satisfy_desktop_installation(self):
        changed = copy.deepcopy(self.result)
        changed["dependency_packages"]["nipat-05-preview"] = changed["dependency_packages"].pop("nipat-desktop")
        with self.assertRaisesRegex(ValueError, "Missing installed dependency versions"):
            CHECK.parse_result(self.result_text(changed))

    def test_container_result_cannot_replace_host_measured_identity(self):
        changed = copy.deepcopy(self.result)
        changed["source_commit"] = "0" * 40
        with self.assertRaisesRegex(ValueError, "Unexpected fields"):
            CHECK.parse_result(self.result_text(changed))

    def test_container_has_readonly_inputs_and_no_host_socket_or_privilege(self):
        command = CHECK.container_command(Path("/tmp/NIPAT test/package.deb"), Path("/tmp/manifest.json"))
        mounts = [command[index + 1] for index, argument in enumerate(command) if argument == "--mount"]
        self.assertEqual(len(mounts), 2)
        self.assertTrue(all(mount.endswith(",readonly") for mount in mounts))
        self.assertFalse(any("docker.sock" in mount for mount in mounts))
        self.assertNotIn("--privileged", command)
        self.assertNotIn("--network=host", command)
        self.assertRegex(CHECK.BASE_IMAGE, r"^ubuntu:24\.04@sha256:[0-9a-f]{64}$")
        with self.assertRaises(ValueError):
            CHECK.container_command(Path("/tmp/a,readonly=false.deb"), Path("/tmp/manifest.json"))

    def test_failed_container_cannot_write_successful_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, manifest, output = root / "nipat.deb", root / "manifest.json", root / "result.json"
            package.write_bytes(b"package bytes")
            manifest.write_text(json.dumps({
                "source_commit": "a" * 40, "assets": {"scientific_image": {"sha256": "b" * 64}},
            }))
            with patch.object(CHECK.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 1, self.result_text().encode())):
                with redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                    CHECK.verify(package, manifest, output)
            evidence = json.loads(output.read_text())
            self.assertTrue(all(value is False for value in evidence["checks"].values()))
            self.assertNotIn("dependency_packages", evidence)

    def test_success_binds_package_manifest_and_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package, manifest, output = root / "nipat.deb", root / "manifest.json", root / "result.json"
            package.write_bytes(b"package bytes")
            manifest.write_text(json.dumps({
                "source_commit": "a" * 40, "assets": {"scientific_image": {"sha256": "b" * 64}},
            }))
            with patch.object(CHECK.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, self.result_text().encode())):
                with redirect_stdout(io.StringIO()):
                    CHECK.verify(package, manifest, output)
            evidence = json.loads(output.read_text())
            self.assertEqual(evidence["source_commit"], "a" * 40)
            self.assertEqual(evidence["package_sha256"], CHECK.sha256(package))
            self.assertEqual(evidence["installer_manifest_sha256"], CHECK.sha256(manifest))
            self.assertEqual(evidence["runtime_archive_sha256"], "b" * 64)
            self.assertEqual(evidence["scenario"], "clean-ubuntu-container")
            with self.assertRaisesRegex(ValueError, "already exist"):
                CHECK.verify(package, manifest, output)


if __name__ == "__main__":
    unittest.main()
