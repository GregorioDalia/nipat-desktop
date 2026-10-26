import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from nipat.errors import ValidationError
from nipat.execution.recovery import ownership_labels
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.transport import DockerTransport
from nipat.paths import ProjectLayout


class RunRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        root = Path(self.temp)
        project = root / "repo"
        project.mkdir()
        self.layout = ProjectLayout(project, root, root / "data", root / "runs", project / "compose.yaml")
        self.runner = DockerComposeRunner(self.layout, transport=DockerTransport())
        self.run = self.layout.new_run_dir("test", "incomplete")
        self.name = "nipat-run-" + "a" * 32
        self.container_id = "b" * 64
        self.record = {
            "schema_version": 1, "run_id": "c" * 32, "run_name": "incomplete",
            "status": "running", "transport": {"backend": "native"},
            "bundled_workflow": "workflow-plan", "runtime": {"image_id": "sha256:" + "d" * 64},
            "commands": [{"container_name": self.name, "status": "running"}],
        }
        self.save_record()
        self.observed = {
            "id": self.container_id, "name": "/" + self.name,
            "image": self.record["runtime"]["image_id"],
            "labels": ownership_labels(self.run, self.record["run_id"]), "state": "running",
        }

    def save_record(self):
        (self.run / "run.json").write_text(json.dumps(self.record))

    def answer(self):
        return subprocess.CompletedProcess("inspect", 0, stdout=json.dumps(self.observed), stderr="")

    def test_inspect_is_read_only_and_keeps_recorded_and_observed_states_distinct(self):
        before = (self.run / "run.json").read_bytes()
        with patch("nipat.execution.recovery.subprocess.run", return_value=self.answer()) as inspect:
            report = self.runner.reconcile_run(self.run)
        self.assertEqual(report["recorded_status"], "running")
        self.assertTrue(report["containers"][0]["owned"])
        self.assertEqual(report["containers"][0]["state"], "running")
        self.assertEqual((self.run / "run.json").read_bytes(), before)
        self.assertFalse((self.run / "recovery.json").exists())
        self.assertEqual(inspect.call_args.args[0][:3], ["docker", "container", "inspect"])

    def test_owned_running_container_stops_by_immutable_id_and_preserves_history(self):
        before = (self.run / "run.json").read_bytes()
        output = self.run / "output" / "partial.txt"
        output.write_text("retain")
        with patch("nipat.execution.recovery.subprocess.run", return_value=self.answer()), patch.object(
            self.runner, "_stop_container", return_value={"status": "removed"},
        ) as stop:
            report = self.runner.reconcile_run(self.run, stop=True)
        stop.assert_called_once_with(self.container_id)
        self.assertEqual(report["containers"][0]["cleanup"]["status"], "removed")
        self.assertEqual((self.run / "run.json").read_bytes(), before)
        self.assertEqual(output.read_text(), "retain")
        self.assertEqual(len(json.loads((self.run / "recovery.json").read_text())["observations"]), 1)
        self.assertIsNone(self.runner._bundled_workflow)

    def test_foreign_labels_or_image_refuse_stop(self):
        for changed in ("labels", "image", "name"):
            with self.subTest(changed=changed):
                original = self.observed[changed]
                self.observed[changed] = {} if changed == "labels" else "foreign"
                with patch("nipat.execution.recovery.subprocess.run", return_value=self.answer()), patch.object(
                    self.runner, "_stop_container",
                ) as stop:
                    with self.assertRaises(ValidationError):
                        self.runner.reconcile_run(self.run, stop=True)
                stop.assert_not_called()
                self.observed[changed] = original

    def test_legacy_record_is_visible_but_cannot_authorize_stop(self):
        del self.record["run_id"]
        self.save_record()
        with patch("nipat.execution.recovery.subprocess.run", return_value=self.answer()):
            report = self.runner.reconcile_run(self.run)
            self.assertFalse(report["containers"][0]["owned"])
            with self.assertRaises(ValidationError):
                self.runner.reconcile_run(self.run, stop=True)

    def test_backend_mismatch_does_not_query_or_stop_other_runtime(self):
        self.record["transport"] = {"backend": "wsl", "wsl_distro": "old-installation"}
        self.save_record()
        with patch("nipat.execution.recovery.subprocess.run") as inspect:
            report = self.runner.reconcile_run(self.run)
        inspect.assert_not_called()
        self.assertFalse(report["backend_matches"])
        self.assertEqual(report["containers"][0]["state"], "identity_mismatch")

    def test_absent_and_unreachable_are_distinct(self):
        for error, state in (("Error: No such container: test", "absent"),
                             ("Cannot connect to daemon", "unavailable")):
            with self.subTest(error=error), patch(
                "nipat.execution.recovery.subprocess.run",
                return_value=subprocess.CompletedProcess("inspect", 1, stdout="", stderr=error),
            ):
                report = self.runner.reconcile_run(self.run)
                self.assertEqual(report["containers"][0]["state"], state)

    def test_scan_includes_failed_but_not_successful_runs(self):
        with patch("nipat.execution.recovery.subprocess.run", return_value=self.answer()):
            self.assertEqual(len(self.runner.incomplete_runs()), 1)
            self.record["status"] = "succeeded"
            self.save_record()
            self.assertEqual(self.runner.incomplete_runs(), [])

    def test_run_outside_current_results_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.runner.reconcile_run(Path(self.temp))

    def test_dry_run_never_queries_or_stops_runtime(self):
        self.runner.dry_run = True
        with patch("nipat.execution.recovery.subprocess.run") as query:
            with self.assertRaisesRegex(ValidationError, "rimuovere --dry-run"):
                self.runner.reconcile_run(self.run)
            with self.assertRaisesRegex(ValidationError, "rimuovere --dry-run"):
                self.runner.incomplete_runs()
        query.assert_not_called()

    def test_invalid_previous_recovery_prevents_stop(self):
        (self.run / "recovery.json").write_text("invalid")
        with patch("nipat.execution.recovery.subprocess.run", return_value=self.answer()), patch.object(
            self.runner, "_stop_container",
        ) as stop:
            with self.assertRaisesRegex(ValidationError, "arresto non eseguito"):
                self.runner.reconcile_run(self.run, stop=True)
        stop.assert_not_called()

    def test_invalid_run_json_is_reported_without_runtime_query(self):
        for invalid in ("[" * 2000 + "]" * 2000,
                        json.dumps({**self.record, "schema_version": True})):
            with self.subTest(invalid=invalid[:40]):
                (self.run / "run.json").write_text(invalid)
                with patch("nipat.execution.recovery.subprocess.run") as query:
                    with self.assertRaises(ValidationError):
                        self.runner.reconcile_run(self.run, stop=True)
                    self.assertEqual(self.runner.incomplete_runs()[0]["recorded_status"], "unreadable")
                query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
