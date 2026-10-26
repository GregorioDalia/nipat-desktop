"""Check bundled R scripts without mounting the application or source checkout.

This verifies native R invocation and all four complete scientific workflows.
Only fixture input and result directories are mounted into the image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

from nipat.adapters.panels import read_position_panel, write_position_panel
from nipat.errors import NipatError
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.validation.self_test import compare_snp_outputs
from nipat.validation.files import require_snp_pileup
from nipat_scientific.catalog import load_catalog
from verify_contamination_update import check_bundled_run
from verify_contamination_update import check_outputs as check_contamination
from verify_cpi_update import check_outputs as check_cpi
from verify_dnp_engine import check_dnp_client_without_host_scripts, check_dnp_workflow
from verify_cpi_engine import check_cpi_client_without_host_scripts, check_cpi_workflow
from verify_workflow_execution import check_workflow_execution, check_cpi_chains, check_imported_cpi_plans
from verify_snp_workflow import check_snp_plans


PROJECT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ["python3", "/opt/nipat/engine/main.py"]


def docker(arguments: list[str], *, expected_returncode: int = 0) -> str:
    result = subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, check=False,
    )
    if result.returncode != expected_returncode:
        raise RuntimeError(
            f"Docker returned {result.returncode}, expected {expected_returncode}: {arguments}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result.stdout if expected_returncode == 0 else result.stdout + result.stderr


def image_id(reference: str) -> str:
    if not reference or reference.startswith("-"):
        raise ValueError("A local image reference is required.")
    images = json.loads(docker(["image", "inspect", reference]))
    if len(images) != 1 or images[0].get("Os") != "linux":
        raise ValueError("Expected one Linux image.")
    identifier = images[0].get("Id", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", identifier):
        raise ValueError("Docker did not return an immutable image ID.")
    return identifier


def run_container(identifier: str, arguments: list[str], *, inputs: Path | None = None,
                  results: Path | None = None, expected_returncode: int = 0,
                  working_dir: str | None = None) -> str:
    command = [
        "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m", "--env", "HOME=/tmp",
        "--env", "TMPDIR=/tmp", "--env", "LANG=C.UTF-8",
        "--env", "LC_ALL=C.UTF-8",
    ]
    if hasattr(os, "getuid"):
        command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    if inputs is not None:
        command.extend([
            "--mount", f"type=bind,source={inputs},target=/inputs,readonly",
        ])
    if results is not None:
        (results / "work").mkdir(parents=True, exist_ok=True)
        (results / "output").mkdir(exist_ok=True)
        command.extend([
            "--mount", f"type=bind,source={results},target=/results",
            "--workdir", working_dir or "/results/work",
        ])
    else:
        command.extend(["--workdir", working_dir or "/tmp"])
    return docker([*command, identifier, *arguments],
                  expected_returncode=expected_returncode)


def run_image(identifier: str, arguments: list[str], *, inputs: Path | None = None,
              results: Path | None = None, expected_returncode: int = 0) -> str:
    return run_container(identifier, [*ENTRYPOINT, *arguments], inputs=inputs,
                         results=results, expected_returncode=expected_returncode)


def check_metadata(identifier: str) -> dict:
    run_image(identifier, ["verify"])
    description = json.loads(run_image(identifier, ["describe", "--json"]))
    expected_digest = hashlib.sha256((PROJECT / "scientific/SHA256SUMS").read_bytes()).hexdigest()
    if description.get("schema_version") != 1 or description.get("interface") != "native-r-v1":
        raise ValueError("Unexpected bundled engine interface.")
    if description.get("manifest", {}).get("sha256") != expected_digest:
        raise ValueError("Bundled scientific manifest differs from this checkout.")
    if description.get("workflow_interfaces", {}).get("contamination") != "contamination-v1":
        raise ValueError("The engine lacks the complete Contamination interface.")
    if description.get("workflow_interfaces", {}).get("snp-call") != "snp-call-v1":
        raise ValueError("The engine lacks the complete SNPcall interface.")
    if description.get("workflow_interfaces", {}).get("dnp-call") != "dnp-call-v1":
        raise ValueError("The engine lacks the complete DNPcall interface.")
    if description.get("workflow_interfaces", {}).get("cpi") != "cpi-v1":
        raise ValueError("The engine lacks the complete CPI interface.")
    if description.get("plan_execution") != {
        "interface": "workflow-plan-execution-v1", "schema_version": 1,
        "workflows": ["dnp-call", "snp-call", "contamination", "cpi"], "scheduling": "sequential", "resume": False,
    }:
        raise ValueError("Unexpected supported workflow plan execution interface.")
    preparation = description.get("preparation", {})
    if preparation.get("interface") != "workflow-preparation-v1":
        raise ValueError("Unexpected preparation metadata interface.")
    source_files = {"engine/main.py": PROJECT / "engine/main.py"}
    for name in (
        "__init__.py", "errors.py", "panels.py", "files.py", "contamination.py", "snp.py",
        "dnp.py", "cpi.py", "catalog.py", "plan.py", "executor.py", "catalog_data/dnp-call.json",
        "catalog_data/snp-call.json", "catalog_data/contamination.json", "catalog_data/cpi.json",
    ):
        source_files[f"lib/nipat_scientific/{name}"] = PROJECT / "src/nipat_scientific" / name
    expected_sources = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in source_files.items()
    }
    if preparation.get("file_sha256") != expected_sources:
        raise ValueError("Bundled preparation sources differ from this checkout.")
    return description


def check_catalog(identifier: str) -> None:
    """Read the actual bundled catalog, with no source or client mounts."""
    actual = json.loads(run_image(identifier, ["catalog", "--json"]))
    expected = load_catalog(source_root=PROJECT)
    if actual != expected:
        raise ValueError("The image catalog differs from the source-verified catalog in this checkout.")
    for workflow in expected["workflows"]:
        selected = json.loads(run_image(identifier, ["catalog", workflow, "--json"]))
        if selected.get("workflows") != {workflow: expected["workflows"][workflow]}:
            raise ValueError(f"The image returned an incorrect catalog selection: {workflow}.")
    print("PASS: source-verified catalog for four R scripts, without host source mounts.", flush=True)


def check_plan_contract(identifier: str, root: Path) -> None:
    """Check plan validation only: this does not execute composed workflows."""
    inputs = root / "plan-contract-inputs"
    inputs.mkdir()
    plan = {
        "schema_version": 1,
        "samples": [{"id": "sample_a", "kind": "bam", "path": "/absent/sample_a.bam"}],
        # Deliberately declare the consumer first: order comes from dependencies.
        "steps": [
            {"id": "contamination", "workflow": "contamination", "inputs": {
                "samples": [{"step": "dnp", "output": "dnp-tables", "sample": "sample_a"}],
                "panel": "/absent/dnp.tsv",
            }, "parameters": {}},
            {"id": "dnp", "workflow": "dnp-call", "inputs": {
                "samples": ["sample_a"], "reference": "/absent/reference.fa",
                "panel": "/absent/dnp.tsv",
            }, "parameters": {"parallel": False}},
        ],
    }
    plan_file = inputs / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    before = plan_file.read_bytes()
    report = json.loads(run_image(
        identifier, ["validate-plan", "--plan", "/inputs/plan.json"], inputs=inputs,
    ))
    expected_plan = {**plan, "steps": list(reversed(plan["steps"]))}
    if report.get("execution_order") != ["dnp", "contamination"] or report.get("plan") != expected_plan:
        raise ValueError("The bundled validator returned an unexpected plan or execution order.")
    if plan_file.read_bytes() != before:
        raise ValueError("Plan validation changed the input file.")
    plan["steps"][0]["inputs"]["samples"][0]["output"] = "snp-counts"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    run_image(identifier, ["validate-plan", "--plan", "/inputs/plan.json"],
              inputs=inputs, expected_returncode=2)
    print("PASS: bundled workflow plan validation and rejection, without executing analyses.", flush=True)


def check_snp(identifier: str, root: Path) -> None:
    examples = PROJECT / "scientific/vendor/NEWPAT/SNPcall/examples"
    inputs = root / "snp-inputs"
    inputs.mkdir()
    for name in ("pileup.txt", "SNPlist.txt"):
        shutil.copyfile(examples / name, inputs / name)
    results = root / "snp-results"
    run_image(identifier, [
        "run", "snp-call", "--", "--pileup", "/inputs/pileup.txt",
        "--snplist", "/inputs/SNPlist.txt", "--out", "/results/output/SNPcall_output.txt",
    ], inputs=inputs, results=results)
    rows = compare_snp_outputs(examples / "output.txt", results / "output/SNPcall_output.txt")
    print(f"PASS: bundled SNPcall, {rows} reference rows.", flush=True)


def check_contamination_fixture(identifier: str, root: Path) -> None:
    fixture = PROJECT / "tests/fixtures/contamination"
    inputs = root / "contamination-inputs"
    (inputs / "samples").mkdir(parents=True)
    for source_name, target_name in (
        ("NoRatio.tsv", "NoRatio.txt"), ("WithRatio.TXT", "WithRatio.txt"),
        ("NoSites.txt", "NoSites.txt"),
    ):
        shutil.copyfile(fixture / "samples" / source_name, inputs / "samples" / target_name)
    # Explicit native-format fixture setup, not proof of in-image client preparation.
    write_position_panel(read_position_panel(fixture / "DNP_list.txt"), inputs / "panel.txt")
    results = root / "contamination-results"
    run_image(identifier, [
        "run", "contamination", "--", "/inputs/panel.txt", "/inputs/samples",
        "/results/output",
    ], inputs=inputs, results=results)
    check_contamination(results)
    print("PASS: bundled Contamination, reference values and no-sites case.", flush=True)


def write_request(results: Path, request: dict) -> None:
    (results / "work").mkdir(parents=True)
    (results / "output").mkdir()
    (results / "work/request.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def compare_snp_with_diagnostics(expected: Path, actual: Path) -> int:
    try:
        return compare_snp_outputs(expected, actual)
    except NipatError:
        print(f"Expected SNPcall output:\n{expected.read_text(encoding='utf-8')}", file=sys.stderr)
        if actual.is_file():
            print(f"Actual SNPcall output:\n{actual.read_text(encoding='utf-8')}", file=sys.stderr)
        raise


def check_snp_intermediates(run_dir: Path) -> Path:
    expected_bed = "chrSynthetic\t48\t51\nchrSynthetic\t118\t121\n"
    if (run_dir / "work/snp_regions.bed").read_text(encoding="utf-8") != expected_bed:
        raise ValueError("The engine produced unexpected SNP three-base BED windows.")
    pileup = run_dir / "work/pileup.txt"
    require_snp_pileup(pileup)
    rows = [line.split("\t") for line in pileup.read_text(encoding="utf-8").splitlines()]
    expected_positions = {(str(position), str(depth)) for position, depth in (
        (49, 7), (50, 7), (51, 7), (119, 6), (120, 6), (121, 6),
    )}
    if (len(rows) != 6 or any(row[0] != "chrSynthetic" or len(row) != 7 for row in rows)
            or {(row[1], row[3]) for row in rows} != expected_positions):
        raise ValueError(f"Unexpected retained SNP pileup positions/depths: {rows}")
    return pileup


def build_snp_bam_fixture(identifier: str, root: Path) -> Path:
    """Compile committed synthetic text inputs using the image's own samtools."""
    fixture = PROJECT / "tests/fixtures/snp_engine"
    generated = root / "generated SNP assets"
    inputs = generated / "work"
    inputs.mkdir(parents=True)
    for name in ("reference.fa", "SNPlist.tsv"):
        shutil.copyfile(fixture / name, inputs / name)
    run_container(identifier, [
        "samtools", "view", "-b", "-o", "/results/work/sample.bam", "/inputs/reads.sam",
    ], inputs=fixture, results=generated)
    run_container(identifier, ["samtools", "faidx", "/results/work/reference.fa"],
                  results=generated)
    if not (inputs / "sample.bam").is_file() or not (inputs / "reference.fa.fai").is_file():
        raise ValueError("Synthetic BAM/FASTA-index preparation failed.")
    if any(inputs.glob("*.bai")) or any(inputs.glob("*.csi")):
        raise ValueError("This regression must exercise the supported unindexed-BAM path.")
    return inputs


