import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from nipat.errors import ValidationError
from nipat.execution.mounts import INPUT_ROOT, InputMounts
from nipat.execution.runner import DockerComposeRunner
from nipat.paths import ProjectLayout


class InputMountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        project = self.root / "application"
        (project / "scientific").mkdir(parents=True)
        script = project / "scientific" / "test.R"
        script.write_text("# fixture\n", encoding="utf-8")
        digest = hashlib.sha256(script.read_bytes()).hexdigest()
        (project / "scientific" / "SHA256SUMS").write_text(f"{digest}  test.R\n")
        self.layout = ProjectLayout(
            project, self.root, self.root / "data", self.root / "results", project / "compose.yaml"
        )
        self.external = self.root / "chosen elsewhere"
        self.external.mkdir()
        self.source = self.external / "sample $NAME (ü).bam"
        self.source.write_bytes(b"original input")

    def test_external_file_is_mapped_read_only_without_copying(self):
        mounts = InputMounts(self.layout)
        target = mounts.bind_file(self.source)
        self.assertTrue(target.is_relative_to(INPUT_ROOT))
        self.assertEqual(target.suffix, ".bam")
        self.assertRegex(target.name, r"^[A-Za-z0-9._-]+$")
        volume = mounts.compose_override()["services"]["scientific"]["volumes"][0]
        self.assertEqual(volume["source"], str(self.source.resolve()).replace("$", "$$"))
        self.assertEqual(volume["target"], str(target))
        self.assertTrue(volume["read_only"])
        self.assertFalse(volume["bind"]["create_host_path"])
        self.assertEqual(self.source.read_bytes(), b"original input")
        self.assertFalse(self.layout.data_dir.exists())
        self.assertFalse(self.layout.runs_dir.exists())

    def test_unicode_default_filename_preserves_extension(self):
        source = self.external / "母亲.txt"
        source.touch()
        self.assertEqual(InputMounts(self.layout).bind_file(source).name, "input.txt")

    def test_explicit_cpi_names_preserve_ids_and_escape_dollar_for_compose(self):
        target = "/workspace/inputs/cpi/Mother Caso è $A.txt"
        mounts = InputMounts(self.layout)
        self.assertEqual(mounts.bind_file(self.source, target=target), PurePosixPath(target))
        self.assertEqual(mounts.mappings[0]["container_path"], target)
        self.assertEqual(
            mounts.compose_override()["services"]["scientific"]["volumes"][0]["target"],
            target.replace("$", "$$"),
        )

    def test_sidecar_targets_share_the_bam_stem(self):
        index = Path(str(self.source) + ".bai")
        index.write_bytes(b"index")
        mounts = InputMounts(self.layout)
        bam_target = mounts.bind_file(self.source, target=INPUT_ROOT / "bam" / "sample_0001.bam")
        index_target = mounts.bind_file(index, target=str(bam_target) + ".bai")
        self.assertEqual(str(index_target), str(bam_target) + ".bai")
        self.assertEqual(len(mounts.mappings), 2)

    def test_same_file_mapping_is_reused_but_target_collision_is_rejected(self):
        mounts = InputMounts(self.layout)
        target = mounts.bind_file(self.source)
        self.assertEqual(mounts.bind_file(self.source), target)
        self.assertEqual(mounts.bind_file(self.source, target=target), target)
        self.assertEqual(len(mounts.mappings), 1)
        other = self.external / "other.bam"
        other.touch()
        with self.assertRaisesRegex(ValidationError, "duplicato"):
            mounts.bind_file(other, target=target)

    def test_rejects_directory_sources_and_unsafe_target_paths(self):
        with self.assertRaisesRegex(ValidationError, "File di input"):
            InputMounts(self.layout).bind_file(self.external)
        invalid = (
            "/workspace/runs/output.txt", "/workspace/inputs", "relative.txt",
            "/workspace/inputs/../escape.txt", "/workspace/inputs/./sample.txt",
            "/workspace/inputs//sample.txt", "/workspace/inputs/name/",
            "/workspace/inputs/name\\file.txt", "/workspace/inputs/a\n.txt",
        )
        for target in invalid:
            with self.subTest(target=target), self.assertRaises(ValidationError):
                InputMounts(self.layout).bind_file(self.source, target=target)

    def test_rejects_parent_file_mounts_in_both_orders(self):
        for first, second in (("parent", "parent/file"), ("parent/file", "parent")):
            mounts = InputMounts(self.layout)
            mounts.bind_file(self.source, target=INPUT_ROOT / first)
            with self.assertRaisesRegex(ValidationError, "sovrapposto"):
                mounts.bind_file(self.source, target=INPUT_ROOT / second)

    def test_generated_target_skips_existing_file_parent(self):
        mounts = InputMounts(self.layout)
        mounts.bind_file(self.source, target=INPUT_ROOT / "input-002")
        other = self.external / "other.txt"
        other.touch()
        target = mounts.bind_file(other)
        self.assertEqual(target.parent.name, "input-003")

    def test_disappeared_source_cannot_become_a_host_directory(self):
        mounts = InputMounts(self.layout)
        mounts.bind_file(self.source)
        self.source.unlink()
        with self.assertRaisesRegex(ValidationError, "non più disponibile"):
            mounts.write_override(self.root / "mounts.json")
        self.assertFalse(self.source.exists())

    def test_saved_override_is_immutable_and_contains_only_selected_files(self):
        mounts = InputMounts(self.layout)
        mounts.bind_file(self.source)
        destination = self.root / "override.json"
        mounts.write_override(destination)
        original = destination.read_bytes()
        with self.assertRaises(FileExistsError):
            mounts.write_override(destination)
        other = self.external / "unselected.txt"
        other.touch()
        with self.assertRaisesRegex(ValidationError, "già stati registrati"):
            mounts.bind_file(other)
        self.assertEqual(destination.read_bytes(), original)
        volumes = json.loads(original)["services"]["scientific"]["volumes"]
        self.assertEqual(len(volumes), 1)

    def test_runner_activates_override_records_mapping_and_clears_it(self):
        mounts = InputMounts(self.layout)
        target = mounts.bind_file(self.source)
        runner = DockerComposeRunner(self.layout, dry_run=True)
        run = self.layout.new_run_dir("test", "mounted")
        with redirect_stdout(io.StringIO()):
            with runner.record_run(
                run, workflow="test", inputs=[self.source], parameters={}, mounts=mounts
            ):
                self.assertEqual(runner._base_command().count("-f"), 2)
                runner.run(["Rscript", "test.R", target])
        self.assertEqual(runner._base_command().count("-f"), 1)
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "planned")
        self.assertEqual(record["input_mounts"], mounts.mappings)
        self.assertEqual(record["commands"][0]["argv"].count("-f"), 2)
        self.assertTrue((run / record["compose_override"]).is_file())

    def test_runner_clears_mounts_after_failure(self):
        mounts = InputMounts(self.layout)
        mounts.bind_file(self.source)
        runner = DockerComposeRunner(self.layout, dry_run=True)
        run = self.layout.new_run_dir("test", "failed-mounted")
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "fixture"):
            with runner.record_run(
                run, workflow="test", inputs=[self.source], parameters={}, mounts=mounts
            ):
                raise ValueError("fixture")
        self.assertEqual(runner._base_command().count("-f"), 1)
        self.assertEqual(json.loads((run / "run.json").read_text(encoding="utf-8"))["status"], "failed")

    def test_doctor_creates_only_required_static_mount_directories(self):
        self.layout.compose_file.write_text("services: {}\n")
        runner = DockerComposeRunner(self.layout)
        with patch("nipat.execution.runner.shutil.which", return_value="docker"), patch.object(
            runner, "_capture", return_value="Docker Compose"
        ):
            runner.doctor(check_runtime=False)
        self.assertTrue(self.layout.data_dir.is_dir())
        self.assertTrue(self.layout.runs_dir.is_dir())
        self.assertEqual(list(self.layout.data_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
