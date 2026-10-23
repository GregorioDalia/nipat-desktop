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
        self.records = []
        self.calls = []

    def record_run(self, run_dir, **kwargs):
        self.records.append((run_dir, kwargs))
        return nullcontext()

    def run(self, command, *, working_dir=None):
        self.calls.append((list(map(str, command)), str(working_dir)))


class DnpWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        workspace = self.root / "workspace with spaces"
        project = workspace / "application"
        project.mkdir(parents=True)
        self.layout = ProjectLayout(
            project, workspace, workspace / "data", workspace / "runs",
            project / "compose.yaml",
        )
        self.external = self.root / "external inputs $ ,= (selected)"
        self.external.mkdir()
        self.bam = self.write_file(self.external / "sample $x,= (one).bam", b"BAM fixture\n")
        self.reference = self.write_file(
            self.external / "reference $x,= (genome).fa", b">chr1\nACGT\n",
        )
        self.fai = self.write_file(Path(str(self.reference) + ".fai"), b"FAI fixture\n")
        self.panel = self.write_file(
            self.external / "DNP panel $x,= (draft).txt", b"chr1\t100\t101\tAA\tCC\n",
        )
        self.runner = RecordingRunner()
        self.workflows = Workflows(self.layout, self.runner)

    @staticmethod
    def write_file(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path.resolve()

    def invoke(self, **kwargs):
        arguments = {"reference": self.reference, "panel": self.panel, "run_name": "test"}
        arguments.update(kwargs)
        if not {"bam", "bams", "bamlist"}.intersection(kwargs):
            arguments["bam"] = self.bam
        return self.workflows.dnp_call(**arguments)

    def assert_not_started(self):
        self.assertEqual(self.runner.records, [])
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.layout.runs_dir.exists())

    @staticmethod
    def request_for(run):
        return json.loads((run / "work" / "engine-request.json").read_text(encoding="utf-8"))

    def test_external_paths_use_safe_read_only_aliases_and_preserve_originals(self):
        originals = {path: path.read_bytes() for path in (
            self.bam, self.reference, self.fai, self.panel,
        )}
        run = self.invoke()
        record = self.runner.records[0][1]
        mappings = record["mounts"].mappings
        mounted = {Path(item["host_path"]): item["container_path"] for item in mappings}
        self.assertEqual(mounted[self.bam], "/workspace/inputs/bams/sample_0001.bam")
        self.assertEqual(mounted[self.reference], "/workspace/inputs/reference/genome.fa")
        self.assertEqual(mounted[self.fai], "/workspace/inputs/reference/genome.fa.fai")
        self.assertTrue(all(item["read_only"] for item in mappings))
        self.assertEqual(mounted[self.panel], "/workspace/inputs/dnp-panel.txt")
        self.assertEqual(set(record["inputs"]), set(originals))
        self.assertEqual(record["bundled_workflow"], "dnp-call")
        self.assertEqual(
            self.request_for(run), {
                "schema_version": 1, "workflow": "dnp-call",
                "panel": "/workspace/inputs/dnp-panel.txt",
                "samples": [{"path": "/workspace/inputs/bams/sample_0001.bam",
                             "sample_id": "sample_0001"}],
                "reference": "/workspace/inputs/reference/genome.fa", "parallel": False,
                "work_dir": str(self.layout.container_path(run / "work")),
                "out_dir": str(self.layout.container_path(run / "output")),
            },
        )
        self.assertFalse((run / "work" / "bamlist.txt").exists())
        self.assertFalse((run / "work" / "DNP_list.txt").exists())
        self.assertEqual(len(self.runner.calls), 1)
        command, working_dir = self.runner.calls[0]
        self.assertEqual(command, [
            "python3", "/opt/nipat/engine/main.py", "execute", "dnp-call", "--request",
            str(self.layout.container_path(run / "work" / "engine-request.json")),
        ])
        self.assertEqual(working_dir, str(self.layout.container_path(run)))
        self.assertFalse(any(str(self.external) in argument for argument in command))
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

    def test_multiple_bams_with_same_basename_keep_order_and_distinct_sample_ids(self):
        first = self.write_file(self.external / "first" / "abam.sample.bam", b"first BAM\n")
        second = self.write_file(self.external / "second" / "abam.sample.bam", b"second BAM\n")
        run = self.invoke(bams=[second, first])
        parameters = self.runner.records[0][1]["parameters"]
        samples = parameters["sample_mapping"]
        self.assertEqual(parameters["bams"], [str(second), str(first)])
        self.assertEqual(
            [sample["original_path"] for sample in samples], [str(second), str(first)],
        )
        self.assertEqual(
            [sample["sample_id"] for sample in samples], ["sample_0001", "sample_0002"],
        )
        expected_aliases = [
            "/workspace/inputs/bams/sample_0001.bam",
            "/workspace/inputs/bams/sample_0002.bam",
        ]
        self.assertEqual([sample["container_path"] for sample in samples], expected_aliases)
        self.assertEqual(
            self.request_for(run)["samples"],
            [{"path": alias, "sample_id": f"sample_{number:04d}"}
             for number, alias in enumerate(expected_aliases, 1)],
        )
        mounted = {item["container_path"]: item["host_path"]
                   for item in self.runner.records[0][1]["mounts"].mappings}
        self.assertEqual(
            [mounted[alias] for alias in expected_aliases], [str(second), str(first)],
        )

    def test_bamlist_resolves_quoted_relative_entries_from_its_own_directory(self):
        first = self.write_file(self.external / "folder one" / "first sample.bam", b"first\n")
        second = self.write_file(self.external / "folder two" / "second sample.bam", b"second\n")
        source_list = self.external / "selected BAMs.txt"
        source_list.write_text(
            "\"folder two/second sample.bam\"\n\n'folder one/first sample.bam'\n",
            encoding="utf-8-sig",
        )
        original = source_list.read_bytes()
        run = self.invoke(bamlist=source_list)
        record = self.runner.records[0][1]
        self.assertEqual(record["parameters"]["bams"], [str(second), str(first)])
        self.assertEqual(record["parameters"]["bamlist"], str(source_list))
        self.assertIn(source_list, record["inputs"])
        self.assertFalse(any(
            item["host_path"] == str(source_list) for item in record["mounts"].mappings
        ))
        self.assertEqual(self.request_for(run)["samples"], [
            {"path": "/workspace/inputs/bams/sample_0001.bam", "sample_id": "sample_0001"},
            {"path": "/workspace/inputs/bams/sample_0002.bam", "sample_id": "sample_0002"},
        ])
        self.assertEqual(source_list.read_bytes(), original)

    def test_duplicate_bams_are_rejected_before_run_creation(self):
        with self.assertRaisesRegex(ValidationError, "più volte"):
            self.invoke(bams=[self.bam, self.bam.parent / "." / self.bam.name])
        self.assert_not_started()

    def test_empty_or_conflicting_bam_modes_are_rejected_before_run_creation(self):
        for arguments in ({"bams": []}, {"bam": None},
                          {"bam": self.bam, "bams": [self.bam]}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValidationError):
                    self.invoke(**arguments)
                self.assert_not_started()

    def test_invalid_panel_is_rejected_before_run_creation(self):
        self.panel.write_text("chr1\t100\t102\tAA\tCC\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "pos2 deve essere"):
            self.invoke()
        self.assert_not_started()

    def test_no_bam_index_is_required_or_created(self):
        candidates = [Path(str(self.bam) + suffix) for suffix in (".bai", ".csi")]
        candidates += [self.bam.with_suffix(suffix) for suffix in (".bai", ".csi")]
        self.assertTrue(all(not path.exists() for path in candidates))
        self.invoke()
        self.assertTrue(all(not path.exists() for path in candidates))
        mappings = self.runner.records[0][1]["mounts"].mappings
        self.assertFalse(any(
            item["container_path"].endswith((".bai", ".csi")) for item in mappings
        ))
        self.assertEqual(len(self.runner.calls), 1)

    def test_missing_fasta_index_is_rejected_before_run_creation(self):
        self.fai.unlink()
        with self.assertRaisesRegex(ValidationError, "Indice FASTA"):
            self.invoke()
        self.assert_not_started()

    def test_compressed_reference_and_available_bam_indexes_keep_safe_aliases(self):
        reference = self.write_file(self.external / "genome $ compressed.bgz", b"BGZF fixture\n")
        fai = self.write_file(Path(str(reference) + ".fai"), b"FAI fixture\n")
        gzi = self.write_file(Path(str(reference) + ".gzi"), b"GZI fixture\n")
        bai = self.write_file(self.bam.with_suffix(".bai"), b"BAI fixture\n")
        csi = self.write_file(Path(str(self.bam) + ".csi"), b"CSI fixture\n")
        run = self.invoke(reference=reference)
        self.assertEqual(self.request_for(run)["reference"], "/workspace/inputs/reference/genome.fa.gz")
        record = self.runner.records[0][1]
        mounted = {Path(item["host_path"]): item["container_path"]
                   for item in record["mounts"].mappings}
        for path, alias in (
            (reference, "/workspace/inputs/reference/genome.fa.gz"),
            (fai, "/workspace/inputs/reference/genome.fa.gz.fai"),
            (gzi, "/workspace/inputs/reference/genome.fa.gz.gzi"),
            (bai, "/workspace/inputs/bams/sample_0001.bam.bai"),
            (csi, "/workspace/inputs/bams/sample_0001.bam.csi"),
        ):
            self.assertEqual(mounted[path], alias)
            self.assertIn(path, record["inputs"])

    def test_missing_compressed_reference_index_is_rejected_before_run_creation(self):
        reference = self.write_file(self.external / "genome.fa.gz", b"BGZF fixture\n")
        self.write_file(Path(str(reference) + ".fai"), b"FAI fixture\n")
        with self.assertRaisesRegex(ValidationError, "Indice FASTA BGZF"):
            self.invoke(reference=reference)
        self.assert_not_started()

    def test_parallel_flag_matches_requested_mode(self):
        serial = self.invoke(parallel=False, run_name="serial")
        parallel = self.invoke(parallel=True, run_name="parallel")
        self.assertIs(self.request_for(serial)["parallel"], False)
        self.assertIs(self.request_for(parallel)["parallel"], True)
        self.assertFalse(self.runner.records[0][1]["parameters"]["parallel"])
        self.assertTrue(self.runner.records[1][1]["parameters"]["parallel"])

    def test_panel_normalization_is_delegated_without_altering_source(self):
        original = b"chr1 100 101 aa cC\nchr2\t200\t201\tgT\tAC\n"
        self.panel.write_bytes(original)
        run = self.invoke()
        self.assertFalse((run / "work" / "DNP_list.txt").exists())
        self.assertEqual(self.panel.read_bytes(), original)
        self.assertEqual(self.request_for(run)["panel"], "/workspace/inputs/dnp-panel.txt")
        record = self.runner.records[0][1]
        self.assertIn(self.panel, record["inputs"])
        self.assertIn({"host_path": str(self.panel),
                       "container_path": "/workspace/inputs/dnp-panel.txt", "read_only": True},
                      record["mounts"].mappings)


if __name__ == "__main__":
    unittest.main()