def check_snp_workflow(identifier: str, root: Path) -> tuple[Path, Path]:
    examples = PROJECT / "scientific/vendor/NEWPAT/SNPcall/examples"
    example_inputs = root / "snp-inputs"
    pileup_request = {
        "schema_version": 1, "workflow": "snp-call", "mode": "pileup",
        "panel": "/inputs/SNPlist.txt", "bam": None,
        "pileup": "/inputs/pileup.txt", "reference": None,
        "work_dir": "/results/work", "out_dir": "/results/output",
    }
    pileup_results = root / "complete SNP pileup results"
    write_request(pileup_results, pileup_request)
    run_image(identifier, ["execute", "snp-call", "--request", "/results/work/request.json"],
              inputs=example_inputs, results=pileup_results)
    compare_snp_with_diagnostics(examples / "output.txt", pileup_results / "output/SNPcall_output.txt")
    if (pileup_results / "work/snp_regions.bed").exists() or (pileup_results / "work/pileup.txt").exists():
        raise ValueError("An existing pileup must not trigger BAM preparation.")
    if any((example_inputs / name).read_bytes() != (examples / name).read_bytes()
           for name in ("pileup.txt", "SNPlist.txt")):
        raise ValueError("The complete SNP pileup workflow changed an original input.")
    print("PASS: complete SNPcall from an existing pileup, all nine reference rows.", flush=True)

    inputs = build_snp_bam_fixture(identifier, root)
    originals = {path: path.read_bytes() for path in inputs.iterdir() if path.is_file()}
    bam_request = {
        **pileup_request, "mode": "bam", "panel": "/inputs/SNPlist.tsv",
        "bam": "/inputs/sample.bam", "pileup": None, "reference": "/inputs/reference.fa",
    }
    bam_results = root / "complete SNP BAM results"
    write_request(bam_results, bam_request)
    run_image(identifier, ["execute", "snp-call", "--request", "/results/work/request.json"],
              inputs=inputs, results=bam_results)
    expected = PROJECT / "tests/fixtures/snp_engine/expected.tsv"
    compare_snp_with_diagnostics(expected, bam_results / "output/SNPcall_output.txt")
    check_snp_intermediates(bam_results)
    if any(path.read_bytes() != content for path, content in originals.items()):
        raise ValueError("The complete SNP BAM workflow changed an original input.")
    print("PASS: complete SNPcall from unindexed BAM, independent allele counts, BED and pileup retained.",
          flush=True)

    invalid_pileup = inputs / "six-columns.txt"
    invalid_pileup.write_text("chrSynthetic\t50\tA\t1\t.\tI\n", encoding="utf-8")
    rejected_pileup = root / "rejected SNP pileup"
    write_request(rejected_pileup, {
        **pileup_request, "panel": "/inputs/SNPlist.tsv", "pileup": "/inputs/six-columns.txt",
    })
    diagnostics = run_image(
        identifier, ["execute", "snp-call", "--request", "/results/work/request.json"],
        inputs=inputs, results=rejected_pileup, expected_returncode=2,
    )
    if "7 colonne" not in diagnostics or "NIPAT scientific engine:" not in diagnostics:
        raise ValueError(f"Unexpected six-column pileup diagnostics: {diagnostics}")
    if ({path.name for path in (rejected_pileup / "work").iterdir()} != {"request.json"}
            or any((rejected_pileup / "output").iterdir())):
        raise ValueError("Invalid SNP input produced intermediate or scientific output.")

    invalid_bam = inputs / "invalid.bam"
    invalid_bam.write_bytes(b"This deliberately is not a BAM file.\n")
    rejected_bam = root / "failed SNP samtools"
    write_request(rejected_bam, {**bam_request, "bam": "/inputs/invalid.bam"})
    diagnostics = run_image(
        identifier, ["execute", "snp-call", "--request", "/results/work/request.json"],
        inputs=inputs, results=rejected_bam, expected_returncode=1,
    )
    if "samtools" not in diagnostics.lower() and "mpileup" not in diagnostics.lower():
        raise ValueError(f"Expected a samtools failure, got: {diagnostics}")
    if "snpscall started" in diagnostics or any((rejected_bam / "output").iterdir()):
        raise ValueError("R ran after failed samtools preparation.")
    print("PASS: SNPcall rejects invalid pileup before preparation and propagates samtools failure without R.",
          flush=True)
    return inputs, expected


