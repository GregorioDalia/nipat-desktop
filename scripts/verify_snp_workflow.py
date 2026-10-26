"""Real-image SNP plan checks with independent synthetic allele-count oracles.

Called by verify_engine_package.py. Scientific sources stay inside the image;
the public client has only compose.yaml and receives read-only original inputs.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import shutil
from unittest.mock import patch

from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from nipat.validation.files import require_snp_pileup
from nipat.validation.self_test import compare_snp_outputs
from verify_dnp_engine import check_dnp_outputs, compare_dnp_tables
from verify_workflow_execution import _artifact, _state


PROJECT = Path(__file__).resolve().parents[1]
SNP_FIELDS = ["chr", "pos", "Reference", "Alternative", "N_Reference",
              "N_Alternative", "N_Altro", "total_count", "ratio"]


def _expected(path: Path, rows: list[tuple]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(SNP_FIELDS)
        writer.writerows(rows)
    return path


def _client_record(parent: Path, layout: ProjectLayout) -> dict:
    record = json.loads((parent / "run.json").read_text(encoding="utf-8"))
    config = json.loads((parent / "work/engine-compose.json").read_text(encoding="utf-8"))
    service = config["services"]["scientific"]
    if (record["status"] != "succeeded" or record["source"].get("role") != "client"
            or len(record["commands"]) != 1
            or "execute-plan" not in record["commands"][0]["argv"]
            or "snp-call" not in record["runtime"]["engine"]["plan_execution"]["workflows"]):
        raise ValueError("SNP batch did not record one complete, image-owned plan invocation.")
    run_target = str(layout.container_path(parent))
    inputs = {item["container_path"] for item in record["input_mounts"]}
    if (set(config["services"]) != {"scientific"} or service.get("read_only") is not True
            or service.get("network_mode") != "none"
            or len(service["volumes"]) != len(inputs) + 1
            or {item["target"] for item in service["volumes"]} != inputs | {run_target}):
        raise ValueError("SNP plan requires isolated input/current-run mounts and no network.")
    for item in service["volumes"]:
        if (item.get("type") != "bind" or item.get("bind", {}).get("create_host_path") is not False
                or item.get("read_only", False) != (item["target"] != run_target)):
            raise ValueError("SNP plan mounted an original input writable or exposed another directory.")
    return record


def _snp_steps(parent: Path, layout: ProjectLayout, expected: list[tuple[Path, Path]],
               *, mode: str) -> list[Path]:
    """Check original-file -> plan sample -> step -> output identity, not order alone."""
    record = _client_record(parent, layout)
    mounts = {item["container_path"]: Path(item["host_path"]).resolve()
              for item in record["input_mounts"]}
    run = parent / "output/workflow"
    state = _state(run)
    plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
    samples = {item["id"]: item for item in plan["samples"]}
    selected = [item for item in plan["steps"] if item["workflow"] == "snp-call"]
    if state["status"] != "succeeded" or len(selected) != len(expected):
        raise ValueError("SNP plan did not produce the expected number of successful steps.")
    expected_by_source = {source.resolve(): oracle for source, oracle in expected}
    seen = set()
    retained = []
    for step in selected:
        sample_id = step["inputs"]["sample"]
        source = mounts[samples[sample_id]["path"]]
        if source not in expected_by_source or source in seen:
            raise ValueError("SNP plan lost, repeated or reassigned an original sample.")
        seen.add(source)
        execution = next(item for item in state["steps"] if item["id"] == step["id"])
        if execution["status"] != "succeeded" or execution["exit_code"] != 0:
            raise ValueError("A SNP plan step is incomplete.")
        request = json.loads((run / execution["request"]).read_text(encoding="utf-8"))
        if (request["mode"] != mode or step["parameters"]["mode"] != mode
                or request["bam" if mode == "bam" else "pileup"] != samples[sample_id]["path"]):
            raise ValueError("SNP mode or input changed between plan and scientific request.")
        tables = execution["artifacts"]["snp-tables"]
        if len(tables) != 1 or tables[0]["sample"] != sample_id:
            raise ValueError("SNP output artifact lost its explicit sample identity.")
        actual = _artifact(run, tables[0])
        if actual != (run / "steps" / step["id"] / "output/SNPcall_output.txt").resolve():
            raise ValueError("SNP output is not inside its declared step.")
        compare_snp_outputs(expected_by_source[source], actual)
        if not (run / execution["log"]).is_file() or not execution.get("finished_utc"):
            raise ValueError("SNP execution evidence is incomplete.")
        preparation = execution["artifacts"]["preparation"]
        if mode == "bam":
            if (execution.get("preparation_exit_code") != 0
                    or execution.get("preparation_command", [None])[0] != "samtools"
                    or not (run / execution["preparation_log"]).is_file()
                    or {item["kind"] for item in preparation} != {"regions-bed", "pileup"}
                    or len(preparation) != 2):
                raise ValueError("SNP BAM preparation lacks its command, log or intermediates.")
            intermediate = {item["kind"]: _artifact(run, item) for item in preparation}
            require_snp_pileup(intermediate["pileup"])
            retained.append(intermediate["pileup"])
        elif preparation or "preparation_command" in execution:
            raise ValueError("An imported pileup triggered unnecessary BAM preparation.")
    if seen != set(expected_by_source):
        raise ValueError("SNP results do not cover the selected original samples.")
    return retained


def _alternate_sample(identifier: str, root: Path, *, run_container) -> tuple[Path, Path]:
    """Remove exactly one documented REF read per locus from the committed SAM."""
    source = root / "SNP batch second SAM"
    source.mkdir()
    lines = (PROJECT / "tests/fixtures/snp_engine/reads.sam").read_text(encoding="utf-8").splitlines()
    removed = {"site50_read1", "site120_read1"}
    if {line.split("\t", 1)[0] for line in lines} & removed != removed:
        raise ValueError("Synthetic SNP source does not contain the two declared REF reads.")
    (source / "reads.sam").write_text("\n".join(
        line for line in lines if line.split("\t", 1)[0] not in removed
    ) + "\n", encoding="utf-8")
    generated = root / "SNP batch second BAM"
    run_container(identifier, ["samtools", "view", "-b", "-o", "/results/work/sample.bam",
                               "/inputs/reads.sam"], inputs=source, results=generated)
    oracle = _expected(source / "expected.tsv", [
        ("chrSynthetic", 50, "A", "G", 3, 2, 1, 6, 3 / 5),
        ("chrSynthetic", 120, "C", "T", 1, 3, 1, 5, 1 / 4),
    ])
    return generated / "work/sample.bam", oracle


def _failed_snp_plan(identifier: str, root: Path, inputs: Path, *, run_image) -> None:
    broken = root / "SNP plan failure inputs"
    shutil.copytree(inputs, broken)
    (broken / "invalid.bam").write_bytes(b"Deliberately invalid BAM\n")
    plan = {"schema_version": 1, "samples": [
        {"id": "broken", "kind": "bam", "path": "/inputs/invalid.bam"},
        {"id": "valid", "kind": "bam", "path": "/inputs/sample.bam"},
    ], "steps": [
        {"id": label, "workflow": "snp-call", "inputs": {
            "sample": sample, "reference": "/inputs/reference.fa", "panel": "/inputs/SNPlist.tsv",
        }, "parameters": {"mode": "bam"}}
        for label, sample in (("a_failure", "broken"), ("z_independent", "valid"))
    ]}
    destination = root / "failed SNP plan results"
    (destination / "work").mkdir(parents=True)
    (destination / "work/plan.json").write_text(json.dumps(plan), encoding="utf-8")
    run_image(identifier, ["execute-plan", "--plan", "/results/work/plan.json",
                           "--run-dir", "/results/workflow"], inputs=broken,
              results=destination, expected_returncode=1)
    run = destination / "workflow"
    state = _state(run)
    records = {item["id"]: item for item in state["steps"]}
    failed = records["a_failure"]
    if (state["status"] != "failed" or state["exit_code"] != 1
            or failed["status"] != "failed" or failed.get("preparation_exit_code") != 1
            or records["z_independent"]["status"] != "blocked"):
        raise ValueError("samtools failure did not stop the SNP plan deterministically.")
    if (run / "steps/z_independent").exists() or (run / failed["log"]).exists():
        raise ValueError("R or the later independent SNP ran after failed samtools preparation.")
    if not (run / failed["preparation_log"]).is_file():
        raise ValueError("Failed SNP preparation lost its samtools diagnostic log.")


def check_snp_plans(identifier: str, root: Path, inputs: Path, expected: Path,
                    dnp_inputs: Path, *, run_image, run_container,
                    check_snp_intermediates) -> None:
    project = root / "SNP plan client without scientific sources"
    project.mkdir()
    shutil.copyfile(PROJECT / "compose.yaml", project / "compose.yaml")
    layout = ProjectLayout(project, root, root / "SNP plan data", root / "SNP plan runs",
                           project / "compose.yaml")
    second, second_expected = _alternate_sample(identifier, root, run_container=run_container)
    # Same basenames, reversed selection and distinct numeric results make an
    # accidental positional or basename identity swap observable.
    selected = [(second, second_expected), (inputs / "sample.bam", expected)]
    originals = {path: path.read_bytes() for directory in (inputs, dnp_inputs, second.parent)
                 for path in directory.rglob("*") if path.is_file()}
    with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
        workflows = Workflows(layout, DockerComposeRunner(layout))
        batch = workflows.snp_batch(bams=[source for source, _ in selected],
                                    reference=inputs / "reference.fa", panel=inputs / "SNPlist.tsv",
                                    run_name="snp-batch-bams")
        pileups = _snp_steps(batch, layout, selected, mode="bam")
        # The unchanged first sample must retain the exact independently known
        # positions/depths already checked for the standalone interface.
        check_snp_intermediates(pileups[1].parent.parent)
        reference_output = root / "complete SNP BAM results/output/SNPcall_output.txt"
        compare_snp_outputs(reference_output, pileups[1].parent.parent / "output/SNPcall_output.txt")
        old_run = {path: path.read_bytes() for path in batch.rglob("*") if path.is_file()}
        reused = workflows.snp_batch(pileups=list(reversed(pileups)), panel=inputs / "SNPlist.tsv",
                                     run_name="snp-batch-pileups")
        _snp_steps(reused, layout, list(zip(reversed(pileups), (expected, second_expected))), mode="pileup")
        if any(path.read_bytes() != content for path, content in old_run.items()):
            raise ValueError("Reusing SNP intermediates changed a completed run.")

        # The first base of each DNP forms a separate SNP panel. These counts
        # follow directly from the committed artificial dinucleotides: the
        # declared Other dinucleotide has the REF first base at all three loci.
        panel = root / "SNP plan explicit first-base panel.tsv"
        panel.write_text("pos\tref\talt\nchrDnpSynthetic:50\tA\tG\n"
                         "chrDnpSynthetic:140\tT\tC\nchrDnpSynthetic:230\tG\tA\n", encoding="utf-8")
        expected_dnp = []
        for sample, counts in (("A", ((21, 0), (11, 10), (1, 20))),
                               ("B", ((1, 20), (13, 8), (21, 0)))):
            expected_dnp.append(_expected(root / f"SNP plan DNP-{sample} expected.tsv", [
                ("chrDnpSynthetic", pos, ref, alt, ref_count, alt_count, 0, 21, ref_count / 21)
                for (pos, ref, alt), (ref_count, alt_count) in zip(
                    ((50, "A", "G"), (140, "T", "C"), (230, "G", "A")), counts)
            ]))
        bams = [dnp_inputs / f"bams/sample_{number:04d}.bam" for number in (1, 2)]
        combined = workflows.dnp_contamination(bams=bams, reference=dnp_inputs / "reference.fa",
                                               panel=dnp_inputs / "DNP_list.txt", snp_panel=panel,
                                               run_name="dnp-contamination-with-snp")
        _snp_steps(combined, layout, list(zip(bams, expected_dnp)), mode="bam")
        check_dnp_outputs(combined / "output/workflow/steps/dnp", ("A", "B"))
        compare_dnp_tables(root / "complete DNP results", combined / "output/workflow/steps/dnp")
        state = _state(combined / "output/workflow")
        if state["execution_order"] != ["dnp", "contamination", "snp_0001", "snp_0002"]:
            raise ValueError("Adding independent SNP tasks changed deterministic workflow ordering.")
    if any(path.read_bytes() != content for path, content in originals.items()):
        raise ValueError("A SNP plan changed an original input.")
    if {path.name for path in project.iterdir()} != {"compose.yaml"}:
        raise ValueError("SNP plan execution copied scientific sources to the client directory.")
    _failed_snp_plan(identifier, root, inputs, run_image=run_image)
    print("PASS: public SNP BAM/pileup batches and independent SNP tasks beside DNPcall -> Contamination; "
          "distinct same-name samples, independent allele counts, standalone parity, original sample identity, "
          "retained BED/pileup hashes, isolated single-container execution and real samtools failure isolation.", flush=True)
