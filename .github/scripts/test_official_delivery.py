"""Official four-platform candidates preserve explicit source and byte ownership."""

import importlib.util
import json
import os
from pathlib import Path
import re
import textwrap
import unittest
from unittest import mock


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

    def test_candidate_summary_reuses_original_package_artifacts(self):
        record = {"publication_authorized": False}
        for key, value in (("windows", "a"), ("linux", "b"), ("macos_arm64", "c"), ("macos_x86_64", "d")):
            record[key] = {"file": key, "sha256": value * 64}
        rows = downloads.download_rows(record)
        self.assertEqual({row[2] for row in rows}, {
            "nipat-windows-setup", "nipat-linux-setup", "nipat-macos-setup-arm64", "nipat-macos-setup-x86_64",
        })
        for key in ("windows", "linux", "macos_arm64", "macos_x86_64"):
            original = record[key]["sha256"]
            record[key]["sha256"] = "invalid"
            with self.subTest(platform=key), self.assertRaises(ValueError):
                downloads.download_rows(record)
            record[key]["sha256"] = original
        workflow = (Path(__file__).resolve().parents[1] / "workflows/windows-installer.yml").read_text()
        self.assertNotIn("archive: false", workflow)
        self.assertNotIn("Provide Windows as one downloadable installer", workflow)

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

    def test_parallel_runtime_keeps_windows_success_required_for_final_evidence(self):
        workflow = (Path(__file__).resolve().parents[1] / "workflows/windows-installer.yml").read_text()
        jobs = dict(re.findall(r"^  ([a-z][a-z-]+):\n(.*?)(?=^  [a-z][a-z-]+:\n|\Z)",
                               workflow, flags=re.MULTILINE | re.DOTALL))
        for name in ("windows-checks", "linux-runtime"):
            with self.subTest(job=name):
                header = jobs[name].split("    steps:", 1)[0]
                self.assertRegex(header, r"(?m)^    needs: release-source$")
                self.assertNotRegex(header, r"(?m)^    if:")
        self.assertNotIn("download-artifact", jobs["linux-runtime"])
        self.assertNotIn("needs.", jobs["linux-runtime"])
        windows_header = jobs["windows-installer"].split("    steps:", 1)[0]
        self.assertIn("needs: [linux-runtime, windows-checks]", windows_header)
        self.assertNotRegex(windows_header, r"(?m)^    if:")
        required = jobs["installer-required"]
        self.assertIn("needs: [windows-installer, linux-installer, macos-installer]", required)
        self.assertRegex(required, r"(?m)^    if: always\(\)$")
        script = re.search(r"python - <<'PY'\n(.*?)^          PY$", required,
                           flags=re.MULTILINE | re.DOTALL)[1]
        code = compile(textwrap.dedent(script), "installer-required gate", "exec")
        results = {name: {"result": "success"}
                   for name in ("windows-installer", "linux-installer", "macos-installer")}
        with mock.patch.dict(os.environ, {"CHECK_RESULTS": json.dumps(results)}):
            exec(code, {})
        for result in ("skipped", "failure", "cancelled"):
            with self.subTest(windows_result=result):
                results["windows-installer"]["result"] = result
                with mock.patch.dict(os.environ, {"CHECK_RESULTS": json.dumps(results)}), \
                        self.assertRaises(SystemExit):
                    exec(code, {})

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