def check_snp_client_without_host_scripts(identifier: str, root: Path,
                                          inputs: Path, expected: Path) -> None:
    project = root / "SNP client without scientific sources"
    project.mkdir()
    shutil.copyfile(PROJECT / "compose.yaml", project / "compose.yaml")
    layout = ProjectLayout(project, root, root / "SNP client data", root / "SNP client results",
                           project / "compose.yaml")
    originals = {path: path.read_bytes() for path in inputs.iterdir() if path.is_file()}
    with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
        workflow = Workflows(layout, DockerComposeRunner(layout))
        bam_run = workflow.snp_call(
            bam=inputs / "sample.bam", reference=inputs / "reference.fa",
            panel=inputs / "SNPlist.tsv", run_name="complete-snp-bam",
        )
        compare_snp_with_diagnostics(expected, bam_run / "output/SNPcall_output.txt")
        pileup = check_snp_intermediates(bam_run)
        pileup_bytes = pileup.read_bytes()
        check_bundled_run(bam_run, layout, workflow="snp-call")
        # Reuse a real intermediate from a previous run through public input
        # selection. It must be mounted read-only, not become a writable old run.
        pileup_run = workflow.snp_call(
            pileup=pileup, panel=inputs / "SNPlist.tsv", run_name="complete-snp-pileup",
        )
    compare_snp_with_diagnostics(expected, pileup_run / "output/SNPcall_output.txt")
    compare_snp_outputs(bam_run / "output/SNPcall_output.txt", pileup_run / "output/SNPcall_output.txt")
    check_bundled_run(pileup_run, layout, workflow="snp-call")
    if pileup.read_bytes() != pileup_bytes or any(
        path.read_bytes() != content for path, content in originals.items()
    ):
        raise ValueError("The CLI SNP workflows changed original inputs or a previous run's pileup.")
    if {path.name for path in project.iterdir()} != {"compose.yaml"}:
        raise ValueError("The source-free client test unexpectedly populated its application directory.")
    print("PASS: CLI SNPcall BAM and reused-pileup modes without host scientific sources, "
          "with isolated mounts, numeric parity and recorded engine identity.", flush=True)


