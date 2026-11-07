import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nipat_scientific.errors import ValidationError
from nipat_scientific.scratch import dnp_environment


class ScientificScratchTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    def test_native_execution_uses_unique_run_disk_directories_and_restores_environment(self):
        os.environ["NIPAT_DNP_SCRATCH"] = "original"
        created = []
        for _ in range(2):
            with dnp_environment("dnp-call", self.work) as directory:
                created.append(directory)
                self.assertEqual(directory.parent, self.work)
                self.assertEqual(os.environ["NIPAT_DNP_SCRATCH"], str(directory))
                self.assertEqual(Path(os.environ["NIPAT_DNP_PILEUP_HELPER"]).name, "dnp_pileup.py")
                (directory / "intermediate").write_bytes(b"temporary scientific data")
            self.assertFalse(directory.exists())
            self.assertEqual(os.environ["NIPAT_DNP_SCRATCH"], "original")
            self.assertNotIn("NIPAT_DNP_PILEUP_HELPER", os.environ)
        self.assertNotEqual(*created)

    def test_packaged_execution_uses_configured_volume_and_removes_only_its_directory(self):
        volume = self.root / "volume"
        volume.mkdir()
        sentinel = volume / "preserve"
        sentinel.write_text("keep")
        os.environ["NIPAT_SCRATCH_ROOT"] = str(volume)
        with self.assertRaises(KeyboardInterrupt):
            with dnp_environment("dnp-call", self.work) as directory:
                self.assertEqual(directory.parent, volume)
                (directory / "partial").write_text("partial")
                raise KeyboardInterrupt
        self.assertFalse(directory.exists())
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertNotIn("NIPAT_DNP_SCRATCH", os.environ)

    def test_configured_missing_root_never_falls_back_to_run_or_tmp(self):
        os.environ["NIPAT_SCRATCH_ROOT"] = str(self.root / "missing")
        with self.assertRaises(ValidationError):
            with dnp_environment("dnp-call", self.work):
                self.fail("must not enter")
        self.assertEqual(list(self.work.iterdir()), [])

    def test_other_workflows_do_not_create_scratch_or_override_environment(self):
        for workflow in ("snp-call", "cpi", "contamination"):
            with dnp_environment(workflow, self.work) as directory:
                self.assertIsNone(directory)
                self.assertNotIn("NIPAT_DNP_SCRATCH", os.environ)
        self.assertEqual(list(self.work.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
