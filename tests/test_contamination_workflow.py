import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

from nipat.errors import ValidationError
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout


class RecordingRunner:
    def __init__(self):
        self.calls = []
        self.records = []

    def run(self, command, *, working_dir=None):
        self.calls.append((list(map(str, command)), str(working_dir)))

    def record_run(self, *args, **kwargs):
        self.records.append(kwargs)
        return nullcontext()


class ContaminationWorkflowTests(unittest.TestCase):
    def prepare_workspace(self, root):
        project = root / "repo"
        data = root / "data"
        project.mkdir()
        data.mkdir()
        layout = ProjectLayout(project, root, data, root / "runs", project / "compose.yaml")
        panel = data / "DNP_list.txt"
        panel.write_text("chr1\t100\t101\tAA\tCC\n", encoding="utf-8")
        return layout, panel

    def write_input(self, path):
        path.write_text(
            "chr\tpos1\tpos2\tN_REF\tN_ALT\tN_Other\n"
            "chr1\t100\t101\t95\t5\t0\n",
            encoding="utf-8",
        )
        return path

    def test_requests_engine_preparation_and_preserves_original_names_and_files(self):
        with tempfile.TemporaryDirectory() as directory:
            layout, panel = self.prepare_workspace(Path(directory))
            inputs = [self.write_input(layout.data_dir / name) for name in ("A.tsv", "B.TXT")]
            originals = {path: path.read_bytes() for path in inputs}
            runner = RecordingRunner()
            run = Workflows(layout, runner).contamination(
                inputs=inputs, panel=panel, run_name="staging"
            )
            request_file = run / "work" / "engine-request.json"
            request = json.loads(request_file.read_text(encoding="utf-8"))
            self.assertEqual({sample["name"] for sample in request["samples"]},
                             {"A.txt", "B.txt"})
            for source in inputs:
                self.assertEqual(source.read_bytes(), originals[source])
            # The client writes a request; only the container creates scientific intermediates.
            self.assertFalse((run / "work" / "inputs").exists())
            self.assertFalse((run / "work" / "DNPpanel.txt").exists())
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(runner.calls[0][0], [
                "python3", "/opt/nipat/engine/main.py", "execute", "contamination",
                "--request", str(layout.container_path(request_file)),
            ])
            self.assertEqual(runner.records[0]["bundled_workflow"], "contamination")
            mappings = runner.records[0]["mounts"].mappings
            self.assertTrue(all(item["read_only"] for item in mappings))
            self.assertEqual({item["host_path"] for item in mappings},
                             {str(path.resolve()) for path in [panel, *inputs]})
            self.assertEqual({item["container_path"] for item in mappings},
                             {request["panel"], *(sample["path"] for sample in request["samples"])})

    def test_rejects_colliding_names_before_running_r(self):
        with tempfile.TemporaryDirectory() as directory:
            layout, panel = self.prepare_workspace(Path(directory))
            inputs = [
                self.write_input(layout.data_dir / name)
                for name in ("sample.tsv", "sample.txt")
            ]
            runner = RecordingRunner()
            with self.assertRaisesRegex(ValidationError, "duplicato"):
                Workflows(layout, runner).contamination(
                    inputs=inputs, panel=panel, run_name="collision"
                )
            self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
