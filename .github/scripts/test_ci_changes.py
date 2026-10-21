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

    def test_manual_request_runs_scientific_checks_without_changes(self):
        self.assertTrue(changes.scientific_decision(self.base, self.base, force=True, repository=self.root)[0])


if __name__ == "__main__":
    unittest.main()
