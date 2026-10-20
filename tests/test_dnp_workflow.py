import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

from nipat.errors import ValidationError
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout


class DnpPathTests(unittest.TestCase):
    def prepare(self, root, bam_name="sample.bam", reference_name="reference.fa"):
        project, data = root / "project", root / "data"
        project.mkdir(parents=True)
        data.mkdir()
        bam, reference, panel = data / bam_name, data / reference_name, data / "DNP_list.txt"
        for path in (bam, reference, Path(str(bam) + ".bai"), Path(str(reference) + ".fai")):
            path.write_text("fixture", encoding="utf-8")
        panel.write_text("chr1\t100\t101\tAA\tCC\n", encoding="utf-8")
        layout = ProjectLayout(project, root, data, root / "runs", project / "compose.yaml")
        return layout, bam, reference, panel

    def test_unsupported_dnp_paths_fail_before_creating_run_or_invoking_runner(self):
        cases = [("sample one.bam", "reference.fa"), ("sample.bam", "reference genome.fa"),
                 ("sample;one.bam", "reference.fa")]
        for bam_name, reference_name in cases:
            with self.subTest(bam_name=bam_name, reference_name=reference_name):
                with tempfile.TemporaryDirectory() as directory:
                    layout, bam, reference, panel = self.prepare(Path(directory), bam_name, reference_name)
                    runner = Mock()
                    with self.assertRaisesRegex(ValidationError, "senza spazi"):
                        Workflows(layout, runner).dnp_call(
                            bam=bam, reference=reference, panel=panel, parallel=False, run_name="bad"
                        )
                    runner.record_run.assert_not_called()
                    runner.run.assert_not_called()
                    self.assertFalse(layout.runs_dir.exists())

    def test_host_workspace_spaces_do_not_reject_valid_container_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            layout, bam, reference, panel = self.prepare(Path(directory) / "workspace with spaces")
            runner = Mock()
            runner.record_run.return_value = nullcontext()
            run = Workflows(layout, runner).dnp_call(
                bam=bam, reference=reference, panel=panel, parallel=False, run_name="good"
            )
            self.assertEqual((run / "work" / "bamlist.txt").read_text(), "/workspace/data/sample.bam\n")
            runner.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
