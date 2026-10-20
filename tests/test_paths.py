import tempfile
import unittest
import os
from pathlib import Path, PurePosixPath
from unittest.mock import patch

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
    def test_discovery_honors_configured_roots_and_explicit_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            with patch.dict(os.environ, {
                "NIPAT_PROJECT_DIR": str(project), "NIPAT_WORKSPACE_DIR": str(root),
                "NIPAT_DATA_DIR": str(root / "external-data"),
                "NIPAT_RUNS_DIR": str(root / "external-results"),
            }):
                layout = ProjectLayout.discover()
                self.assertEqual(layout.data_dir, (root / "external-data").resolve())
                self.assertEqual(layout.runs_dir, (root / "external-results").resolve())
                explicit = ProjectLayout.discover(
                    data_dir=root / "chosen-data", runs_dir=root / "chosen-results"
                )
                self.assertEqual(explicit.data_dir, (root / "chosen-data").resolve())
                self.assertEqual(explicit.runs_dir, (root / "chosen-results").resolve())
                explicit.ensure_storage_dirs()
                self.assertTrue(explicit.data_dir.is_dir())
                self.assertTrue(explicit.runs_dir.is_dir())
                self.assertEqual(list(explicit.data_dir.iterdir()), [])
                self.assertEqual(
                    explicit.container_path(explicit.runs_dir / "case" / "output.txt"),
                    PurePosixPath("/workspace/runs/case/output.txt"),
                )

    def test_rejects_overlapping_storage_roots_and_drive_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            cases = (
                (project / "data", root / "runs"),
                (root / "data", project / "runs"),
                (root / "data", root / "data" / "runs"),
                (root / "runs" / "data", root / "runs"),
                (root / "same", root / "same"),
                (root, root / "runs"),
                (Path(root.anchor), root / "runs"),
            )
            for data, runs in cases:
                with self.subTest(data=data, runs=runs):
                    layout = ProjectLayout(project, root, data, runs, project / "compose.yaml")
                    with self.assertRaises(ValidationError):
                        layout.ensure_storage_dirs()
            self.assertFalse((root / "runs").exists())

    def test_storage_root_cannot_be_a_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout = _layout(root)
            layout.data_dir.write_text("not a directory", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "non è una cartella"):
                layout.ensure_storage_dirs()

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
