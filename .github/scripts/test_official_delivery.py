"""Official four-platform candidates preserve explicit source and byte ownership."""

import importlib.util
from pathlib import Path
import re
import unittest


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source = load("verify_release_source")
downloads = load("installer_downloads")
publisher = load("publish_windows_release")


class OfficialDeliveryTests(unittest.TestCase):
    def test_only_explicit_main_or_matching_release_branch_can_build(self):
        for ref in ("refs/heads/main", "refs/heads/release/0.8.2", "refs/heads/release/0.8.2-usability"):
            source.validate_dispatch("workflow_dispatch", ref, "0.8.2", source.PROFILE)
        for event, ref, version in (("push", "refs/heads/main", "0.8.2"),
                                    ("pull_request", "refs/pull/12/merge", "0.8.2"),
                                    ("workflow_dispatch", "refs/heads/experiment/0.8-portability", "0.8.2"),
                                    ("workflow_dispatch", "refs/heads/release/0.8.3", "0.8.2"),
                                    ("workflow_dispatch", "refs/heads/main", "0.8.0a1")):
            with self.subTest(event=event, ref=ref, version=version), self.assertRaises(ValueError):
                source.validate_dispatch(event, ref, version, source.PROFILE)
        with self.assertRaises(ValueError):
            source.validate_dispatch("workflow_dispatch", "refs/heads/main", "0.8.2",
                                     dict(source.PROFILE, channel="experimental08"))

    def test_diagnostic_candidate_uses_same_version_source_gate(self):
        for ref in ("refs/heads/main", "refs/heads/release/0.8.5", "refs/heads/release/0.8.5-diagnostics"):
            source.validate_dispatch("workflow_dispatch", ref, "0.8.5", source.PROFILE)
        for ref in ("refs/heads/release/0.8.2", "refs/heads/release/0.8.50",
                    "refs/heads/release/0.8.5evil", "refs/heads/feature/0.8.5-performance-diagnostics"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                source.validate_dispatch("workflow_dispatch", ref, "0.8.5", source.PROFILE)

    def test_four_downloads_match_exact_bound_packages(self):
        record = {"publication_authorized": False}
        environment = {}
        for key, prefix, value in (("windows", "WINDOWS", "a"), ("linux", "LINUX", "b"),
                                   ("macos_arm64", "ARM64", "c"), ("macos_x86_64", "INTEL", "d")):
            record[key] = {"file": key, "sha256": value * 64}
            environment[prefix + "_SHA256"] = value * 64
            environment[prefix + "_URL"] = "https://github.com/GregorioDalia/nipat-desktop/actions/runs/123/artifacts/456"
        self.assertEqual(len(downloads.download_rows(record, environment)), 4)
        for prefix in ("WINDOWS", "LINUX", "ARM64", "INTEL"):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                downloads.download_rows(record, dict(environment, **{prefix + "_SHA256": "0" * 64}))

    def test_review_build_restores_real_ubuntu_upgrade_and_requires_all_platforms(self):
        workflow = (Path(__file__).resolve().parents[1] / "workflows/windows-installer.yml").read_text()
        self.assertIn("needs: [windows-installer, linux-installer, macos-installer]", workflow)
        for verifier in ("verify_linux_dependencies.py", "verify_linux_installer.py", "verify_linux_upgrade.py",
                         "verify_installer_set.py", "verify_presentation.py", "verify_performance.py"):
            self.assertIn(verifier, workflow)
        self.assertIn("--previous-package build/upgrade-baseline/nipat-desktop_0.7.2_amd64.deb", workflow)
        self.assertIn("--macos-arm64-dir build/macos-arm64 --macos-x86-64-dir build/macos-x86_64", workflow)
        self.assertNotIn("verify_experimental_installers.py", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("${{ runner.temp }}/nipat-performance-check/", workflow)

    def test_publisher_required_jobs_match_actual_workflow_display_names(self):
        workflow = (Path(__file__).resolve().parents[1] / "workflows/windows-installer.yml").read_text()
        blocks = re.findall(r"^  ([a-z][a-z-]+):\n(.*?)(?=^  [a-z][a-z-]+:\n|\Z)",
                            workflow, flags=re.MULTILINE | re.DOTALL)
        names = set()
        for identifier, body in blocks:
            display = re.search(r"^    name: (.+)$", body, re.MULTILINE)
            name = display[1] if display else identifier
            if "${{ matrix.architecture }}" in name:
                architectures = re.findall(r"^            architecture: (\S+)$", body, re.MULTILINE)
                names.update(name.replace("${{ matrix.architecture }}", value) for value in architectures)
            else:
                names.add(name)
        self.assertTrue(set(publisher.required_build_jobs("0.8.2")).issubset(names), names)


if __name__ == "__main__":
    unittest.main()