def check_contamination_workflow(identifier: str, root: Path) -> None:
    fixture = PROJECT / "tests/fixtures/contamination"
    inputs = root / "complete Contamination inputs"
    shutil.copytree(fixture / "samples", inputs / "samples")
    shutil.copyfile(fixture / "DNP_list.txt", inputs / "panel-original.txt")
    sample_names = ("NoRatio.tsv", "WithRatio.TXT", "NoSites.txt")
    request = {
        "schema_version": 1, "workflow": "contamination",
        "panel": "/inputs/panel-original.txt",
        "samples": [{"path": f"/inputs/samples/{name}", "name": Path(name).stem + ".txt"}
                    for name in sample_names],
        "work_dir": "/results/work", "out_dir": "/results/output",
    }
    originals = {path: path.read_bytes() for path in inputs.rglob("*") if path.is_file()}
    results = root / "complete Contamination results"
    write_request(results, request)
    run_image(identifier, ["execute", "contamination", "--request", "/results/work/request.json"],
              inputs=inputs, results=results)
    check_contamination(results)
    staged = results / "work/inputs"
    expected_names = {Path(name).stem + ".txt" for name in sample_names}
    if {path.name for path in staged.iterdir()} != expected_names:
        raise ValueError("The engine changed the original sample names during staging.")
    for name in sample_names:
        if (staged / (Path(name).stem + ".txt")).read_bytes() != originals[inputs / "samples" / name]:
            raise ValueError(f"The engine changed the table bytes during staging: {name}")
    expected_panel = root / "expected-native-panel.txt"
    write_position_panel(read_position_panel(fixture / "DNP_list.txt"), expected_panel)
    if (results / "work/DNPpanel.txt").read_bytes() != expected_panel.read_bytes():
        raise ValueError("The engine produced an unexpected normalized panel.")
    if any(path.read_bytes() != content for path, content in originals.items()):
        raise ValueError("The complete Contamination workflow changed an original input.")
    print("PASS: complete Contamination preparation, original names/bytes and numeric results.",
          flush=True)

    # Failed validation must be distinguishable from a Docker start failure or
    # an R failure, and it must not produce staged data or scientific outputs.
    missing_counts = inputs / "samples/BadCounts.tsv"
    missing_counts.write_text("chr\tpos1\tpos2\tN_REF\nchr1\t100\t101\t95\n", encoding="utf-8")
    invalid_cases = (
        ("duplicate names", [request["samples"][0],
                             {"path": request["samples"][1]["path"], "name": "noratio.txt"}],
         "Nome file duplicato nello staging"),
        ("missing counts", [{"path": "/inputs/samples/BadCounts.tsv", "name": "BadCounts.txt"}],
         "colonne mancanti"),
    )
    for label, samples, expected_error in invalid_cases:
        rejected = root / f"rejected Contamination {label}"
        write_request(rejected, {**request, "samples": samples})
        diagnostics = run_image(
            identifier, ["execute", "contamination", "--request", "/results/work/request.json"],
            inputs=inputs, results=rejected, expected_returncode=2,
        )
        if "NIPAT scientific engine:" not in diagnostics or expected_error not in diagnostics:
            raise ValueError(f"Unexpected rejection diagnostics for {label}: {diagnostics}")
        if any((rejected / "output").iterdir()) or (rejected / "work/inputs").exists() \
                or (rejected / "work/DNPpanel.txt").exists():
            raise ValueError(f"Invalid {label} produced staging or scientific output.")
    print("PASS: complete Contamination rejects duplicate names and missing counts before R.",
          flush=True)


