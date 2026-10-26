import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("ci_changes", Path(__file__).with_name("ci_changes.py"))
changes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(changes)


class ScientificSelection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "CI selection test")
        self.git("config", "user.email", "ci-selection@example.invalid")
        self.write("README.md", "initial\n")
        self.write("scientific/panel.txt", "original input\n")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.PIPE).decode().strip()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def selected(self):
        return changes.scientific_decision(self.base, self.commit(), repository=self.root)[0]

    def test_documentation_changes_keep_only_quick_checks(self):
        self.write("README.md", "clarified instructions\n")
        self.write("docs/usage.md", "usage\n")
        self.assertFalse(self.selected())

    def test_deleting_scientific_input_requires_integration(self):
        (self.root / "scientific/panel.txt").unlink()
        self.assertTrue(self.selected())

    def test_renaming_scientific_input_outside_its_directory_requires_integration(self):
        self.git("mv", "scientific/panel.txt", "moved panel.txt")
        self.assertTrue(self.selected())

    def test_wrapper_runtime_and_fixture_changes_require_integration(self):
        for name in ("src/nipat/execution/runner.py", "docker/scientific-runtime/dependencies.lock.json",
                     "tests/fixtures/new sample/input.txt", "scripts/verify_input_modes.py"):
            with self.subTest(path=name):
                self.write(name, "changed\n")
                self.assertTrue(self.selected())
                self.base = self.git("rev-parse", "HEAD")

    def test_unknown_or_unavailable_history_fails_closed(self):
        head = self.base
        for base in ("", "0" * 40, "f" * 40, "--output=unexpected"):
            with self.subTest(base=base):
                self.assertTrue(changes.scientific_decision(base, head, repository=self.root)[0])

    def test_engine_package_and_its_checks_require_integration(self):
        for name in ("engine/main.py", "engine/contract.json", "tests/test_engine_package.py",
                     "tests/test_contamination_engine.py", "tests/test_bundled_runner.py",
                     "tests/test_snp_engine.py", "tests/test_input_modes.py",
                     "tests/test_dnp_engine.py", "tests/test_dnp_workflow.py",
                     "tests/test_cpi_engine.py",
                     "scripts/verify_engine_package.py", "scripts/verify_dnp_engine.py",
                     "scripts/verify_cpi_engine.py"):
            with self.subTest(path=name):
                self.write(name, "changed\n")
                self.assertTrue(self.selected())
                self.base = self.git("rev-parse", "HEAD")

    def test_runtime_and_packaging_paths_select_their_real_integration(self):
        for path in ("installer/runtime/Dockerfile", "installer/runtime/nipat-engine",
                     "installer/runtime/component.py"):
            with self.subTest(path=path):
                self.assertTrue({"runtime", "packaging"} <= changes.layers_for_path(path))
        for path in ("installer/linux/launch.py", "installer/windows/bootstrap.ps1",
                     "scripts/build_linux_installer.py", "scripts/build_windows_installer_assets.py",
                     "distribution-files.txt"):
            with self.subTest(path=path):
                self.assertIn("packaging", changes.layers_for_path(path))
        self.assertEqual(changes.layers_for_path("docs/GUIDA_UTILIZZO.md"), set())

    def test_unknown_comparison_and_deleted_runtime_cover_every_required_layer(self):
        decision, _ = changes.layer_decision("", self.base, repository=self.root)
        self.assertEqual(decision, dict.fromkeys(changes.LAYERS, True))
        self.write("installer/runtime/nipat-engine", "old helper")
        self.base = self.commit()
        (self.root / "installer/runtime/nipat-engine").unlink()
        decision, _ = changes.layer_decision(self.base, self.commit(), repository=self.root)
        self.assertTrue(decision["runtime"])
        self.assertTrue(decision["packaging"])

    def test_manual_request_runs_scientific_checks_without_changes(self):
        self.assertTrue(changes.scientific_decision(self.base, self.base, force=True, repository=self.root)[0])

    def test_catalog_and_plan_changes_require_real_engine_checks(self):
        for name in (
            "src/nipat_scientific/catalog_data/dnp-call.json",
            "src/nipat_scientific/catalog.py", "src/nipat_scientific/plan.py",
            "tests/test_scientific_catalog.py", "tests/test_workflow_plan.py",
        ):
            with self.subTest(path=name):
                self.write(name, "changed\n")
                self.assertTrue(self.selected())
                self.base = self.git("rev-parse", "HEAD")

    def test_new_or_renamed_tests_cannot_silently_skip_scientific_integration(self):
        # A whitelist misses future regression tests: the directory is the contract.
        for name in ("tests/test_previously_unknown_regression.py", "tests/new_area/test_workflow.py",
                     ".github/scripts/ci_control.py"):
            with self.subTest(path=name):
                self.write(name, "changed\n")
                self.assertTrue(self.selected())
                self.base = self.git("rev-parse", "HEAD")

    def test_deleting_a_test_requires_scientific_integration(self):
        self.write("tests/test_regression.py", "previous coverage\n")
        self.base = self.commit()
        (self.root / "tests/test_regression.py").unlink()
        self.assertTrue(self.selected())


if __name__ == "__main__":
    unittest.main()
