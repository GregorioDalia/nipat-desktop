import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "linux_installation_check", Path(__file__).resolve().parents[1] / "scripts/verify_linux_installer.py",
)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class LinuxInstallationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = {
            "version": "0.5.0a1", "source_commit": "1" * 40,
            "runtime_image": "sha256:" + "2" * 64,
            "assets": {"scientific_image": {"sha256": "3" * 64}},
        }
        self.state = {
            "schema_version": 1, "phase": "ready", "channel": "preview-0.5",
            "version": "0.5.0a1", "source_commit": "1" * 40,
            "installer_manifest_sha256": "4" * 64,
            "runtime_archive_sha256": "3" * 64,
            "source_runtime_image": "sha256:" + "2" * 64,
            # Different storage drivers may resolve the same archive to different IDs.
            "resolved_runtime_image": "sha256:" + "5" * 64,
        }

    def test_ready_state_requires_exact_archive_and_source_binding(self):
        self.assertEqual(check.check_state(self.state, self.manifest, "4" * 64),
                         "sha256:" + "5" * 64)
        for name, value in (
            ("phase", "failed"), ("channel", "stable"), ("version", "0.4.1"),
            ("source_commit", "0" * 40), ("installer_manifest_sha256", "0" * 64),
            ("runtime_archive_sha256", "0" * 64),
            ("source_runtime_image", "sha256:" + "0" * 64),
            ("resolved_runtime_image", "mutable:tag"),
        ):
            with self.subTest(field=name), self.assertRaises(RuntimeError):
                check.check_state({**self.state, name: value}, self.manifest, "4" * 64)

    def test_all_four_workflows_must_have_successful_run_records(self):
        for workflow in ("dnp-call", "snp-call", "contamination", "cpi"):
            directory = self.root / workflow
            directory.mkdir()
            (directory / "run.json").write_text(json.dumps({
                "workflow": workflow, "status": "succeeded",
            }))
        uid = (self.root / "cpi/run.json").stat().st_uid
        check.check_workflows(self.root, uid)
        (self.root / "cpi/run.json").write_text(json.dumps({"workflow": "cpi", "status": "failed"}))
        with self.assertRaisesRegex(RuntimeError, "all four"):
            check.check_workflows(self.root, uid)

    def test_foreign_owned_result_is_rejected(self):
        for workflow in ("dnp-call", "snp-call", "contamination", "cpi"):
            directory = self.root / workflow
            directory.mkdir()
            (directory / "run.json").write_text(json.dumps({
                "workflow": workflow, "status": "succeeded",
            }))
        wrong_uid = (self.root / "cpi/run.json").stat().st_uid + 1
        with self.assertRaisesRegex(RuntimeError, "owned by another"):
            check.check_workflows(self.root, wrong_uid)

    def test_snapshot_detects_changed_or_removed_user_data(self):
        path = self.root / "user result.txt"
        path.write_text("original")
        original = check.snapshot(self.root)
        path.write_text("changed")
        self.assertNotEqual(original, check.snapshot(self.root))
        path.unlink()
        self.assertNotEqual(original, check.snapshot(self.root))


if __name__ == "__main__":
    unittest.main()
