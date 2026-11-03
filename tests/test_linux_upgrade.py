import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("linux_upgrade", Path(__file__).resolve().parents[1] / "scripts/verify_linux_upgrade.py")
upgrade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upgrade)


class LinuxUpgradePreservationTests(unittest.TestCase):
    def test_current_candidate_upgrades_the_last_published_official_baseline(self):
        self.assertEqual(upgrade.baseline_for("0.8.2"), upgrade.CURRENT_BASELINE)
        self.assertEqual(upgrade.CURRENT_BASELINE["version"], "0.7.2")
        self.assertEqual(upgrade.CURRENT_BASELINE["sha256"],
                         "e623897ffa46698250b1ee32216b1ab392607b6f7e3082a1932a164ef4992675")
        self.assertEqual(upgrade.baseline_for("0.7.2"), upgrade.BASELINE)

    def test_upgrade_allows_new_runs_but_never_changes_previous_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / "old/result.tsv"
            old.parent.mkdir()
            old.write_text("value\n0.602\n")
            before = upgrade.install.snapshot(root)
            (root / "new-result.tsv").write_text("new data\n")
            self.assertTrue(upgrade.preserved_files(root, before))
            old.write_text("value\n0.603\n")
            self.assertFalse(upgrade.preserved_files(root, before))
            old.unlink()
            self.assertFalse(upgrade.preserved_files(root, before))


if __name__ == "__main__":
    unittest.main()
