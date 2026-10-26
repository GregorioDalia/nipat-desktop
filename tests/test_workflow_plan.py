from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from nipat_scientific.plan import PlanValidationError, validate_plan


def table(sample: str, step: str = "dnp") -> dict:
    return {"step": step, "output": "dnp-tables", "sample": sample}


def example_plan() -> dict:
    return {
        "schema_version": 1,
        "samples": [
            {"id": "mother_a", "kind": "bam", "path": "/inputs/mother_a.bam"},
            {"id": "father_a", "kind": "bam", "path": "/inputs/father_a.bam"},
        ],
        # A consumer is deliberately declared before its producer.
        "steps": [
            {"id": "cpi", "workflow": "cpi", "inputs": {
                "pairs": [{"id": "pair_a", "mother": table("mother_a"),
                           "father": table("father_a")}],
                "popfreq": "/inputs/popfreq.tsv", "cutoffs": [],
            }, "parameters": {"err_const": 0.0000892303778101497, "cutoff_mode": "all"}},
            {"id": "dnp", "workflow": "dnp-call", "inputs": {
                "samples": ["mother_a", "father_a"], "reference": "/inputs/reference.fa",
                "panel": "/inputs/dnp.tsv",
            }, "parameters": {"parallel": False}},
            {"id": "contamination", "workflow": "contamination", "inputs": {
                "samples": [table("mother_a"), table("father_a")], "panel": "/inputs/dnp.tsv",
            }, "parameters": {}},
            {"id": "snp", "workflow": "snp-call", "inputs": {
                "sample": "mother_a", "reference": "/inputs/reference.fa",
                "panel": "/inputs/snp.tsv",
            }, "parameters": {"mode": "bam"}},
        ],
    }


