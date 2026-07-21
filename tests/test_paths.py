import tempfile
import unittest
from pathlib import Path, PurePosixPath

from nipat.errors import ValidationError
from nipat.paths import ProjectLayout


def _layout(tmp_path: Path) -> ProjectLayout:
    project = tmp_path / "nipat-desktop"
    project.mkdir(parents=True)
    return ProjectLayout(
        project_dir=project,
        workspace_dir=tmp_path,
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        compose_file=project / "compose.yaml",
    )


class PathTests(unittest.TestCase):
    def test_container_path_maps_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            layout = _layout(tmp_path)
            sample = tmp_path / "data" / "samples" / "sample.bam"
            sample.parent.mkdir(parents=True)
            sample.touch()
            self.assertEqual(
                layout.container_path(sample),
                PurePosixPath("/workspace/data/samples/sample.bam"),
            )

    def test_container_path_maps_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            layout = _layout(tmp_path)
            script = layout.project_dir / "scientific" / "script.R"
            script.parent.mkdir()
            script.touch()
            self.assertEqual(
                layout.container_path(script),
                PurePosixPath("/workspace/nipat-desktop/scientific/script.R"),
            )

    def test_container_path_rejects_external_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            layout = _layout(tmp_path / "workspace")
            external = tmp_path / "external.txt"
            external.touch()
            with self.assertRaisesRegex(ValidationError, "data/runs"):
                layout.container_path(external)

    def test_new_run_directory_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            layout = _layout(tmp_path)
            first = layout.new_run_dir("dnp-call", "test-run")
            self.assertTrue((first / "work").is_dir())
            self.assertTrue((first / "output").is_dir())
            with self.assertRaisesRegex(ValidationError, "esiste già"):
                layout.new_run_dir("dnp-call", "test-run")


if __name__ == "__main__":
    unittest.main()
