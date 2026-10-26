import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("linux_upgrade", Path(__file__).resolve().parents[1] / "scripts/verify_linux_upgrade.py")
upgrade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upgrade)


class LinuxUpgradePreservationTests(unittest.TestCase):
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
