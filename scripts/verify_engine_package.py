"""Check bundled R scripts without mounting the application or source checkout.

This verifies native R invocation and full Contamination preparation/execution.
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
from verify_contamination_update import check_bundled_run
from verify_contamination_update import check_outputs as check_contamination
from verify_cpi_update import check_outputs as check_cpi


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


def run_image(identifier: str, arguments: list[str], *, inputs: Path | None = None,
              results: Path | None = None, expected_returncode: int = 0) -> str:
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
            "--workdir", "/results/work",
        ])
    else:
        command.extend(["--workdir", "/tmp"])
    return docker([*command, identifier, *ENTRYPOINT, *arguments],
                  expected_returncode=expected_returncode)


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
    preparation = description.get("preparation", {})
    if preparation.get("interface") != "contamination-v1":
        raise ValueError("Unexpected preparation metadata interface.")
    source_files = {"engine/main.py": PROJECT / "engine/main.py"}
    for name in ("__init__.py", "errors.py", "panels.py", "files.py", "contamination.py"):
        source_files[f"lib/nipat_scientific/{name}"] = PROJECT / "src/nipat_scientific" / name
    expected_sources = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in source_files.items()
    }
    if preparation.get("file_sha256") != expected_sources:
        raise ValueError("Bundled preparation sources differ from this checkout.")
    return description


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="already-built local Docker image")
    args = parser.parse_args()
    try:
        identifier = image_id(args.image)
        check_metadata(identifier)
        print(f"PASS: bundled code integrity, image {identifier}", flush=True)
        with tempfile.TemporaryDirectory(prefix="nipat engine package ") as directory:
            root = Path(directory).resolve()
            check_snp(identifier, root)
            check_contamination_fixture(identifier, root)
            check_contamination_workflow(identifier, root)
            check_cpi_fixture(identifier, root)
            check_contamination_client_without_host_scripts(identifier, root)
    except (NipatError, OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"Engine package verification failed: {exc}", file=sys.stderr)
        return 1
    print("PASS: five numeric checks and validation failures without application/source mounts or network.")
    print("DNPcall code is bundled and hash-verified; its BAM regression is a separate step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
