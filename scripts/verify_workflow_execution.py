"""Real-image checks for the sequential DNPcall → Contamination plan executor.

Called by the scientific CI package verification. Only synthetic input files and
one output directory are mounted; the image supplies every scientific source.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from verify_dnp_engine import check_dnp_outputs, compare_dnp_tables, expected_rows, keyed_rows, table


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state(run: Path) -> dict:
    state = json.loads((run / "workflow-state.json").read_text(encoding="utf-8"))
    if (state.get("schema_version") != 1
            or state.get("interface") != "workflow-plan-execution-v1"):
        raise ValueError("Unexpected workflow execution report interface.")
    return state


def _artifact(run: Path, artifact: dict) -> Path:
    relative = Path(artifact["path"])
    path = (run / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(run.resolve()) or not path.is_file():
        raise ValueError("Workflow artifact is missing or outside its run directory.")
    if artifact["sha256"] != _digest(path):
        raise ValueError("Workflow artifact hash does not identify the produced file.")
    return path


def check_workflow_execution(identifier: str, root: Path, inputs: Path, *, run_image,
                             write_request) -> None:
    """Verify actual chaining, biological table identity, failure, and no reuse."""
    plan = {
        "schema_version": 1,
        "samples": [
            {"id": "research_a", "kind": "bam", "path": "/inputs/bams/sample_0001.bam"},
            {"id": "research_b", "kind": "bam", "path": "/inputs/bams/sample_0002.bam"},
        ],
        # Consumer first and reverse sample order deliberately exercise graph
        # ordering and identity references rather than positional assumptions.
        "steps": [
            {"id": "contamination", "workflow": "contamination", "inputs": {
                "samples": [
                    {"step": "dnp", "output": "dnp-tables", "sample": "research_b"},
                    {"step": "dnp", "output": "dnp-tables", "sample": "research_a"},
                ], "panel": "/inputs/DNP_list.txt",
            }, "parameters": {}},
            {"id": "dnp", "workflow": "dnp-call", "inputs": {
                "samples": ["research_a", "research_b"],
                "reference": "/inputs/reference.fa", "panel": "/inputs/DNP_list.txt",
            }, "parameters": {"parallel": False}},
        ],
    }
    results = root / "composed workflow results"
    (results / "work").mkdir(parents=True)
    plan_file = results / "work/plan.json"
    plan_file.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    original_inputs = {path: path.read_bytes() for path in inputs.rglob("*") if path.is_file()}
    original_plan = plan_file.read_bytes()
    arguments = ["execute-plan", "--plan", "/results/work/plan.json",
                 "--run-dir", "/results/workflow"]
    run_image(identifier, arguments, inputs=inputs, results=results)
    run = results / "workflow"
    state = _state(run)
    if (state.get("status") != "succeeded" or state.get("exit_code") != 0
            or state.get("execution_order") != ["dnp", "contamination"]):
        raise ValueError(f"Unexpected composed workflow status: {state}.")
    if state.get("plan_sha256") != _digest(run / "plan.json"):
        raise ValueError("Workflow report does not identify the exact canonical plan.")
    steps = {step["id"]: step for step in state["steps"]}
    if set(steps) != {"dnp", "contamination"} or any(
        step.get("status") != "succeeded" or step.get("exit_code") != 0
        for step in steps.values()
    ):
        raise ValueError("A composed scientific step did not succeed.")
    for step in steps.values():
        if (not step.get("started_utc") or not step.get("finished_utc")
                or not (run / step["log"]).is_file() or not (run / step["request"]).is_file()):
            raise ValueError("A composed step lacks execution or request evidence.")
    dnp_run = run / "steps/dnp"
    check_dnp_outputs(dnp_run, ("A", "B"))
    compare_dnp_tables(root / "complete DNP results", dnp_run)
    dnp_artifacts = {item["sample"]: item for item in steps["dnp"]["artifacts"]["dnp-tables"]}
    if set(dnp_artifacts) != {"research_a", "research_b"}:
        raise ValueError("DNP output identity mapping lost a plan sample.")
    for sample, alias in (("research_a", "sample_0001"), ("research_b", "sample_0002")):
        path = _artifact(run, dnp_artifacts[sample])
        expected = dnp_run / f"output/individual_outputs/full_output_{alias}.txt"
        if path != expected.resolve():
            raise ValueError("DNP output was assigned to the wrong plan sample.")

    contamination_artifacts = steps["contamination"]["artifacts"]
    summary = table(_artifact(run, contamination_artifacts["summary"]))
    if len(summary) != 2:
        raise ValueError("Expected two Contamination summaries.")
    for row in summary:
        if (int(row["informative_DNPs"]) != 2 or float(row["mean_contamination"]) != 0
                or float(row["sd_contamination"]) != 0):
            raise ValueError(f"Contamination differs from the independent synthetic oracle: {row}.")
    contamination_tables = {
        item["sample"]: _artifact(run, item)
        for item in contamination_artifacts["contamination-tables"]
    }
    if set(contamination_tables) != {"research_a", "research_b"}:
        raise ValueError("Contamination output identity mapping lost a sample.")
    for sample, path in contamination_tables.items():
        rows = keyed_rows(path)
        if set(rows) != {("chrDnpSynthetic", "50", "51"), ("chrDnpSynthetic", "230", "231")}:
            raise ValueError("Unexpected informative loci in chained Contamination.")
        expected = expected_rows("A" if sample == "research_a" else "B")
        for key, row in rows.items():
            if any(row[field] != expected[key][field] for field in ("N_REF", "N_ALT", "N_Other")):
                raise ValueError("Chained Contamination received another sample's DNP table.")
        if any(float(row["contamination"]) != 0 for row in rows.values()):
            raise ValueError("Expected zero unexpected REF/ALT counts at retained synthetic loci.")

    # Execute Contamination separately from the same DNP output tables. Use its
    # native staging names from the recorded request, preserving sample labels.
    step_request = json.loads((run / "steps/contamination/request.json").read_text(encoding="utf-8"))
    separate = root / "separate workflow contamination"
    sources = []
    for item in step_request["samples"]:
        container_path = Path(item["path"])
        relative = container_path.relative_to("/results/workflow")
        sources.append({"path": "/inputs/" + relative.as_posix(), "name": item["name"]})
    write_request(separate, {
        "schema_version": 1, "workflow": "contamination", "samples": sources,
        # The canonical DNP panel is already inside the workflow output mount.
        "panel": "/inputs/steps/dnp/work/DNP_list.txt",
        "work_dir": "/results/work", "out_dir": "/results/output",
    })
    run_image(identifier, ["execute", "contamination", "--request", "/results/work/request.json"],
              inputs=run, results=separate)
    actual_output = run / "steps/contamination/output"
    first = {path.name: table(path) for path in actual_output.glob("*.txt")}
    second = {path.name: table(path) for path in (separate / "output").glob("*.txt")}
    if first != second:
        raise ValueError("Composed Contamination tables differ from the standalone workflow.")

    immutable = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    run_image(identifier, arguments, inputs=inputs, results=results, expected_returncode=2)
    if immutable != {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}:
        raise ValueError("Reusing a workflow run changed its existing results or evidence.")
    if plan_file.read_bytes() != original_plan or any(
        path.read_bytes() != content for path, content in original_inputs.items()
    ):
        raise ValueError("Workflow execution changed an original input or plan.")
    # A corrupt BAM is a runtime failure rather than an unavailable input.
    # DNP's real R/samtools process must fail and its consumer must never run.
    broken_inputs = root / "corrupt workflow inputs"
    shutil.copytree(inputs, broken_inputs)
    (broken_inputs / "bams/sample_0001.bam").write_bytes(b"not a BAM file\n")
    rejected = root / "failed composed workflow"
    (rejected / "work").mkdir(parents=True)
    (rejected / "work/plan.json").write_bytes(original_plan)
    run_image(identifier, arguments, inputs=broken_inputs, results=rejected, expected_returncode=1)
    failed_run = rejected / "workflow"
    failed = _state(failed_run)
    failed_steps = {step["id"]: step for step in failed["steps"]}
    if (failed.get("status") != "failed" or failed.get("exit_code") != 1
            or failed_steps["dnp"].get("status") != "failed"
            or failed_steps["contamination"].get("status") != "blocked"):
        raise ValueError("DNP runtime failure did not block the dependent Contamination step.")
    if (failed_run / "steps/contamination").exists():
        raise ValueError("A blocked downstream analysis created scientific work or results.")
    print("PASS: bundled DNPcall -> Contamination, numeric oracle, separate-call parity, "
          "sample identity, artifact hashes, immutable run reuse rejection, and real R failure isolation.", flush=True)
