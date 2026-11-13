"""Client contracts and guided flows for all five scientific modules."""
from contextlib import nullcontext, redirect_stdout
from itertools import combinations
import io
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from nipat.analysis_forms import AnalysisForm
from nipat.cli import main
from nipat.errors import ValidationError
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.preferences import Preferences, PreferencesStore
from nipat.scientific_options import load_scientific_config, edit_scientific_settings
from nipat.terminal import Terminal
from nipat.wizard import run_wizard
from nipat_scientific.settings import defaults


class RecordingRunner:
    def __init__(self):
        self.records, self.calls = [], []

    def record_run(self, run_dir, **kwargs):
        self.records.append((run_dir, kwargs))
        return nullcontext()

    def run(self, command, **kwargs):
        self.calls.append((command, kwargs))


class FiveModuleClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        project = self.root / "project"
        project.mkdir()
        self.layout = ProjectLayout(project, self.root, self.root / "data", self.root / "runs", project / "compose.yaml")
        self.runner = RecordingRunner()
        self.workflows = Workflows(self.layout, self.runner)
        self.bams = [(name, self.file(name + " $ space.bam", name)) for name in ("Plasma", "Mother", "Father", "Child")]
        self.reference = self.file("ref.fa", ">chr1\nACGT\n")
        self.file("ref.fa.fai", "chr1\t4\t6\t4\t5\n")
        self.dnp_panel = self.file("dnp.tsv", "chr1\t2\t3\tCG\tAT\n")
        self.snp_panel = self.file("snp.tsv", "chr\tpos\tref\talt\nchr1\t2\tC\tA\n")
        self.dnp_freq = self.file("dnp-pop.tsv", "chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\nchr1\t2\t3\t0.6\t0.4\n")
        self.snp_freq = self.file("snp-pop.tsv", "chr\tpos\tRef_f.pop\tAlt_f.pop\nchr1\t2\t0.6\t0.4\n")
        self.snp_tables = [(name, self.file("snp-" + name + ".txt",
            "chr\tpos\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\nchr1\t2\tC\tA\t50\t50\t0\t100\n"))
            for name in ("Plasma", "Mother", "Father", "Child")]
        self.dnp_tables = [(name, self.file("dnp-" + name + ".txt",
            "chr\tpos1\tpos2\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\nchr1\t2\t3\tCG\tAT\t50\t50\t0\t100\n"))
            for name in ("Plasma", "Mother", "Father", "Child")]

    def file(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def arguments(self, caller="both", analyses=None):
        analyses = analyses if analyses is not None else ["contamination", "cpi", "cpin"]
        return dict(caller=caller, analyses=analyses,
                    samples=self.bams if caller != "tables" else None,
                    reference=self.reference if caller != "tables" else None,
                    dnp_tables=self.dnp_tables if caller == "tables" else None,
                    snp_tables=self.snp_tables if caller == "tables" else None,
                    dnp_panel=self.dnp_panel, snp_panel=self.snp_panel,
                    dnp_popfreq=self.dnp_freq, snp_popfreq=self.snp_freq,
                    dnp_contamination_panel=self.dnp_panel, snp_contamination_panel=self.snp_panel,
                    pairs=[("Prenatal", "Plasma", "Father")] if "cpi" in analyses else None,
                    trios=[("Postnatal", "Mother", "Father", "Child")] if "cpin" in analyses else None)

    def plan(self, run):
        return json.loads((run / "work" / "engine-plan.json").read_text())

    def test_all_consumer_subsets_for_each_caller_and_imported_tables(self):
        for caller in ("dnp", "snp", "both", "tables"):
            for size in (1, 2, 3):
                for subset in combinations(("contamination", "cpi", "cpin"), size):
                    with self.subTest(caller=caller, analyses=subset):
                        run = self.workflows.analyze(**self.arguments(caller, list(subset)),
                                                     run_name=caller + "-" + "-".join(subset))
                        plan = self.plan(run)
                        branches = 2 if caller in {"both", "tables"} else 1
                        consumers = [step for step in plan["steps"] if step["workflow"] in subset]
                        self.assertEqual(len(consumers), branches * len(subset))
                        for step in consumers:
                            marker = step["parameters"]["marker_type"]
                            self.assertTrue(step["id"].startswith(marker.lower() + "_"))
                            self.assertEqual(step["parameters"]["scientific_settings"], defaults(step["workflow"]))
                        self.assertEqual(self.runner.records[-1][1]["bundled_workflow"], "workflow-plan-all")
                        self.assertTrue(all(item["read_only"] for item in self.runner.records[-1][1]["mounts"].mappings))
                        self.assertEqual(len(self.runner.calls), len(self.runner.records))

    def test_asymmetric_branches_execute_only_the_selected_analyses(self):
        cases = ((["cpi"], ["contamination"]), (["cpin"], ["cpi"]))
        for number, (dnp_analyses, snp_analyses) in enumerate(cases):
            with self.subTest(dnp=dnp_analyses, snp=snp_analyses):
                selected = list(set(dnp_analyses + snp_analyses))
                args = self.arguments("both", selected)
                args.update(dnp_analyses=dnp_analyses, snp_analyses=snp_analyses,
                            snp_popfreq=self.snp_freq if "cpi" in snp_analyses else None,
                            run_name=f"asymmetric-{number}")
                plan = self.plan(self.workflows.analyze(**args))
                consumers = {step["id"] for step in plan["steps"] if step["workflow"] in selected}
                self.assertEqual(consumers, {*("dnp_" + name for name in dnp_analyses),
                                             *("snp_" + name for name in snp_analyses)})

    def test_asymmetric_imports_do_not_require_unused_population_or_roles(self):
        args = self.arguments("tables", ["contamination"])
        args.update(dnp_analyses=[], snp_analyses=["contamination"], dnp_popfreq=None, snp_popfreq=None)
        plan = self.plan(self.workflows.analyze(**args))
        self.assertEqual([step["id"] for step in plan["steps"]], ["snp_contamination"])

    def test_guided_asymmetric_branches_expose_only_the_needed_files_and_roles(self):
        form = AnalysisForm("1", Mock(), self.layout, 0.001)
        form.values.update(source="bam", marker="both", analyses="8", dnp_analyses="3", snp_analyses="2")
        keys = {field.key for field in form.fields()}
        self.assertTrue({"pairs", "trios", "dnp_popfreq", "snp_popfreq", "dnp_cpin_panel", "snp_cpi_cutoffs"} <= keys)
        self.assertTrue({"dnp_cpi_cutoffs", "snp_cpin_panel", "dnp_contamination_panel"}.isdisjoint(keys))

    def test_both_callers_share_bams_and_keep_family_roles_separate(self):
        run = self.workflows.analyze(**self.arguments())
        plan = self.plan(run)
        self.assertEqual(len(plan["samples"]), 4)
        steps = {step["id"]: step for step in plan["steps"]}
        for marker in ("dnp", "snp"):
            self.assertEqual(steps[marker + "_cpi"]["inputs"]["pairs"][0]["mother"]["sample"], "Plasma")
            self.assertEqual(steps[marker + "_cpin"]["inputs"]["trios"][0]["mother"]["sample"], "Mother")
            refs = steps[marker + "_contamination"]["inputs"]["samples"]
            self.assertEqual({ref["output"] for ref in refs}, {marker + "-tables"})

    def test_generated_plan_passes_engine_file_preflight_with_arbitrary_biological_ids(self):
        from nipat_scientific.executor import _preflight
        run = self.workflows.analyze(**self.arguments())
        plan = self.plan(run)
        runtime = self.root / "runtime"
        runtime.mkdir()
        mounts = self.runner.records[-1][1]["mounts"].mappings
        for mount in mounts:
            destination = runtime / mount["container_path"].lstrip("/")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(mount["host_path"], destination)
        def translated(value):
            if isinstance(value, str) and value.startswith("/workspace/"):
                return str(runtime / value.lstrip("/"))
            if isinstance(value, dict):
                return {key: translated(item) for key, item in value.items()}
            if isinstance(value, list):
                return [translated(item) for item in value]
            return value
        local_plan = translated(plan)
        script = self.file("placeholder.R", "# preflight verifies presence, without executing R\n")
        report, _, _ = _preflight(local_plan, runtime / "new-analysis",
                                  {name: script for name in ("dnp-call", "snp-call", "cpi", "cpin", "contamination")})
        samples = {sample["id"]: sample for sample in report["plan"]["samples"]}
        dnp = next(step for step in report["plan"]["steps"] if step["workflow"] == "dnp-call")
        self.assertEqual(dnp["inputs"]["samples"], ["Plasma", "Mother", "Father", "Child"])
        for number, sample_id in enumerate(dnp["inputs"]["samples"], 1):
            self.assertEqual(Path(samples[sample_id]["path"]).name, f"sample_{number:04d}.bam")

    def test_scientific_overrides_arrive_in_every_matching_step_and_run_metadata(self):
        self.workflows.scientific_settings = {"snp-call": {"min_base_quality": 17}, "cpin": {"min_child_reads": 8}}
        run = self.workflows.analyze(**self.arguments())
        for step in self.plan(run)["steps"]:
            if step["workflow"] == "snp-call":
                self.assertEqual(step["parameters"]["scientific_settings"]["min_base_quality"], 17)
            if step["workflow"] == "cpin":
                self.assertEqual(step["parameters"]["scientific_settings"]["min_child_reads"], 8)
        record = self.runner.records[-1][1]["parameters"]
        self.assertEqual(record["scientific_settings_requested"], self.workflows.scientific_settings)
        self.assertEqual(record["scientific_settings_effective"]["cpin"]["min_child_reads"], 8)

    def test_snp_pileup_can_feed_all_consumers_without_reference(self):
        arguments = self.arguments("snp")
        arguments.update(samples=None, reference=None,
                         pileups=[(name, self.file(name + ".pileup", "chr1\t2\tC\t1\t.\tI\tread1\n")) for name, _ in self.bams])
        plan = self.plan(self.workflows.analyze(**arguments))
        self.assertTrue(all(sample["kind"] == "snp-pileup" for sample in plan["samples"]))
        self.assertEqual({step["workflow"] for step in plan["steps"]}, {"snp-call", "contamination", "cpi", "cpin"})

    def test_invalid_roles_and_wrong_population_fail_before_run_allocation(self):
        for change in ({"trios": [("T", "Mother", "Father", "Mother")]},
                       {"pairs": [("P", "Missing", "Father")]},
                       {"snp_popfreq": self.dnp_freq}, {"samples": [("A", self.bams[0][1]), ("B", self.bams[0][1])]}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.workflows.analyze(**(self.arguments() | change))
        self.assertEqual(self.runner.records, [])
        self.assertFalse(self.layout.runs_dir.exists())

    def test_standalone_snp_consumers_and_cpin_native_contract(self):
        table_dir = self.root / "native"
        table_dir.mkdir()
        for role, identifier in (("Mother", "M"), ("Father", "F"), ("Child", "C")):
            (table_dir / (role + identifier + ".txt")).write_text(self.snp_tables[0][1].read_text())
        cpin = self.workflows.cpin(input_dir=table_dir, trios="M:F:C", popfreq=self.snp_freq)
        req = json.loads((cpin / "work" / "engine-request.json").read_text())
        self.assertEqual(req["workflow"], "cpin")
        self.assertEqual([sample["name"] for sample in req["samples"]], ["MotherM.txt", "FatherF.txt", "ChildC.txt"])
        cpi = self.workflows.cpi(input_dir=table_dir, pairs="M:F", mother_prefix="Mother", father_prefix="Father", popfreq=self.snp_freq)
        req = json.loads((cpi / "work" / "engine-request.json").read_text())
        self.assertEqual(req["marker_type"], "SNP")
        self.assertNotIn("err_const", req)
        contam = self.workflows.contamination(inputs=[self.snp_tables[0][1]], panel=self.snp_panel)
        req = json.loads((contam / "work" / "engine-request.json").read_text())
        self.assertEqual(req["marker_type"], "SNP")

    def test_settings_cli_exports_valid_config_without_runtime(self):
        export = self.root / "science.json"
        with patch("nipat.cli.DockerComposeRunner") as runner, redirect_stdout(io.StringIO()):
            result = main(["--set", "snp-call.min_base_quality=23", "settings", "--export", str(export)])
        self.assertEqual(result, 0)
        runner.assert_not_called()
        config = load_scientific_config(export)
        self.assertEqual(set(config), {"dnp-call", "snp-call", "contamination", "cpi", "cpin"})
        self.assertEqual(config["snp-call"]["min_base_quality"], 23)

    def test_cli_scientific_config_and_generic_roles_dispatch(self):
        config = self.file("config.json", '{"cpin":{"min_child_reads":9}}')
        with patch("nipat.cli.ProjectLayout.discover", return_value=self.layout), \
                patch("nipat.cli.DockerComposeRunner"), patch("nipat.cli.Workflows") as workflows, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--scientific-config", str(config), "--set", "snp-call.min_base_quality=21",
                "workflow", "analyze", "--caller", "snp", "--analyses", "cpi,cpin", "--sample", "M", "m.bam",
                "--pair", "P", "M", "F", "--trio", "T", "M", "F", "C"]), 0)
        self.assertEqual(workflows.call_args.kwargs["scientific_settings"],
                         {"cpin": {"min_child_reads": 9}, "snp-call": {"min_base_quality": 21}})
        call = workflows.return_value.analyze.call_args.kwargs
        self.assertEqual(call["pairs"], [["P", "M", "F"]])
        self.assertEqual(call["trios"], [["T", "M", "F", "C"]])

    def test_invalid_scientific_overrides_fail_before_runtime(self):
        for override in ("cpin.unknown=2", "cpi.err_const_snp=0", "snp-call.min_base_quality=true"):
            with self.subTest(override=override), self.assertRaises(ValidationError):
                load_scientific_config(overrides=[override])

    def test_guided_full_workflow_collects_roles_and_keeps_optional_fields(self):
        answers = ["1", "3", "7"]  # BAM, both callers, all consumers
        for name, path in self.bams:
            answers += [name, str(path)]
        answers += ["", str(self.reference), str(self.dnp_panel), str(self.snp_panel),
                    "Prenatal", "Plasma", "Father", "", "Postnatal", "Mother", "Father", "Child", "",
                    str(self.dnp_freq), "", "", "", str(self.snp_freq), "", "", "", "guided"]
        form = AnalysisForm("1", Terminal(read=Mock(side_effect=answers), write=lambda _: None), self.layout, 0.001)
        form.collect()
        arguments = form.arguments()
        self.assertEqual(arguments["caller"], "both")
        self.assertEqual(arguments["pairs"], [("Prenatal", "Plasma", "Father")])
        self.assertEqual(arguments["trios"], [("Postnatal", "Mother", "Father", "Child")])
        self.assertIsNone(arguments["dnp_cpi_cutoffs"])
        self.workflows.analyze(**arguments)

    def test_guided_cpin_dispatch_and_scientific_setting_persistence(self):
        run = self.layout.runs_dir / "result"
        (run / "output").mkdir(parents=True)
        workflows = Mock()
        workflows.cpin.return_value = run
        workflows.scientific_settings = {}
        store = PreferencesStore(self.root / "preferences.json")
        store.save(Preferences(scientific_settings={"cpin": {"min_child_reads": 12}}))
        seen = []
        workflows.cpin.side_effect = lambda **kwargs: seen.append(dict(workflows.scientific_settings)) or run
        answers = ["N", str(self.root), "M:F:C", "", "", "", str(self.snp_freq), "", "", "1", "0", "0"]
        status = run_wizard(workflows, self.layout, err_const=0.001, preferences_store=store,
                            read=Mock(side_effect=answers), write=lambda _: None)
        self.assertEqual(status, 0)
        workflows.cpin.assert_called_once()
        self.assertEqual(seen, [{"cpin": {"min_child_reads": 12}}])

    def test_editor_checks_combined_thresholds_and_failed_default_reset_is_atomic(self):
        ui = Mock()
        ui.menu.side_effect = ["4", "9"]
        ui.prompt.side_effect = ["heterozygous_min=0.7", "heterozygous_max=:default", ""]
        original = {"cpi": {"heterozygous_max": 0.8}}
        result = edit_scientific_settings(ui, original)
        self.assertEqual(result, {"cpi": {"heterozygous_min": 0.7, "heterozygous_max": 0.8}})
        self.assertEqual(original, {"cpi": {"heterozygous_max": 0.8}})
        self.assertTrue(any(call.kwargs.get("kind") == "error" for call in ui.message.call_args_list))

    def test_advanced_editor_validates_and_reverts_settings(self):
        ui = Mock()
        ui.menu.side_effect = ["5", "9"]
        ui.prompt.side_effect = ["min_child_reads=11", "min_child_reads=-1", ""]
        result = edit_scientific_settings(ui, {})
        self.assertEqual(result, {"cpin": {"min_child_reads": 11}})
        self.assertTrue(any(call.kwargs.get("kind") == "error" for call in ui.message.call_args_list))
