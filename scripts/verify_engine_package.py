"""Check bundled R scripts without mounting the application or source checkout.

This verifies native R invocation and three existing numeric fixtures. Python
workflow preparation remains outside the image in this first migration step.
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

from nipat.adapters.panels import read_position_panel, write_position_panel
from nipat.errors import NipatError
from nipat.validation.self_test import compare_snp_outputs
from verify_contamination_update import check_outputs as check_contamination
from verify_cpi_update import check_outputs as check_cpi


PROJECT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ["python3", "/opt/nipat/engine/main.py"]


def docker(arguments: list[str]) -> str:
    result = subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"Docker command failed ({result.returncode}): {arguments}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result.stdout


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
              results: Path | None = None) -> str:
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
        (results / "work").mkdir(parents=True)
        (results / "output").mkdir()
        command.extend([
            "--mount", f"type=bind,source={results},target=/results",
            "--workdir", "/results/work",
        ])
    else:
        command.extend(["--workdir", "/tmp"])
    return docker([*command, identifier, *ENTRYPOINT, *arguments])


def check_metadata(identifier: str) -> dict:
    run_image(identifier, ["verify"])
    description = json.loads(run_image(identifier, ["describe", "--json"]))
    expected_digest = hashlib.sha256((PROJECT / "scientific/SHA256SUMS").read_bytes()).hexdigest()
    if description.get("schema_version") != 1 or description.get("interface") != "native-r-v1":
        raise ValueError("Unexpected bundled engine interface.")
    if description.get("manifest", {}).get("sha256") != expected_digest:
        raise ValueError("Bundled scientific manifest differs from this checkout.")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="already-built local Docker image")
    args = parser.parse_args()
    try:
        identifier = image_id(args.image)
        check_metadata(identifier)
        print(f"PASS: bundled code integrity, image {identifier}", flush=True)
        with tempfile.TemporaryDirectory(prefix="nipat-engine-package-") as directory:
            root = Path(directory).resolve()
            check_snp(identifier, root)
            check_contamination_fixture(identifier, root)
            check_cpi_fixture(identifier, root)
    except (NipatError, OSError, RuntimeError, ValueError, KeyError) as exc:
        print(f"Engine package verification failed: {exc}", file=sys.stderr)
        return 1
    print("PASS: three numeric checks without application/source mounts or network.")
    print("DNPcall code is bundled and hash-verified; its BAM regression is a separate step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
