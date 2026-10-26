"""Client integration for a single image-owned DNPcall → Contamination plan."""

import io
import json
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from nipat.cli import build_parser, main
from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.transport import DockerTransport
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat_scientific.plan import validate_plan


class RecordingRunner:
    def __init__(self):
        self.records = []
        self.calls = []

    def record_run(self, run_dir, **kwargs):
        self.records.append((run_dir, kwargs))
        return nullcontext()

    def run(self, command, *, working_dir=None):
        self.calls.append((list(map(str, command)), str(working_dir)))


class WorkflowClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        project = self.root / "project"
        project.mkdir()
        self.layout = ProjectLayout(project, self.root, self.root / "data", self.root / "results",
                                    project / "compose.yaml")
        self.external = self.root / "external inputs $ ,= è"
        self.external.mkdir()
        self.bam = self.write("sample $ ,= è.bam", b"BAM fixture\n")
        self.reference = self.write("genome $ ,= è.fa", b">chr1\nACGT\n")
        self.fai = self.write(self.reference.name + ".fai", b"chr1\t4\t6\t4\t5\n")
        self.panel = self.write("DNP panel.tsv", b"chr1\t100\t101\tAA\tCC\n")
        self.runner = RecordingRunner()
        self.workflows = Workflows(self.layout, self.runner)

    def write(self, name, content):
        target = self.external / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target.resolve()

    def invoke(self, **kwargs):
        arguments = {"reference": self.reference, "panel": self.panel, "run_name": "chain"}
        arguments.update(kwargs)
        if not {"bam", "bams", "bamlist"}.intersection(kwargs):
            arguments["bam"] = self.bam
        return self.workflows.dnp_contamination(**arguments)

    @staticmethod
    def plan(run):
        return json.loads((run / "work" / "engine-plan.json").read_text(encoding="utf-8"))

    def assert_not_started(self):
        self.assertFalse(self.layout.runs_dir.exists())
        self.assertEqual(self.runner.records, [])
        self.assertEqual(self.runner.calls, [])

    def test_one_container_hands_off_typed_outputs_and_records_exact_host_identity(self):
        originals = {path: path.read_bytes() for path in self.external.iterdir()}
        run = self.invoke()
        self.assertEqual(len(self.runner.calls), 1)
        command, working_dir = self.runner.calls[0]
        self.assertEqual(command, [
            "python3", "/opt/nipat/engine/main.py", "execute-plan", "--plan",
            str(self.layout.container_path(run / "work" / "engine-plan.json")),
            "--run-dir", str(self.layout.container_path(run / "output" / "workflow")),
        ])
        self.assertEqual(working_dir, str(self.layout.container_path(run / "work")))
        self.assertFalse((run / "output" / "workflow").exists())
        self.assertEqual({path.name for path in (run / "work").iterdir()}, {"engine-plan.json"})
        plan = self.plan(run)
        self.assertEqual(validate_plan(plan)["execution_order"], ["dnp", "contamination"])
        self.assertEqual(plan["samples"], [{"id": "sample_0001", "kind": "bam",
                                            "path": "/workspace/inputs/bams/sample_0001.bam"}])
        self.assertEqual(plan["steps"][1]["inputs"]["samples"], [
            {"step": "dnp", "output": "dnp-tables", "sample": "sample_0001"},
        ])
        self.assertEqual(plan["steps"][0]["inputs"]["panel"], plan["steps"][1]["inputs"]["panel"])
        record = self.runner.records[0][1]
        self.assertEqual(record["workflow"], "dnp-contamination")
        self.assertEqual(record["bundled_workflow"], "workflow-plan")
        self.assertEqual(record["parameters"]["sample_mapping"], [{
            "sample_id": "sample_0001", "original_path": str(self.bam),
            "container_path": "/workspace/inputs/bams/sample_0001.bam",
        }])
        self.assertEqual(set(record["inputs"]), set(originals))
        self.assertTrue(all(item["read_only"] for item in record["mounts"].mappings))
        self.assertEqual({path: path.read_bytes() for path in self.external.iterdir()}, originals)
        self.assertTrue(all(str(self.external) not in part for part in command))

    def test_bamlist_selection_preserves_order_and_separates_same_basenames(self):
        first = self.write("one/sample.bam", b"one\n")
        second = self.write("two/sample.bam", b"two\n")
        listing = self.write("selected.txt", b'"two/sample.bam"\n\n\'one/sample.bam\'\n')
        run = self.invoke(bamlist=listing, parallel=True)
        plan = self.plan(run)
        record = self.runner.records[0][1]
        self.assertEqual(record["parameters"]["bams"], [str(second), str(first)])
        self.assertEqual([item["original_path"] for item in record["parameters"]["sample_mapping"]],
                         [str(second), str(first)])
        self.assertEqual(plan["steps"][0]["inputs"]["samples"], ["sample_0001", "sample_0002"])
        self.assertIs(plan["steps"][0]["parameters"]["parallel"], True)
        self.assertEqual([item["sample"] for item in plan["steps"][1]["inputs"]["samples"]],
                         ["sample_0001", "sample_0002"])
        self.assertIn(listing, record["inputs"])
        self.assertFalse(any(item["host_path"] == str(listing) for item in record["mounts"].mappings))

    def test_separate_contamination_panel_is_mounted_and_recorded_without_normalization(self):
        panel = self.write("contamination panel.tsv", b"pos2\tchr\tpos1\n105\tchr1\t100\n")
        original = panel.read_bytes()
        run = self.invoke(contamination_panel=panel)
        plan = self.plan(run)
        self.assertEqual(plan["steps"][1]["inputs"]["panel"], "/workspace/inputs/contamination-panel.txt")
        record = self.runner.records[0][1]
        self.assertEqual(record["parameters"]["contamination_panel"], str(panel))
        self.assertIn(panel, record["inputs"])
        self.assertIn({"host_path": str(panel), "container_path": "/workspace/inputs/contamination-panel.txt",
                       "read_only": True}, record["mounts"].mappings)
        self.assertEqual(panel.read_bytes(), original)

    def test_invalid_selections_or_parallel_values_create_no_run(self):
        for kwargs in ({"bams": []}, {"bams": [self.bam, self.bam]},
                       {"bam": self.bam, "bamlist": self.panel},
                       {"parallel": "yes"}, {"parallel": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                self.invoke(**kwargs)
            self.assert_not_started()

    def test_invalid_secondary_panel_or_missing_fasta_index_create_no_run(self):
        panel = self.write("invalid.tsv", b"not\ta\tpanel\n")
        with self.assertRaises(ValidationError):
            self.invoke(contamination_panel=panel)
        self.assert_not_started()
        self.fai.unlink()
        with self.assertRaisesRegex(ValidationError, "Indice FASTA"):
            self.invoke()
        self.assert_not_started()

    def test_dry_run_never_starts_runtime_or_creates_scientific_results(self):
        self.workflows = Workflows(self.layout, DockerComposeRunner(
            self.layout, dry_run=True, transport=DockerTransport(),
        ))
        with patch("nipat.execution.runner.subprocess.Popen") as popen, \
                patch("nipat.execution.runner.subprocess.run") as process_run, \
                patch("nipat.execution.tracking.platform.platform", return_value="Test OS"), \
                redirect_stdout(io.StringIO()):
            run = self.invoke()
        popen.assert_not_called()
        process_run.assert_not_called()
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "planned")
        self.assertEqual(record["engine_verification"], "not_run_dry_run")
        self.assertEqual(len(record["commands"]), 1)
        self.assertIn("execute-plan", record["commands"][0]["argv"])
        self.assertFalse((run / "output" / "workflow").exists())
        compose = json.loads((run / "work" / "engine-compose.json").read_text(encoding="utf-8"))
        volumes = compose["services"]["scientific"]["volumes"]
        writable = [item for item in volumes if not item["read_only"]]
        self.assertEqual(len(writable), 1)
        self.assertEqual(writable[0]["target"], str(self.layout.container_path(run)))
        self.assertFalse(any(item["source"] == str(self.layout.project_dir) for item in volumes))

    def test_failure_keeps_parent_failed_and_does_not_launch_second_container(self):
        runner = DockerComposeRunner(self.layout, transport=DockerTransport())
        self.workflows = Workflows(self.layout, runner)
        def prepare():
            runner._image_id = "sha256:" + "1" * 64
        with patch.object(runner, "_prepare_runtime", side_effect=prepare), \
                patch.object(runner, "_describe_bundled_engine"), \
                patch.object(runner, "run", side_effect=RuntimeExecutionError("step dnp failed")) as run, \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeExecutionError, "step dnp failed"):
                self.invoke()
        run.assert_called_once()
        record = json.loads((self.layout.runs_dir / "chain" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error"]["type"], "RuntimeExecutionError")
        self.assertTrue((self.layout.runs_dir / "chain" / "work" / "engine-plan.json").is_file())

    def test_existing_run_is_never_reused(self):
        run = self.invoke()
        original = (run / "work" / "engine-plan.json").read_bytes()
        with self.assertRaisesRegex(ValidationError, "esiste già"):
            self.invoke()
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual((run / "work" / "engine-plan.json").read_bytes(), original)

    def test_cli_exposes_complete_preset_and_dispatches_once(self):
        argv = ["workflow", "dnp-contamination", "--bam", str(self.bam),
                "--reference", str(self.reference), "--panel", str(self.panel),
                "--contamination-panel", str(self.panel), "--parallel", "--run-name", "chosen"]
        args = build_parser().parse_args(argv)
        self.assertEqual(args.preset, "dnp-contamination")
        self.assertEqual(args.bam, [self.bam])
        with patch("nipat.cli.ProjectLayout.discover", return_value=self.layout), \
                patch("nipat.cli.activity_session", return_value=nullcontext()), \
                patch("nipat.cli.DockerComposeRunner"), \
                patch("nipat.cli.Workflows") as workflows, redirect_stdout(io.StringIO()):
            workflows.return_value.dnp_contamination.return_value = self.layout.runs_dir / "chosen"
            self.assertEqual(main(argv), 0)
        workflows.return_value.dnp_contamination.assert_called_once_with(
            bams=[self.bam], bamlist=None, reference=self.reference, panel=self.panel,
            contamination_panel=self.panel, parallel=True, run_name="chosen",
        )
        workflows.return_value.dnp_call.assert_not_called()
        workflows.return_value.contamination.assert_not_called()

    def test_cli_preset_requires_complete_and_unambiguous_input(self):
        parser = build_parser()
        variants = [
            ["workflow"], ["workflow", "unknown"],
            ["workflow", "dnp-contamination"],
            ["workflow", "dnp-contamination", "--bam", "a.bam", "--bamlist", "files.txt",
             "--reference", "ref.fa", "--panel", "panel.tsv"],
        ]
        for argv in variants:
            with self.subTest(argv=argv), redirect_stdout(io.StringIO()), \
                    patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(argv)


if __name__ == "__main__":
    unittest.main()
