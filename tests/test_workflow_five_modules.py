"""Typed five-module plans preserve biological roles and caller identities."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from nipat_scientific.errors import ValidationError
from nipat_scientific.executor import _preflight
from nipat_scientific.files import require_count_input
from nipat_scientific.panels import read_position_panel, write_position_panel
from nipat_scientific.plan import PlanValidationError, validate_plan
from nipat_scientific.outputs import _cpin_bindings
from nipat_scientific.presentation import step_presentation, validate_request_presentation


def plan_for(marker="SNP", *, called=True):
    samples = [{"id": name, "kind": "bam" if called else marker.lower() + "-table",
                "path": f"/input/{name}.bam" if called else f"/input/{name}.tsv"}
               for name in ("mother", "father", "child")]
    steps = []
    if called and marker == "SNP":
        steps = [{"id": "call_" + sample["id"], "workflow": "snp-call", "inputs": {
            "sample": sample["id"], "panel": "/input/panel.tsv", "reference": "/input/ref.fa"},
            "parameters": {"mode": "bam"}} for sample in samples]
    elif called:
        steps = [{"id": "call", "workflow": "dnp-call", "inputs": {"samples": [s["id"] for s in samples],
                 "panel": "/input/panel.tsv", "reference": "/input/ref.fa"}, "parameters": {"parallel": True}}]
    def ref(sample):
        return {"sample": sample, **({"step": "call_" + sample if marker == "SNP" else "call",
            "output": marker.lower() + "-tables"} if called else {})}
    steps.extend([
        {"id": "contamination", "workflow": "contamination", "inputs": {
            "samples": [ref(s["id"]) for s in samples], "panel": "/input/panel.tsv"}, "parameters": {}},
        {"id": "prenatal", "workflow": "cpi", "inputs": {
            "pairs": [{"id": "prenatal_family", "mother": ref("mother"), "father": ref("father")}],
            "popfreq": "/input/frequency.tsv", "cutoffs": []}, "parameters": {"cutoff_mode": "all"}},
        {"id": "postnatal", "workflow": "cpin", "inputs": {
            "trios": [{"id": "trio_family", "mother": ref("mother"), "father": ref("father"), "child": ref("child")}],
            "popfreq": "/input/frequency.tsv", "markers": None}, "parameters": {"scientific_settings": {"min_child_reads": 5}}},
    ])
    return {"schema_version": 1, "samples": samples, "steps": steps,
            "presentation": {"samples": {s["id"]: s["id"] + ".bam" for s in samples},
                             "pairs": {"trio_family": "Famiglia A"}}}


class FiveModulePlans(unittest.TestCase):
    def test_imported_shared_parents_are_scanned_once_per_validation_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            shutil.copytree(Path(__file__).parent / "fixtures/cpin/SNP", inputs)
            source = plan_for(called=False)
            for sample, name in zip(source["samples"], ("MotherM1.txt", "FatherF1.txt", "ChildC1.txt")):
                sample["path"] = str(inputs / name)
            extra = inputs / "ChildC2.txt"
            shutil.copyfile(inputs / "ChildC1.txt", extra)
            source["samples"].append({"id": "child_two", "kind": "snp-table", "path": str(extra)})
            source["presentation"]["samples"]["child_two"] = "ChildC2.txt"
            source["steps"][-1]["inputs"]["trios"].append({"id": "trio_two", "mother": {"sample": "mother"},
                "father": {"sample": "father"}, "child": {"sample": "child_two"}})
            for step in source["steps"]:
                for field, name in (("panel", "markers.tsv"), ("popfreq", "population.txt")):
                    if field in step["inputs"]:
                        step["inputs"][field] = str(inputs / name)
            scripts = {workflow: Path(__file__) for workflow in ("cpi", "cpin", "contamination")}
            with patch("nipat_scientific.executor.require_count_input", wraps=require_count_input) as scan:
                _preflight(source, root / "run", scripts)
            keys = [(call.args[0], call.kwargs["marker_type"], call.kwargs["cpi"]) for call in scan.call_args_list]
            self.assertEqual(len(keys), 7)  # 3 contamination contracts + 4 CPI/CPIN contracts.
            self.assertEqual(len(set(keys)), len(keys))
            self.assertFalse((root / "run").exists())
            # Cache lifetime is only this preflight: edited input must be read
            # and rejected on the next request, before creating any run.
            extra.write_text("invalid\n")
            with self.assertRaises(ValidationError):
                _preflight(source, root / "run", scripts)
            self.assertFalse((root / "run").exists())

    def test_all_caller_and_imported_table_branches_are_typed_and_idempotent(self):
        for marker in ("SNP", "DNP"):
            for called in (False, True):
                with self.subTest(marker=marker, called=called):
                    source = plan_for(marker, called=called)
                    original = copy.deepcopy(source)
                    report = validate_plan(source)
                    self.assertEqual(source, original)
                    self.assertEqual(validate_plan(report["plan"]), report)
                    for step in report["plan"]["steps"]:
                        if step["workflow"] in {"contamination", "cpi", "cpin"}:
                            self.assertEqual(step["parameters"]["marker_type"], marker)
                    post = next(step for step in report["plan"]["steps"] if step["workflow"] == "cpin")
                    self.assertEqual(post["parameters"]["scientific_settings"]["min_child_reads"], 5)

    def test_each_incompatible_marker_role_producer_and_setting_fails(self):
        cases = []
        plan = plan_for(called=False)
        plan["samples"][2]["kind"] = "dnp-table"
        cases.append((plan, "plan.marker_type"))
        plan = plan_for()
        plan["steps"][-1]["inputs"]["trios"][0]["child"] = copy.deepcopy(plan["steps"][-1]["inputs"]["trios"][0]["mother"])
        cases.append((plan, "plan.roles"))
        plan = plan_for()
        plan["steps"][-1]["inputs"]["trios"][0]["child"]["output"] = "dnp-tables"
        cases.append((plan, "plan.output_kind"))
        plan = plan_for()
        plan["steps"][-1]["parameters"]["scientific_settings"] = {"min_child_reads": -1}
        cases.append((plan, "plan.parameter"))
        plan = plan_for()
        plan["steps"][-1]["parameters"]["scientific_settings"] = {"unknown_constant": 1}
        cases.append((plan, "plan.parameter"))
        for source, code in cases:
            with self.subTest(code=code), self.assertRaises(PlanValidationError) as error:
                validate_plan(source)
            self.assertEqual(error.exception.code, code)

    def test_cpin_aliases_and_readable_labels_preserve_all_three_roles(self):
        plan = validate_plan(plan_for())["plan"]
        step = next(step for step in plan["steps"] if step["workflow"] == "cpin")
        samples, trios = _cpin_bindings(step)
        request = {"workflow": "cpin", "samples": samples, "trios": trios[0]["native_selection"]}
        presentation = step_presentation(plan, step, request, trios)
        request["presentation"] = presentation
        self.assertEqual(validate_request_presentation(request), presentation)
        self.assertEqual(set(presentation["samples"].values()), {"mother.bam", "father.bam", "child.bam"})
        self.assertEqual(list(presentation["pairs"].values()), ["Famiglia A"])
        self.assertTrue(trios[0]["native_trio"].endswith("_SNPs"))

    def test_panel_roundtrip_keeps_snp_and_dnp_alleles_and_rejects_mixed_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for marker, text in (("SNP", "chr\tpos\tREF\tALT\nchr1\t10\tA\tG\n"),
                                 ("SNP", "pos\tref\talt\nchr1:10\ta\tg\n"),
                                 ("DNP", "chr1\t10\t11\tAA\tGG\n")):
                source, result = root / "input.tsv", root / "normalized.tsv"
                source.write_text(text)
                records = read_position_panel(source, marker)
                write_position_panel(records, result, marker)
                self.assertEqual(read_position_panel(result, marker), records)
                self.assertTrue(records[0].reference)
            source.write_text("chr\tpos\tREF\tALT\tN_REF\tN_ALT\tN_Other\ttotal_count\nchr1\t10\tA\tG\t1\t1\t0\t2\n")
            self.assertEqual(require_count_input(source, "SNP"), [])
            with self.assertRaises(ValidationError):
                require_count_input(source, "DNP")
