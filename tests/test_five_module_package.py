"""Contract tests for the final-image workflow gate; these do not run Docker."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from nipat.paths import ProjectLayout


SPEC = importlib.util.spec_from_file_location(
    "five_module_package", Path(__file__).resolve().parents[1] / "scripts/verify_five_module_workflow.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class FiveModulePackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        self.layout = ProjectLayout(root / "app", root, root / "data", root / "runs", root / "compose.yaml")
        self.parent = root / "runs" / "all-five"
        (self.parent / "work").mkdir(parents=True)
        self.image = "sha256:" + "a" * 64
        self.record = {"status": "succeeded", "workflow": "analysis", "source": {"role": "client"},
                       "runtime": {"image_id": self.image},
                       "input_mounts": [{"container_path": "/inputs/sample.bam"}]}
        self.service = {"image": self.image, "read_only": True, "network_mode": "none", "volumes": [
            {"type": "bind", "source": "/original/sample.bam", "target": "/inputs/sample.bam",
             "read_only": True, "bind": {"create_host_path": False}},
            {"type": "bind", "source": str(self.parent), "target": str(self.layout.container_path(self.parent)),
             "read_only": False, "bind": {"create_host_path": False}},
            {"type": "volume", "target": "/scratch", "read_only": False}]}

    def verify(self, record=None, service=None):
        (self.parent / "run.json").write_text(json.dumps(self.record if record is None else record))
        (self.parent / "work/engine-compose.json").write_text(json.dumps(
            {"services": {"scientific": self.service if service is None else service}}))
        return check.check_bundled_client(self.parent, self.layout, self.image)

    def test_accepts_exact_image_and_only_scoped_input_run_and_scratch_mounts(self):
        self.assertEqual(self.verify(), self.record)

    def test_rejects_false_success_or_a_different_runtime_even_with_valid_compose(self):
        for changes in ({"status": "planned"}, {"workflow": "cpin"},
                        {"source": {"role": "engine"}}, {"runtime": {"image_id": "sha256:" + "b" * 64}}):
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                self.verify(record=self.record | changes)

    def test_rejects_source_checkout_mounts_and_writable_inputs(self):
        for change in ("extra-source", "writable-input", "writable-root", "network", "different-image"):
            service = deepcopy(self.service)
            if change == "extra-source":
                service["volumes"].append({"type": "bind", "source": "/checkout", "target": "/opt/nipat"})
            elif change == "writable-input":
                service["volumes"][0]["read_only"] = False
            elif change == "writable-root":
                service["read_only"] = False
            elif change == "network":
                service["network_mode"] = "host"
            else:
                service["image"] = "nipat-scientific-runtime:mutable-tag"
            with self.subTest(change=change), self.assertRaises(AssertionError):
                self.verify(service=service)


if __name__ == "__main__":
    unittest.main()