class WorkflowPlanTests(unittest.TestCase):
    def assert_invalid(self, plan: object, code: str):
        with self.assertRaises(PlanValidationError) as error:
            validate_plan(plan)
        self.assertEqual(error.exception.code, code)
        self.assertTrue(str(error.exception).startswith(code + ":"))

    def test_dnp_branches_and_independent_snp_have_deterministic_order(self):
        plan = example_plan()
        before = copy.deepcopy(plan)
        result = validate_plan(plan)
        self.assertEqual(plan, before)
        self.assertEqual(result["execution_order"], ["dnp", "contamination", "cpi", "snp"])
        self.assertEqual([step["id"] for step in result["plan"]["steps"]],
                         result["execution_order"])
        self.assertEqual(result["plan"]["steps"][2]["inputs"]["pairs"][0],
                         plan["steps"][0]["inputs"]["pairs"][0])
        plan["steps"].reverse()
        plan["samples"].reverse()
        self.assertEqual(validate_plan(plan), result)
        self.assertEqual(validate_plan(result["plan"]), result)

    def test_documented_json_example_is_a_valid_branching_plan(self):
        document = (Path(__file__).resolve().parents[1] / "docs" / "WORKFLOW_CONTRACT.md")
        blocks = re.findall(r"```json\n(.*?)\n```", document.read_text(encoding="utf-8"), re.S)
        self.assertEqual(len(blocks), 1)
        result = validate_plan(json.loads(blocks[0]))
        self.assertEqual(result["execution_order"], ["dnp", "contamination", "cpi"])

    def test_result_cannot_mutate_input_and_is_serializable(self):
        plan = example_plan()
        result = validate_plan(plan)
        result["plan"]["steps"][0]["inputs"]["samples"].append("new")
        self.assertNotIn("new", plan["steps"][1]["inputs"]["samples"])
        json.dumps(result, allow_nan=False)

    def test_validation_never_reads_files_or_creates_directories(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("unexpected file read")), \
                patch.object(Path, "exists", side_effect=AssertionError("unexpected file check")), \
                patch.object(Path, "mkdir", side_effect=AssertionError("unexpected write")):
            result = validate_plan(example_plan())
        self.assertEqual(len(result["execution_order"]), 4)

    def test_prepared_tables_allow_contamination_and_cpi_without_dnp(self):
        plan = example_plan()
        for sample in plan["samples"]:
            sample["kind"] = "dnp-table"
            sample["path"] = sample["path"].replace(".bam", ".tsv")
        plan["steps"] = [plan["steps"][0], plan["steps"][2]]
        pair = plan["steps"][0]["inputs"]["pairs"][0]
        pair["mother"] = {"sample": "mother_a"}
        pair["father"] = {"sample": "father_a"}
        plan["steps"][1]["inputs"]["samples"] = [
            {"sample": "mother_a"}, {"sample": "father_a"},
        ]
        self.assertEqual(validate_plan(plan)["execution_order"], ["contamination", "cpi"])

    def test_snp_pileup_requires_an_explicit_matching_mode(self):
        plan = {"schema_version": 1, "samples": [
            {"id": "pileup_a", "kind": "snp-pileup", "path": "/inputs/pileup.txt"},
        ], "steps": [{"id": "snp", "workflow": "snp-call", "inputs": {
            "sample": "pileup_a", "reference": None, "panel": "/inputs/snp.tsv",
        }, "parameters": {"mode": "pileup"}}]}
        self.assertEqual(validate_plan(plan)["plan"], plan)
        plan["steps"][0]["inputs"]["reference"] = "/inputs/reference.fa"
        self.assert_invalid(plan, "plan.parameter")
        plan["steps"][0]["inputs"]["reference"] = None
        plan["steps"][0]["parameters"]["mode"] = "bam"
        self.assert_invalid(plan, "plan.sample_kind")

    def test_schema_and_unknown_fields_are_rejected_at_each_level(self):
        for version in (True, 0, 2, "1", 1.0):
            with self.subTest(version=version):
                plan = example_plan()
                plan["schema_version"] = version
                self.assert_invalid(plan, "plan.schema")
        for location in ("root", "sample", "step", "inputs", "parameters", "pair", "reference"):
            with self.subTest(location=location):
                plan = example_plan()
                targets = {
                    "root": plan, "sample": plan["samples"][0], "step": plan["steps"][0],
                    "inputs": plan["steps"][0]["inputs"],
                    "parameters": plan["steps"][0]["parameters"],
                    "pair": plan["steps"][0]["inputs"]["pairs"][0],
                    "reference": plan["steps"][0]["inputs"]["pairs"][0]["mother"],
                }
                targets[location]["command"] = "echo arbitrary shell"
                self.assert_invalid(plan, "plan.fields")
        plan = example_plan()
        plan["execution_order"] = ["cpi", "dnp"]
        self.assert_invalid(plan, "plan.fields")
        self.assert_invalid(validate_plan(example_plan()), "plan.fields")

    def test_duplicate_identifiers_and_input_paths_are_rejected(self):
        for change in ("sample_id", "case_sample_id", "sample_path", "step", "step_case", "dnp_sample"):
            with self.subTest(change=change):
                plan = example_plan()
                if change == "sample_id":
                    plan["samples"].append(copy.deepcopy(plan["samples"][0]))
                elif change == "case_sample_id":
                    plan["samples"][1]["id"] = "MOTHER_A"
                elif change == "sample_path":
                    plan["samples"][1]["path"] = plan["samples"][0]["path"]
                elif change == "step":
                    plan["steps"].append(copy.deepcopy(plan["steps"][1]))
                elif change == "step_case":
                    plan["steps"][0]["id"] = "DNP"
                else:
                    plan["steps"][1]["inputs"]["samples"].append("mother_a")
                self.assert_invalid(plan, "plan.duplicate")

    def test_invalid_paths_and_ids_fail_without_normalizing_away_ambiguity(self):
        for path in ("relative.bam", "C:\\data\\a.bam", "/data/../a.bam", "/data/./a.bam",
                     "//server/share/a.bam", "/data//a.bam", "/data/a.bam/", "/data/\na.bam", "/"):
            with self.subTest(path=path):
                plan = example_plan()
                plan["samples"][0]["path"] = path
                self.assert_invalid(plan, "plan.path")
        for identifier in ("1first", "with space", "../escape", "x" * 65, "à"):
            with self.subTest(identifier=identifier):
                plan = example_plan()
                plan["steps"][0]["id"] = identifier
                self.assert_invalid(plan, "plan.identifier")

    def test_missing_or_mismatched_samples_and_outputs_fail(self):
        plan = example_plan()
        plan["steps"][1]["inputs"]["samples"] = ["unknown"]
        self.assert_invalid(plan, "plan.sample_missing")
        for reference, code in (
            ({"step": "missing", "output": "dnp-tables", "sample": "mother_a"}, "plan.step_missing"),
            ({"step": "snp", "output": "dnp-tables", "sample": "mother_a"}, "plan.output_kind"),
            ({"step": "dnp", "output": "summary", "sample": "mother_a"}, "plan.output_kind"),
            ({"step": "dnp", "output": "dnp-tables", "sample": "missing"}, "plan.output_sample"),
            ({"sample": "mother_a"}, "plan.sample_kind"),
        ):
            with self.subTest(reference=reference):
                plan = example_plan()
                plan["steps"][2]["inputs"]["samples"] = [reference]
                self.assert_invalid(plan, code)

    def test_dependency_cycles_and_self_references_are_rejected(self):
        plan = example_plan()
        plan["steps"][2]["inputs"]["samples"] = [table("mother_a", "contamination")]
        self.assert_invalid(plan, "plan.cycle")
        plan["steps"][2]["inputs"]["samples"] = [table("mother_a", "cpi")]
        plan["steps"][0]["inputs"]["pairs"][0]["mother"] = table("mother_a", "contamination")
        self.assert_invalid(plan, "plan.cycle")

    def test_cpi_roles_are_explicit_consistent_and_pairs_unique(self):
        for change, code in (("same_roles", "plan.roles"), ("cross_roles", "plan.roles"),
                             ("pair_id", "plan.duplicate"), ("pair_content", "plan.duplicate")):
            with self.subTest(change=change):
                plan = example_plan()
                pairs = plan["steps"][0]["inputs"]["pairs"]
                if change == "same_roles":
                    pairs[0]["father"] = table("mother_a")
                elif change == "cross_roles":
                    pairs.append({"id": "pair_b", "mother": table("father_a"),
                                  "father": table("mother_a")})
                else:
                    pairs.append(copy.deepcopy(pairs[0]))
                    if change == "pair_content":
                        pairs[1]["id"] = "pair_b"
                self.assert_invalid(plan, code)
        # Distinct output producers do not change the biological sample identity.
        plan = example_plan()
        other = copy.deepcopy(plan["steps"][1])
        other["id"] = "dnp_other"
        plan["steps"].append(other)
        plan["steps"][0]["inputs"]["pairs"][0]["father"] = table("mother_a", "dnp_other")
        self.assert_invalid(plan, "plan.roles")

    def test_cpi_parameter_and_cutoff_modes_preserve_native_contract(self):
        for value in (-1, float("nan"), float("inf"), True, "0.01", 10 ** 1000):
            with self.subTest(error=str(value)[:20]):
                plan = example_plan()
                plan["steps"][0]["parameters"]["err_const"] = value
                self.assert_invalid(plan, "plan.parameter")
        for mode, cutoffs in (
            ("all", []), ("panel", [{"label": "", "path": "/inputs/panel.tsv"}]),
            ("named", [{"label": "Panel A", "path": "/inputs/panel_a.tsv"},
                       {"label": "Panel B", "path": "/inputs/panel_b.tsv"}]),
        ):
            with self.subTest(mode=mode):
                plan = example_plan()
                plan["steps"][0]["parameters"].update(err_const=0, cutoff_mode=mode)
                plan["steps"][0]["inputs"]["cutoffs"] = cutoffs
                result = validate_plan(plan)["plan"]["steps"][2]
                self.assertEqual(result["inputs"]["cutoffs"], cutoffs)
                self.assertEqual(result["parameters"]["err_const"], 0)
        for mode, cutoffs, code in (
            ("unknown", [], "plan.cutoff_mode"), ("panel", [], "plan.cutoff_mode"),
            ("named", [], "plan.cutoff_mode"),
            ("all", [{"label": "", "path": "/inputs/p.tsv"}], "plan.cutoff_mode"),
            ("panel", [{"label": "named", "path": "/inputs/p.tsv"}], "plan.cutoff_label"),
            ("named", [{"label": "bad=name", "path": "/inputs/p.tsv"}], "plan.cutoff_label"),
        ):
            with self.subTest(mode=mode, cutoffs=cutoffs):
                plan = example_plan()
                plan["steps"][0]["parameters"]["cutoff_mode"] = mode
                plan["steps"][0]["inputs"]["cutoffs"] = cutoffs
                self.assert_invalid(plan, code)

    def test_parameters_are_required_instead_of_silently_defaulted(self):
        plan = example_plan()
        del plan["steps"][1]["parameters"]["parallel"]
        self.assert_invalid(plan, "plan.fields")
        plan = example_plan()
        plan["steps"][1]["parameters"]["parallel"] = 1
        self.assert_invalid(plan, "plan.parameter")
        plan = example_plan()
        plan["steps"][0]["workflow"] = "run-shell"
        self.assert_invalid(plan, "plan.workflow")


if __name__ == "__main__":
    unittest.main()
