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

    def run(self, command, *, working_dir=None):
        self.calls.append((list(map(str, command)), str(working_dir)))

    def record_run(self, *args, **kwargs):
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

    def test_stages_supported_tables_as_txt_without_changing_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            layout, panel = self.prepare_workspace(Path(directory))
            inputs = [self.write_input(layout.data_dir / name) for name in ("A.tsv", "B.TXT")]
            originals = {path: path.read_bytes() for path in inputs}
            runner = RecordingRunner()
            run = Workflows(layout, runner).contamination(
                inputs=inputs, panel=panel, run_name="staging"
            )
            staged = run / "work" / "inputs"
            self.assertEqual({path.name for path in staged.iterdir()}, {"A.txt", "B.txt"})
            for source in inputs:
                self.assertEqual(source.read_bytes(), originals[source])
                self.assertEqual((staged / f"{source.stem}.txt").read_bytes(), originals[source])
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(runner.calls[0][0][-2], str(layout.container_path(staged)))

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