def check_cpi_fixture(identifier: str, root: Path) -> None:
    fixture = PROJECT / "tests/fixtures/cpi"
    inputs = root / "cpi-inputs"
    shutil.copytree(fixture / "samples", inputs / "samples")
    shutil.copyfile(fixture / "pop_allFreq.txt", inputs / "pop_allFreq.txt")
    write_position_panel(read_position_panel(fixture / "DNP_list.txt"), inputs / "panel.txt")
    results = root / "cpi-results"
    run_image(identifier, [
        "run", "cpi", "--", "--pileup_dir", "/inputs/samples",
        "--out_dir", "/results/output", "--pairs", "Informative:Informative,NoSites:NoSites",
        "--mother_prefix", "Mother", "--father_prefix", "Father",
        "--popfreq", "/inputs/pop_allFreq.txt", "--err_const", "0.0000892303778101497",
        "--cutoff_map", "/inputs/panel.txt",
    ], inputs=inputs, results=results)
    check_cpi(results, "/inputs/panel.txt")
    print("PASS: bundled CPI, reference values, no-sites case and three PDFs.", flush=True)


def check_contamination_client_without_host_scripts(identifier: str, root: Path) -> None:
    # The client can load its installed Python package, but its project folder
    # deliberately has no scientific/, engine/ or src/ tree to mount or verify.
    project = root / "client without scientific sources"
    project.mkdir()
    shutil.copyfile(PROJECT / "compose.yaml", project / "compose.yaml")
    layout = ProjectLayout(project, root, root / "client data", root / "client results",
                           project / "compose.yaml")
    inputs = root / "recursive original inputs"
    fixture = PROJECT / "tests/fixtures/contamination"
    shutil.copytree(fixture / "samples", inputs / "nested samples")
    shutil.copyfile(fixture / "DNP_list.txt", inputs / "panel.txt")
    originals = {path: path.read_bytes() for path in inputs.rglob("*") if path.is_file()}
    with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
        run_dir = Workflows(layout, DockerComposeRunner(layout)).contamination(
            input_dir=inputs, panel=inputs / "panel.txt", run_name="complete-contamination",
        )
    check_contamination(run_dir)
    check_bundled_run(run_dir, layout)
    if any(path.read_bytes() != content for path, content in originals.items()):
        raise ValueError("The CLI Contamination workflow changed an original input.")
    print("PASS: CLI Contamination from recursive inputs without host scientific sources, "
          "with isolated mounts and recorded engine identity.", flush=True)


