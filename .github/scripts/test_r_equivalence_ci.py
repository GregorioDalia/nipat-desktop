"""Keep scientific equivalence mandatory without authorizing publication."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECK_NAME = "Compare scientific cores with immutable versioned references"


def job_text(workflow, identifier):
    match = re.search(
        rf"^  {re.escape(identifier)}:\n(.*?)(?=^  [a-z][a-z-]+:\n|\Z)",
        workflow, re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"Missing workflow job: {identifier}")
    return match[1]


class REquivalenceCI(unittest.TestCase):
    def test_new_analysis_models_are_required_in_the_packaged_image(self):
        for name, identifier in (("ci.yml", "scientific"),
                                 ("windows-installer.yml", "linux-runtime")):
            job = job_text((ROOT / ".github/workflows" / name).read_text(), identifier)
            self.assertIn('scripts/verify_five_modules.py --image "$NIPAT_RUNTIME_IMAGE"', job)
            self.assertIn('--output "$TMPDIR/artifacts" --full', job)
            self.assertIn('${{ runner.temp }}/nipat-five-modules-check/', job)
            self.assertNotIn("continue-on-error:", job)

    def test_native_edge_and_settings_regressions_cannot_skip_in_image(self):
        for name, identifier in (("ci.yml", "scientific"), ("windows-installer.yml", "linux-runtime")):
            job = job_text((ROOT / ".github/workflows" / name).read_text(), identifier)
            self.assertIn("/qualification/.github/scripts/check_native_r.py", job)
            self.assertIn("--env PYTHONPATH=/opt/nipat/lib:/qualification/src", job)
            self.assertIn("--network=none", job)
            self.assertIn("${{ runner.temp }}/nipat-native-r-check/", job)
        gate = (ROOT / ".github/scripts/check_native_r.py").read_text()
        self.assertIn("result.skipped", gate)
        self.assertIn("test_native_r_*.py", gate)
        self.assertIn("test_scientific_settings.py", gate)

    def test_python_collection_includes_pytest_functions_and_unittest_classes(self):
        for name in ("ci.yml", "windows-installer.yml"):
            workflow = (ROOT / ".github/workflows" / name).read_text()
            self.assertIn("python -m coverage run -m pytest tests", workflow)
        self.assertIn("'pytest', 'tests'", (ROOT / ".github/scripts/check_windows.ps1").read_text())
        self.assertIn('"-m", "pytest", "tests"', (ROOT / ".github/scripts/check_macos.py").read_text())
        self.assertIn('"-r", ".github/quality-requirements.txt"', (ROOT / ".github/scripts/check_macos.py").read_text())
        self.assertIn("pytest==", (ROOT / ".github/quality-requirements.txt").read_text())

    def test_ci_and_installer_build_require_equivalence_in_the_tested_image(self):
        for name, identifier in (("ci.yml", "scientific"),
                                 ("windows-installer.yml", "linux-runtime")):
            with self.subTest(workflow=name):
                workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
                job = job_text(workflow, identifier)
                self.assertEqual(job.count(CHECK_NAME), 1)
                step = re.search(
                    rf"^      - name: {re.escape(CHECK_NAME)}\n(.*?)(?=^      - name:|\Z)",
                    job, re.MULTILINE | re.DOTALL,
                )[1]
                self.assertNotIn("continue-on-error:", job)
                self.assertNotRegex(step, r"(?m)^        if:")
                self.assertIn('set -o pipefail', step)
                self.assertIn('scripts/verify_r_equivalence.py --image "$NIPAT_RUNTIME_IMAGE"', step)
                self.assertIn('--output-dir "$TMPDIR/artifacts"', step)
                self.assertIn('${{ runner.temp }}/nipat-r-equivalence-check/', job)
                self.assertLess(job.index("Build scientific runtime"), job.index(CHECK_NAME))
                if name == "windows-installer.yml":
                    self.assertLess(job.index(CHECK_NAME), job.index("Export pinned assets"))
                    self.assertIn("needs: [linux-runtime, windows-checks]",
                                  job_text(workflow, "windows-installer"))
                else:
                    self.assertRegex(job_text(workflow, "required"),
                                     r"needs: \[[^\n]*\bscientific\b[^\n]*\]")

    def test_frozen_oracle_and_test_harness_are_not_installed_application_sources(self):
        inventory = {
            line.strip() for line in (ROOT / "distribution-files.txt").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertFalse(any(path.startswith(("tests/reference_r/", "tests/r_optimization/"))
                             for path in inventory))
        self.assertNotIn("scripts/verify_r_equivalence.py", inventory)

    def test_equivalence_does_not_enable_automatic_release_or_installer_publication(self):
        for name in ("windows-installer.yml", "publish-windows-release.yml"):
            with self.subTest(workflow=name):
                workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
                triggers = re.search(r"(?ms)^on:\n(.*?)(?=^[^ #\n])", workflow)[1]
                self.assertIn("workflow_dispatch:", triggers)
                self.assertNotRegex(triggers, r"(?m)^  (push|pull_request|workflow_run|release):")
        publisher = (ROOT / ".github/workflows/publish-windows-release.yml").read_text()
        self.assertIn("github.ref == 'refs/heads/main'", publisher)
        self.assertIn("default: testing", publisher)


if __name__ == "__main__":
    unittest.main()
