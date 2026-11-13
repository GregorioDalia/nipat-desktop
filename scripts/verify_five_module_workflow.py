"""Run all five modules from three synthetic BAMs in serial and capped modes.

Local qualification requires Rscript, samtools and bundled R libraries. With
--image, the image supplies samtools and all scientific code, while the real
public client runs from a project directory containing only compose.yaml.
The BAMs contain two synthetic contigs from the existing caller fixtures. They
exercise role routing and output contracts, not a simulated real biological trio.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from nipat_scientific.executor import execute_plan


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_inputs(inputs: Path, samtools):
    """One committed synthetic recipe, compiled locally or inside the exact image."""
    inputs.mkdir(parents=True, exist_ok=False)
    dnp, snp = (PROJECT / "tests/fixtures" / name for name in ("dnp_engine", "snp_engine"))
    original = {str(path): digest(path) for directory in (dnp, snp) for path in directory.iterdir() if path.is_file()}
    reference = inputs / "reference.fa"
    reference.write_bytes((dnp / "reference.fa").read_bytes() + (snp / "reference.fa").read_bytes())
    samtools(["faidx", str(reference)])
    snp_lines = (snp / "reads.sam").read_text().splitlines()
    for index, source in enumerate(("reads_A.sam", "reads_B.sam", "reads_A.sam"), 1):
        lines = (dnp / source).read_text().splitlines()
        header = [line for line in lines if line.startswith("@")] + [line for line in snp_lines if line.startswith("@SQ")]
        reads = [f"sample{index}_" + line for line in lines + snp_lines if not line.startswith("@")]
        sam = inputs / f"sample_{index:04d}.sam"
        sam.write_text("\n".join(header + reads) + "\n")
        bam = inputs / f"sample_{index:04d}.bam"
        samtools(["sort", "-o", str(bam), str(sam)])
        samtools(["index", str(bam)])
    (inputs / "dnp-panel.tsv").write_bytes((dnp / "DNP_list.txt").read_bytes())
    (inputs / "snp-panel.tsv").write_bytes((snp / "SNPlist.tsv").read_bytes())
    (inputs / "snp-positions.tsv").write_text("chr\tpos\nchrSynthetic\t50\nchrSynthetic\t120\n")
    (inputs / "dnp-frequency.tsv").write_text("chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\n" +
        "".join(f"chrDnpSynthetic\t{position}\t{position+1}\t0.6\t0.4\n" for position in (50, 140, 230)))
    (inputs / "snp-frequency.tsv").write_text("chr\tpos\tRef_f.pop\tAlt_f.pop\n" +
        "".join(f"chrSynthetic\t{position}\t0.6\t0.4\n" for position in (50, 120)))
    input_hashes = {str(path): digest(path) for path in inputs.iterdir() if path.is_file()}
    return original, input_hashes


def scientific_tables(run: Path) -> dict[str, str]:
    return {str(path.relative_to(run)): digest(path) for path in run.glob("steps/*/output/**/*")
            if path.is_file() and path.suffix in {".txt", ".tsv", ".csv"}
            and "presentation" not in path.relative_to(run).parts and path.name != "resources.tsv"}


def check_unchanged(hashes: dict[str, str]) -> None:
    for path, expected in hashes.items():
        if digest(Path(path)) != expected:
            raise AssertionError(f"Input or execution source changed: {path}")


def check_bundled_client(parent: Path, layout, identifier: str) -> dict:
    """Require the verified image and only read-only inputs plus one writable run."""
    record = json.loads((parent / "run.json").read_text())
    service = json.loads((parent / "work/engine-compose.json").read_text())["services"]["scientific"]
    if (record.get("status") != "succeeded" or record.get("workflow") != "analysis"
            or record.get("source", {}).get("role") != "client"
            or record.get("runtime", {}).get("image_id") != identifier
            or service.get("image") != identifier or service.get("read_only") is not True
            or service.get("network_mode") != "none"):
        raise AssertionError("The composed workflow did not use the exact isolated bundled image")
    run_target = str(layout.container_path(parent))
    inputs = {item["container_path"] for item in record["input_mounts"]}
    volumes = service["volumes"]
    scratch = [item for item in volumes if item.get("target") == "/scratch"]
    binds = [item for item in volumes if item.get("target") != "/scratch"]
    if (scratch != [{"type": "volume", "target": "/scratch", "read_only": False}]
            or len(binds) != len(inputs) + 1
            or {item["target"] for item in binds} != inputs | {run_target}
            or any(item.get("type") != "bind"
                   or item.get("bind", {}).get("create_host_path") is not False
                   or item.get("read_only") != (item["target"] != run_target) for item in binds)):
        raise AssertionError("Unexpected mounts in the bundled five-module workflow")
    return record


def check_step_outputs(run: Path, plan: dict) -> None:
    from nipat.validation.self_test import compare_snp_outputs
    from verify_dnp_engine import check_dnp_outputs

    check_dnp_outputs(run / "steps/dnp", ("A", "B", "A"))
    for step in plan["steps"]:
        step_run = run / "steps" / step["id"]
        if step["workflow"] == "snp-call":
            compare_snp_outputs(PROJECT / "tests/fixtures/snp_engine/expected.tsv",
                                step_run / "output/SNPcall_output.txt")
        settings = json.loads((step_run / "work/effective-scientific-settings.json").read_text())
        native = json.loads((step_run / "output/scientific-settings.json").read_text())
        if settings.get("workflow") != step["workflow"] or settings != native:
            raise AssertionError(f"Scientific settings provenance mismatch: {step['id']}")


def qualify(destination: Path):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    inputs = destination / "inputs"
    original, input_hashes = prepare_inputs(
        inputs, lambda args: subprocess.run(["samtools", *args], check=True))
    reference = inputs / "reference.fa"
    ids = ("mother", "father", "child")
    plan = {"schema_version": 1, "samples": [
        {"id": name, "kind": "bam", "path": str(inputs / f"sample_{number:04d}.bam")}
        for number, name in enumerate(ids, 1)], "steps": [],
        "presentation": {"samples": {name: name + "_synthetic.bam" for name in ids}, "pairs": {}}}
    plan["steps"].append({"id": "dnp", "workflow": "dnp-call", "inputs": {
        "samples": list(ids), "panel": str(inputs / "dnp-panel.tsv"), "reference": str(reference)},
        "parameters": {"parallel": True}})
    for name in ids:
        plan["steps"].append({"id": "snp_" + name, "workflow": "snp-call", "inputs": {
            "sample": name, "panel": str(inputs / "snp-panel.tsv"), "reference": str(reference)}, "parameters": {"mode": "bam"}})
    for marker in ("dnp", "snp"):
        def ref(name):
            return {"step": "dnp" if marker == "dnp" else "snp_" + name, "output": marker + "-tables", "sample": name}
        plan["steps"].extend([
            {"id": marker + "_contamination", "workflow": "contamination", "inputs": {
                "samples": [ref(name) for name in ids], "panel": str(inputs / ("dnp-panel.tsv" if marker == "dnp" else "snp-panel.tsv"))}, "parameters": {}},
            {"id": marker + "_cpi", "workflow": "cpi", "inputs": {
                "pairs": [{"id": marker + "_prenatal", "mother": ref("mother"), "father": ref("father")}],
                "popfreq": str(inputs / (marker + "-frequency.tsv")), "cutoffs": []}, "parameters": {"cutoff_mode": "all"}},
            {"id": marker + "_cpin", "workflow": "cpin", "inputs": {
                "trios": [{"id": marker + "_postnatal", "mother": ref("mother"), "father": ref("father"), "child": ref("child")}],
                "popfreq": str(inputs / (marker + "-frequency.tsv")), "markers": str(inputs / (marker + "-panel.tsv"))}, "parameters": {}},
        ])
    helper = PROJECT / "src/nipat_scientific"
    os.environ.update({"NIPAT_PARALLEL_HELPER": str(helper / "parallel.R"), "NIPAT_PLOTS_HELPER": str(helper / "plots.R"),
                       "NIPAT_DNP_BLOCKS_HELPER": str(helper / "dnp_blocks.R"), "NIPAT_DNP_PILEUP_HELPER": str(helper / "dnp_pileup.py")})
    scripts = {"dnp-call": PROJECT / "scientific/vendor/DNPcall/DNPcall.R", "snp-call": PROJECT / "scientific/vendor/NEWPAT/SNPcall/SNPcall.R",
               "contamination": PROJECT / "scientific/vendor/NEWPAT/contamination/detect_contamination.R",
               "cpi": PROJECT / "scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R",
               "cpin": PROJECT / "scientific/vendor/NEWPAT/CPI_postnatal/Postnatal_CPI.R"}
    source_hashes = {str(path): digest(path) for path in [Path(__file__).resolve(), PROJECT / "engine/main.py", *scripts.values(), *helper.glob("*.py"), *helper.glob("*.R"), helper / "settings_data.json"]}
    results, tables = {}, {}
    for mode in ("serial", "capped"):
        os.environ.update({"NIPAT_EXECUTION_MODE": "serial" if mode == "serial" else "auto", "NIPAT_MAX_WORKERS": "2"})
        run = destination / mode
        result = execute_plan(plan, run_dir=run, script_paths=scripts)
        if result["status"] != "succeeded":
            raise AssertionError(f"{mode}: {result['error']}; inspect {run / 'workflow-state.json'}")
        check_step_outputs(run, plan)
        results[mode] = {"status": result["status"], "steps": len(result["steps"]), "snp_parallel": result.get("snp_parallel")}
        tables[mode] = scientific_tables(run)
    if tables["serial"] != tables["capped"]:
        raise AssertionError("Serial/capped scientific tables differ")
    if results["capped"]["snp_parallel"]["workers"] != 2:
        raise AssertionError("Capped run did not exercise two SNP workers")
    check_unchanged({**original, **input_hashes, **source_hashes})
    report = {"status": "passed", "bam_count": 3, "scope": "all five modules, both marker branches, presentation and original inputs",
              "runs": results, "identical_scientific_tables": len(tables["serial"]),
              "input_sha256": input_hashes, "fixture_sha256": original,
              "script_sha256": {name: source_hashes[str(path)] for name, path in scripts.items()}, "engine_sha256": source_hashes}
    (destination / "qualification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def qualify_image(identifier: str, destination: Path, *, run_container) -> dict:
    """Exercise installed-client routing without mounting checkout/scientific code.

    The three BAMs deliberately test routing rather than biological trio validity.
    Caller counts are checked against independent committed fixture oracles;
    downstream output contracts/settings are checked by the bundled engine and
    all scientific tables must agree between serial and bounded parallel runs.
    """
    from nipat.execution.options import ExecutionOptions
    from nipat.execution.runner import DockerComposeRunner
    from nipat.execution.workflows import Workflows
    from nipat.paths import ProjectLayout

    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    generated = destination / "generated"
    inputs = generated / "work"

    def samtools(arguments):
        mapped = ["/results/work/" + Path(value).relative_to(inputs).as_posix()
                  if Path(value).is_absolute() and Path(value).is_relative_to(inputs)
                  else value for value in arguments]
        run_container(identifier, ["samtools", *mapped], results=generated)

    originals, input_hashes = prepare_inputs(inputs, samtools)
    project = destination / "source-free client"
    project.mkdir()
    (project / "compose.yaml").write_text(
        f"services:\n  scientific:\n    image: {identifier}\n", encoding="utf-8")
    layout = ProjectLayout(project, destination, destination / "client data",
                           destination / "client results", project / "compose.yaml")
    results, tables = {}, {}
    expected_workflows = {"dnp-call", "snp-call", "contamination", "cpi", "cpin"}
    with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
        for mode in ("serial", "capped"):
            runner = DockerComposeRunner(layout, options=ExecutionOptions(
                execution_mode="serial" if mode == "serial" else "auto", max_workers=2))
            parent = Workflows(layout, runner).analyze(
                caller="both", analyses=["contamination", "cpi", "cpin"], run_name=mode,
                samples=[(name, inputs / f"sample_{number:04d}.bam")
                         for number, name in enumerate(("mother", "father", "child"), 1)],
                reference=inputs / "reference.fa",
                dnp_panel=inputs / "dnp-panel.tsv", snp_panel=inputs / "snp-panel.tsv",
                dnp_popfreq=inputs / "dnp-frequency.tsv", snp_popfreq=inputs / "snp-frequency.tsv",
                dnp_contamination_panel=inputs / "dnp-panel.tsv", snp_contamination_panel=inputs / "snp-panel.tsv",
                dnp_cpin_panel=inputs / "dnp-panel.tsv", snp_cpin_panel=inputs / "snp-panel.tsv",
                pairs=[("prenatal", "mother", "father")],
                trios=[("postnatal", "mother", "father", "child")])
            record = check_bundled_client(parent, layout, identifier)
            run = parent / "output/workflow"
            state = json.loads((run / "workflow-state.json").read_text())
            plan = json.loads((run / "plan.json").read_text())
            commands = record.get("commands", [])
            if (record.get("status") != "succeeded" or state.get("status") != "succeeded"
                    or len(commands) != 1 or "execute-plan" not in commands[0]["argv"]
                    or len(state["steps"]) != 10
                    or {step["workflow"] for step in plan["steps"]} != expected_workflows):
                raise AssertionError("The source-free client did not complete its ten-step five-module plan")
            check_step_outputs(run, plan)
            results[mode] = {"status": state["status"], "steps": len(state["steps"]),
                             "snp_parallel": state.get("snp_parallel")}
            tables[mode] = scientific_tables(run)
    if not tables["serial"] or tables["serial"] != tables["capped"]:
        raise AssertionError("Bundled serial/capped scientific tables differ or are missing")
    parallel = results["capped"]["snp_parallel"] or {}
    if parallel.get("workers") != 2 or parallel.get("tasks") != 3:
        raise AssertionError("Bundled capped workflow did not exercise three SNP tasks with two workers")
    check_unchanged({**originals, **input_hashes})
    if {path.name for path in project.iterdir()} != {"compose.yaml"}:
        raise AssertionError("The source-free client unexpectedly populated its application directory")
    report = {"status": "passed", "image": identifier, "bam_count": 3, "runs": results,
              "scope": "bundled five-module public-client workflow, both marker branches",
              "identical_scientific_tables": len(tables["serial"]), "input_sha256": input_hashes,
              "fixture_sha256": originals}
    (destination / "qualification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--image", help="Already-built local image; use its code and tools exclusively")
    args = parser.parse_args()
    if args.image:
        from verify_engine_package import image_id, run_container
        report = qualify_image(image_id(args.image), args.output, run_container=run_container)
    else:
        report = qualify(args.output)
    print(json.dumps(report, indent=2))