def check_doctor_without_host_scripts(identifier: str, root: Path) -> None:
    project = root / "diagnostics without scientific sources"
    project.mkdir()
    shutil.copyfile(PROJECT / "compose.yaml", project / "compose.yaml")
    layout = ProjectLayout(project, root, root / "doctor data", root / "doctor results",
                           project / "compose.yaml")
    with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
        DockerComposeRunner(layout).doctor(True)
    if {path.name for path in project.iterdir()} != {"compose.yaml"}:
        raise ValueError("Runtime diagnostics unexpectedly populated the application directory.")
    print("PASS: runtime diagnostics verify all four bundled interfaces without host scientific sources.",
          flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="already-built local Docker image")
    args = parser.parse_args()
    root: Path | None = None
    try:
        identifier = image_id(args.image)
        check_metadata(identifier)
        check_catalog(identifier)
        print(f"PASS: bundled code integrity, image {identifier}", flush=True)
        root = Path(tempfile.mkdtemp(prefix="nipat engine package ")).resolve()
        check_plan_contract(identifier, root)
        check_doctor_without_host_scripts(identifier, root)
        check_snp(identifier, root)
        snp_inputs, snp_expected = check_snp_workflow(identifier, root)
        check_snp_client_without_host_scripts(identifier, root, snp_inputs, snp_expected)
        dnp_inputs = check_dnp_workflow(identifier, root, run_container=run_container,
                                      run_image=run_image, write_request=write_request)
        check_dnp_client_without_host_scripts(identifier, root, dnp_inputs)
        check_snp_plans(identifier, root, snp_inputs, snp_expected, dnp_inputs,
                        run_image=run_image, run_container=run_container,
                        check_snp_intermediates=check_snp_intermediates)
        check_workflow_execution(identifier, root, dnp_inputs, run_image=run_image,
                                 write_request=write_request)
        check_cpi_chains(identifier, root, dnp_inputs, run_image=run_image,
                         run_container=run_container, write_request=write_request)
        check_imported_cpi_plans(identifier, root, run_image=run_image, write_request=write_request)
        check_contamination_fixture(identifier, root)
        check_contamination_workflow(identifier, root)
        check_cpi_fixture(identifier, root)
        cpi_inputs = check_cpi_workflow(identifier, root, run_image=run_image, write_request=write_request)
        check_cpi_client_without_host_scripts(identifier, root, cpi_inputs)
        check_contamination_client_without_host_scripts(identifier, root)
    except (NipatError, OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"Engine package verification failed: {exc}", file=sys.stderr)
        if root is not None:
            print(f"Synthetic inputs and failed-run diagnostics retained at: {root}", file=sys.stderr)
        return 1
    shutil.rmtree(root)
    print("PASS: numeric regressions and validation failures without application/source mounts or network.")
    print("Complete DNPcall, SNPcall, Contamination and CPI, plus automatic DNPcall -> Contamination/CPI plans and independent SNP batches/tasks, verified inside the bundled engine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
