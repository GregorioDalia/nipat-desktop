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
            contamination_panel=self.panel, parallel=True, run_name="chosen", snp_panel=None,
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


    def cpi_arguments(self, **kwargs):
        father = self.write("father $ ,= è.bam", b"paternal BAM\n")
        popfreq = self.write("population.tsv", b"chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\nchr1\t100\t101\t0.6\t0.4\n")
        arguments = {"pairs": [("FamilyA", self.bam, father)], "reference": self.reference,
                     "panel": self.panel, "popfreq": popfreq, "run_name": "cpi-chain"}
        arguments.update(kwargs)
        return arguments

    def test_cpi_pairs_define_roles_and_only_one_container_with_all_default(self):
        arguments = self.cpi_arguments(err_const=0)
        originals = {path: path.read_bytes() for path in self.external.iterdir()}
        run = self.workflows.dnp_cpi(**arguments)
        plan = self.plan(run)
        self.assertEqual(validate_plan(plan)["execution_order"], ["dnp", "cpi"])
        cpi = plan["steps"][1]
        self.assertEqual(cpi["inputs"]["pairs"], [{
            "id": "FamilyA",
            "mother": {"step": "dnp", "output": "dnp-tables", "sample": "sample_0001"},
            "father": {"step": "dnp", "output": "dnp-tables", "sample": "sample_0002"},
        }])
        self.assertEqual(cpi["parameters"], {"err_const": 0, "cutoff_mode": "all"})
        self.assertEqual(cpi["inputs"]["cutoffs"], [])
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.calls[0][0][2], "execute-plan")
        record = self.runner.records[0][1]
        self.assertEqual(record["workflow"], "dnp-cpi")
        self.assertEqual(record["bundled_workflow"], "workflow-plan-cpi")
        self.assertEqual(record["parameters"]["pair_mapping"], [{
            "pair_id": "FamilyA", "mother_sample_id": "sample_0001", "father_sample_id": "sample_0002",
            "mother_bam": str(self.bam), "father_bam": str(arguments["pairs"][0][2]),
        }])
        self.assertTrue(all(item["read_only"] for item in record["mounts"].mappings))
        self.assertEqual({path: path.read_bytes() for path in self.external.iterdir()}, originals)
        self.assertFalse((run / "output" / "workflow").exists())

    def test_cpi_shared_parent_is_processed_once_and_pair_order_is_preserved(self):
        arguments = self.cpi_arguments()
        mother_b = self.write("second mother.bam", b"second maternal BAM\n")
        father = arguments["pairs"][0][2]
        arguments["pairs"] = [("FamilyB", mother_b, father), ("FamilyA", self.bam, father)]
        run = self.workflows.dnp_cpi(**arguments)
        plan = self.plan(run)
        self.assertEqual(len(plan["samples"]), 3)
        self.assertEqual(plan["steps"][0]["inputs"]["samples"],
                         ["sample_0001", "sample_0002", "sample_0003"])
        pairs = plan["steps"][1]["inputs"]["pairs"]
        self.assertEqual([pair["id"] for pair in pairs], ["FamilyB", "FamilyA"])
        self.assertEqual([pair["father"]["sample"] for pair in pairs], ["sample_0002", "sample_0002"])
        self.assertEqual([pair["mother"]["sample"] for pair in pairs], ["sample_0001", "sample_0003"])
        self.assertEqual(self.runner.records[0][1]["parameters"]["bams"],
                         [str(mother_b), str(father), str(self.bam)])

    def test_cpi_full_workflow_does_not_use_contamination_outputs_as_cpi_inputs(self):
        contamination_panel = self.write("contamination.tsv", b"chr1\t100\t101\n")
        arguments = self.cpi_arguments(include_contamination=True, contamination_panel=contamination_panel,
                                       parallel=True)
        run = self.workflows.dnp_cpi(**arguments)
        plan = self.plan(run)
        self.assertEqual(validate_plan(plan)["execution_order"], ["dnp", "contamination", "cpi"])
        self.assertIs(plan["steps"][0]["parameters"]["parallel"], True)
        self.assertEqual(plan["steps"][1]["inputs"]["panel"], "/workspace/inputs/contamination-panel.txt")
        for role in ("mother", "father"):
            self.assertEqual(plan["steps"][2]["inputs"]["pairs"][0][role]["step"], "dnp")
        self.assertEqual(self.runner.records[0][1]["workflow"], "dnp-contamination-cpi")
        self.assertEqual(len(self.runner.calls), 1)

    def test_cpi_cutoff_modes_keep_native_labels_and_distinct_dnp_panel(self):
        first = self.write("cutoff one.tsv", b"chr1\t100\t101\n")
        second = self.write("cutoff two.tsv", b"chr1\t200\t201\n")
        # The native comma syntax is exercised with a comma-free source path.
        simple = self.layout.project_dir / "native.tsv"
        simple.write_bytes(first.read_bytes())
        modes = [({"cpi_panel": first}, "panel", [""]),
                 ({"cutoffs": [("Full panel", first), ("Subset", second)]}, "named", ["Full panel", "Subset"]),
                 ({"cutoff_map": f"Native={simple}"}, "named", ["Native"]),
                 ({"cutoff_map": str(simple)}, "named", [str(simple)])]
        for index, (options, mode, labels) in enumerate(modes):
            with self.subTest(mode=mode, labels=labels):
                run = self.workflows.dnp_cpi(**self.cpi_arguments(run_name=f"cutoff-{index}", **options))
                plan = self.plan(run)
                self.assertEqual(plan["steps"][0]["inputs"]["panel"], "/workspace/inputs/dnp-panel.txt")
                cpi = plan["steps"][1]
                self.assertEqual(cpi["parameters"]["cutoff_mode"], mode)
                self.assertEqual([item["label"] for item in cpi["inputs"]["cutoffs"]], labels)
                self.assertTrue(all(item["path"].startswith("/workspace/inputs/cpi-cutoffs/")
                                    for item in cpi["inputs"]["cutoffs"]))

    def test_cpi_rejects_ambiguous_roles_duplicate_pairs_or_identifiers_before_creating_run(self):
        arguments = self.cpi_arguments()
        father = arguments["pairs"][0][2]
        pair_lists = [[], [("FamilyA", self.bam, self.bam)],
                      [("FamilyA", self.bam, father), ("FamilyB", father, self.bam)],
                      [("FamilyA", self.bam, father), ("FamilyB", self.bam, father)],
                      [("invalid id", self.bam, father)], [("A", self.bam)],
                      [("A", self.bam, father), ("a", self.write("other.bam", b"other"), father)]]
        for pairs in pair_lists:
            with self.subTest(pairs=pairs), self.assertRaises(ValidationError):
                self.workflows.dnp_cpi(**{**arguments, "pairs": pairs})
            self.assert_not_started()

    def test_cpi_detects_hard_link_aliases_for_deduplication_and_roles(self):
        arguments = self.cpi_arguments()
        father = arguments["pairs"][0][2]
        alias = self.external / "father hardlink.bam"
        try:
            alias.hardlink_to(father)
        except (OSError, NotImplementedError):
            self.skipTest("Hard links unavailable")
        with self.assertRaisesRegex(ValidationError, "sia cfDNA materno sia campione paterno"):
            self.workflows.dnp_cpi(**{**arguments, "pairs": [("A", alias, father)]})
        self.assert_not_started()
        mother_b = self.write("other mother.bam", b"maternal two")
        run = self.workflows.dnp_cpi(**{**arguments, "pairs": [
            ("A", self.bam, father), ("B", mother_b, alias),
        ]})
        plan = self.plan(run)
        self.assertEqual(len(plan["samples"]), 3)
        self.assertEqual({pair["father"]["sample"] for pair in plan["steps"][1]["inputs"]["pairs"]},
                         {"sample_0002"})
        self.assertEqual(self.runner.records[0][1]["parameters"]["pair_mapping"][1]["father_bam"], str(alias))

    def test_cpi_invalid_settings_are_rejected_before_creating_run(self):
        arguments = self.cpi_arguments()
        invalid = [{"err_const": float("nan")}, {"err_const": -1}, {"err_const": True},
                   {"parallel": "yes"}, {"include_contamination": 1},
                   {"contamination_panel": self.panel},
                   {"cpi_panel": self.panel, "cutoffs": [("A", self.panel)]},
                   {"cutoffs": []}, {"cutoff_map": ""}]
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(ValidationError):
                self.workflows.dnp_cpi(**{**arguments, **options})
            self.assert_not_started()
        arguments["popfreq"].write_text("chr\tpos1\tpos2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "Frequenze di popolazione"):
            self.workflows.dnp_cpi(**arguments)
        self.assert_not_started()

    def test_cpi_workflow_dry_run_records_pairs_without_starting_processes(self):
        arguments = self.cpi_arguments(include_contamination=True)
        self.workflows = Workflows(self.layout, DockerComposeRunner(self.layout, dry_run=True,
                                                                   transport=DockerTransport()))
        with patch("nipat.execution.runner.subprocess.Popen") as popen, \
                patch("nipat.execution.runner.subprocess.run") as process_run, \
                patch("nipat.execution.tracking.platform.platform", return_value="Test OS"), \
                redirect_stdout(io.StringIO()):
            run = self.workflows.dnp_cpi(**arguments)
        popen.assert_not_called()
        process_run.assert_not_called()
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "planned")
        self.assertEqual(record["bundled_workflow"], "workflow-plan-cpi")
        self.assertEqual(record["parameters"]["pair_mapping"][0]["pair_id"], "FamilyA")
        self.assertEqual(len(record["commands"]), 1)
        self.assertFalse((run / "output" / "workflow").exists())

    def test_cpi_cli_presets_dispatch_explicit_roles_and_complete_options(self):
        arguments = self.cpi_arguments()
        father = arguments["pairs"][0][2]
        for preset in ("dnp-cpi", "dnp-contamination-cpi"):
            argv = ["workflow", preset, "--pair", "FamilyA", str(self.bam), str(father),
                    "--reference", str(self.reference), "--panel", str(self.panel),
                    "--popfreq", str(arguments["popfreq"]), "--err-const", "0", "--parallel",
                    "--cutoff", "Full", str(self.panel), "--run-name", "chosen"]
            if preset == "dnp-contamination-cpi":
                argv += ["--contamination-panel", str(self.panel)]
            with self.subTest(preset=preset), \
                    patch("nipat.cli.ProjectLayout.discover", return_value=self.layout), \
                    patch("nipat.cli.activity_session", return_value=nullcontext()), \
                    patch("nipat.cli.DockerComposeRunner"), patch("nipat.cli.Workflows") as workflows, \
                    redirect_stdout(io.StringIO()):
                workflows.return_value.dnp_cpi.return_value = self.layout.runs_dir / "chosen"
                self.assertEqual(main(argv), 0)
                workflows.return_value.dnp_cpi.assert_called_once_with(
                    pairs=[("FamilyA", self.bam, father)], reference=self.reference, panel=self.panel,
                    popfreq=arguments["popfreq"], err_const=0.0, cpi_panel=None,
                    cutoffs=[("Full", self.panel)], cutoff_map=None,
                    include_contamination=preset == "dnp-contamination-cpi",
                    contamination_panel=self.panel if preset == "dnp-contamination-cpi" else None,
                    parallel=True, run_name="chosen", snp_panel=None,
                )
                workflows.return_value.dnp_call.assert_not_called()
                workflows.return_value.cpi.assert_not_called()

    def snp_panel(self):
        return self.write("SNP panel.tsv", b"pos\tref\talt\nchr1:100\tA\tC\n")

    def test_optional_snp_steps_reuse_each_bam_once_without_changing_dnp_handoff(self):
        panel = self.snp_panel()
        second = self.write("other/sample.bam", b"second BAM\n")
        run = self.invoke(bams=[self.bam, second], snp_panel=panel)
        plan = self.plan(run)
        self.assertEqual(validate_plan(plan)["execution_order"],
                         ["dnp", "contamination", "snp_0001", "snp_0002"])
        for number, step in enumerate(plan["steps"][2:], 1):
            self.assertEqual(step, {"id": f"snp_{number:04d}", "workflow": "snp-call",
                                   "inputs": {"sample": f"sample_{number:04d}",
                                              "reference": "/workspace/inputs/reference/genome.fa",
                                              "panel": "/workspace/inputs/snp-list.tsv"},
                                   "parameters": {"mode": "bam"}})
        self.assertEqual(plan["steps"][1]["inputs"]["samples"][0]["step"], "dnp")
        record = self.runner.records[0][1]
        self.assertEqual(record["bundled_workflow"], "workflow-plan-with-snp")
        self.assertEqual(record["parameters"]["snp_panel"], str(panel))
        self.assertEqual(record["parameters"]["expected_steps"][-1], {
            "id": "snp_0002", "workflow": "snp-call", "sample": "sample_0002", "mode": "bam",
        })
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(sum(item["host_path"] == str(self.bam)
                             for item in record["mounts"].mappings), 1)

    def test_cpi_shared_parent_generates_only_one_independent_snp_step(self):
        arguments = self.cpi_arguments(include_contamination=True, snp_panel=self.snp_panel())
        father = arguments["pairs"][0][2]
        another = self.write("other_mother.bam", b"other maternal BAM\n")
        arguments["pairs"].append(("FamilyB", another, father))
        run = self.workflows.dnp_cpi(**arguments)
        plan = self.plan(run)
        self.assertEqual(validate_plan(plan)["execution_order"],
                         ["dnp", "contamination", "cpi", "snp_0001", "snp_0002", "snp_0003"])
        self.assertEqual([step["inputs"]["sample"] for step in plan["steps"][3:]],
                         ["sample_0001", "sample_0002", "sample_0003"])
        self.assertTrue(all(pair["father"]["step"] == "dnp" for pair in plan["steps"][2]["inputs"]["pairs"]))
        self.assertEqual(self.runner.records[0][1]["bundled_workflow"], "workflow-plan-with-snp")

    def test_invalid_snp_panel_is_rejected_before_any_dnp_run(self):
        for invoke in (self.invoke, lambda **options: self.workflows.dnp_cpi(**self.cpi_arguments(**options))):
            with self.assertRaisesRegex(ValidationError, "lista SNP"):
                invoke(snp_panel=self.panel)
            self.assert_not_started()

    def test_snp_batch_bamlist_maps_duplicate_basenames_and_records_one_plan(self):
        first = self.write("one/sample.bam", b"one\n")
        second = self.write("two/sample.bam", b"two\n")
        listing = self.write("batch.txt", b"two/sample.bam\none/sample.bam\n")
        run = self.workflows.snp_batch(bamlist=listing, reference=self.reference,
                                       panel=self.snp_panel(), run_name="snp-batch")
        plan = self.plan(run)
        self.assertEqual(validate_plan(plan)["execution_order"], ["snp_0001", "snp_0002"])
        self.assertEqual([sample["kind"] for sample in plan["samples"]], ["bam", "bam"])
        record = self.runner.records[0][1]
        self.assertEqual(record["workflow"], "snp-batch")
        self.assertEqual(record["bundled_workflow"], "workflow-plan-snp")
        self.assertEqual(record["parameters"]["bams"], [str(second), str(first)])
        self.assertEqual(record["parameters"]["pileups"], [])
        self.assertIn(listing, record["inputs"])
        self.assertTrue(all(item["read_only"] for item in record["mounts"].mappings))
        self.assertEqual(len(self.runner.calls), 1)
        self.assertFalse((run / "output" / "workflow").exists())

    def test_snp_batch_pileups_need_no_reference_and_preserve_original_bytes(self):
        first = self.write("a/snp.txt", b"chr1\t100\tA\t2\t.,\tII\tread1,read2\n")
        second = self.write("b/snp.txt", b"chr1\t100\tA\t1\t.\tI\tread1\n")
        originals = {first: first.read_bytes(), second: second.read_bytes()}
        run = self.workflows.snp_batch(pileups=[first, second], panel=self.snp_panel())
        plan = self.plan(run)
        self.assertEqual([sample["kind"] for sample in plan["samples"]], ["snp-pileup", "snp-pileup"])
        self.assertTrue(all(step["inputs"]["reference"] is None for step in plan["steps"]))
        self.assertTrue(all(step["parameters"] == {"mode": "pileup"} for step in plan["steps"]))
        record = self.runner.records[0][1]
        self.assertEqual(record["parameters"]["reference"], None)
        self.assertEqual(record["parameters"]["pileups"], [str(first), str(second)])
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.assertEqual(len(self.runner.calls), 1)

    def test_snp_batch_rejects_invalid_mode_reference_and_empty_selection_before_run(self):
        pileup = self.write("snp.txt", b"chr1\t100\tA\t1\t.\tI\tread1\n")
        panel = self.snp_panel()
        options = [{}, {"bams": []}, {"bams": [self.bam]}, {"pileups": []},
                   {"pileups": [pileup], "reference": self.reference},
                   {"bams": [self.bam], "reference": self.reference, "pileups": [pileup]},
                   {"pileups": [pileup, pileup]},
                   {"bams": [self.bam, self.bam], "reference": self.reference}]
        for selected in options:
            with self.subTest(selected=selected), self.assertRaises(ValidationError):
                self.workflows.snp_batch(panel=panel, **selected)
            self.assert_not_started()
        pileup.write_text("chr1\t100\tA\t1\t.\tI\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "7 colonne"):
            self.workflows.snp_batch(panel=panel, pileups=[pileup])
        self.assert_not_started()

    def test_hardlink_duplicate_inputs_are_rejected_before_allocating_run(self):
        alias = self.external / "same.bam"
        try:
            alias.hardlink_to(self.bam)
        except (OSError, NotImplementedError):
            self.skipTest("Platform does not permit hard links")
        with self.assertRaisesRegex(ValidationError, "stesso BAM"):
            self.workflows.snp_batch(bams=[self.bam, alias], reference=self.reference, panel=self.snp_panel())
        self.assert_not_started()
        with self.assertRaisesRegex(ValidationError, "stesso BAM"):
            self.invoke(bams=[self.bam, alias])
        self.assert_not_started()
        pileup = self.write("original.txt", b"chr1\t100\tA\t1\t.\tI\tread1\n")
        duplicate = self.external / "same.txt"
        duplicate.hardlink_to(pileup)
        with self.assertRaisesRegex(ValidationError, "stesso pileup"):
            self.workflows.snp_batch(pileups=[pileup, duplicate], panel=self.snp_panel())
        self.assert_not_started()

    def test_snp_batch_dry_run_never_invokes_runtime_or_writes_results(self):
        self.workflows = Workflows(self.layout, DockerComposeRunner(self.layout, dry_run=True,
                                                                   transport=DockerTransport()))
        with patch("nipat.execution.runner.subprocess.Popen") as popen, \
                patch("nipat.execution.runner.subprocess.run") as process_run, redirect_stdout(io.StringIO()):
            run = self.workflows.snp_batch(bams=[self.bam], reference=self.reference, panel=self.snp_panel())
        popen.assert_not_called()
        process_run.assert_not_called()
        record = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "planned")
        self.assertEqual(record["bundled_workflow"], "workflow-plan-snp")
        self.assertEqual(len(record["commands"]), 1)
        self.assertFalse((run / "output" / "workflow").exists())

    def test_snp_cli_dispatches_batch_and_optional_panel_without_separate_analyses(self):
        panel = self.snp_panel()
        for options, expected in ((["--bam", str(self.bam), "--reference", str(self.reference)],
                                   {"bams": [self.bam], "bamlist": None, "pileups": None,
                                    "reference": self.reference}),
                                  (["--pileup", "a.txt", "--pileup", "b.txt"],
                                   {"bams": None, "bamlist": None, "pileups": [Path("a.txt"), Path("b.txt")],
                                    "reference": None})):
            argv = ["workflow", "snp-batch", *options, "--panel", str(panel), "--run-name", "batch"]
            with patch("nipat.cli.ProjectLayout.discover", return_value=self.layout), \
                    patch("nipat.cli.activity_session", return_value=nullcontext()), \
                    patch("nipat.cli.DockerComposeRunner"), patch("nipat.cli.Workflows") as workflows, \
                    redirect_stdout(io.StringIO()):
                workflows.return_value.snp_batch.return_value = self.layout.runs_dir / "batch"
                self.assertEqual(main(argv), 0)
                workflows.return_value.snp_batch.assert_called_once_with(
                    **expected, panel=panel, run_name="batch")
                workflows.return_value.snp_call.assert_not_called()
        args = build_parser().parse_args(["workflow", "dnp-contamination", "--bam", "a.bam",
                                         "--reference", "ref.fa", "--panel", "dnp.tsv",
                                         "--snp-panel", str(panel)])
        self.assertEqual(args.snp_panel, panel)


if __name__ == "__main__":
    unittest.main()
