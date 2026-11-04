"""Verify opt-in telemetry against real containers and synthetic scientific data.

This is a correctness integration check, not a speed benchmark. It compares
single-BAM DNPcall results with diagnostics disabled/enabled and deliberately
exceeds a small container memory limit to verify retained failure evidence.
No researcher data, machine speed threshold or host scientific sources are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nipat.errors import RuntimeExecutionError
from nipat.execution.options import ExecutionOptions
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout
from verify_dnp_engine import check_dnp_outputs, compare_dnp_tables
from verify_engine_package import docker, image_id
from verify_presentation import fixtures


PROJECT = Path(__file__).resolve().parents[1]
MAX_EVIDENCE_BYTES = 34 * 1024 * 1024


def document(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected object: {path}")
    return value


def rows(path: Path) -> list[dict]:
    if path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ValueError(f"Unbounded diagnostic evidence: {path}")
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if any(not isinstance(value, dict) for value in values):
        raise ValueError(f"Expected JSONL objects: {path}")
    return values


def check_engine_evidence(run: Path) -> dict:
    directory = run / "performance/engine"
    summary = document(directory / "summary.json")
    samples = rows(directory / "samples.jsonl")
    phases = rows(directory / "phases.jsonl")
    if (summary.get("interface") != "performance-diagnostics-v1"
            or summary.get("status") != "complete"
            or summary.get("samples") != len(samples) or not samples
            or summary.get("phase_events") != len(phases)
            or summary.get("errors") or summary.get("truncated")):
        raise ValueError("Engine diagnostics did not complete with bounded, consistent evidence")
    # Both cgroup generations are supported. A missing optional high-water mark
    # is not a failure: older kernels do not expose memory.peak.
    memory = [sample["cgroup"].get("memory_current_bytes") for sample in samples]
    if not any(type(value) is int and value > 0 for value in memory):
        raise ValueError("No actual cgroup memory observation was retained")
    cpu = [sample["cgroup"].get("cpu", {}).get("usage_usec")
           if isinstance(sample["cgroup"].get("cpu"), dict) else None for sample in samples]
    cpu.extend(sample["cgroup"].get("cpu_usage_ns") for sample in samples)
    if not any(type(value) is int and value >= 0 for value in cpu):
        raise ValueError("No actual cgroup CPU observation was retained")
    completed = {phase.get("phase") for phase in phases if phase.get("event") == "end"}
    if not {"preparation", "r-execution", "output-validation", "presentation-finalization"} <= completed:
        raise ValueError("Engine phase evidence is incomplete")
    for phase in phases:
        if phase.get("event") == "end" and (
            type(phase.get("duration_seconds")) not in (int, float) or phase["duration_seconds"] < 0
        ):
            raise ValueError("Engine phase duration is not a non-negative measured interval")
    return {"samples": len(samples), "phases": sorted(completed),
            "cgroup_versions": sorted({sample["cgroup"].get("version") for sample in samples}),
            "memory_observed": True, "cpu_observed": True}


def check_external_evidence(run: Path, *, require_samples: bool = False) -> dict:
    summary = document(run / "performance/summary.json")
    samples = rows(run / "performance/container-samples.jsonl")
    if summary.get("source") != "docker-cli-stats" or summary.get("sample_count") != len(samples):
        raise ValueError("External observer evidence is missing or inconsistent")
    if require_samples and not samples:
        raise ValueError("The long-lived synthetic container produced no external samples")
    if summary.get("status") == "collecting":
        raise ValueError("External observer was not finalized before cleanup")
    if samples:
        if not any("memory_cache_adjusted_bytes" in sample and "cpu_percent" in sample for sample in samples):
            raise ValueError("External samples lack Docker CPU and memory observations")
        if len(summary.get("container_id", "")) != 64:
            raise ValueError("External observer did not record its immutable container identity")
    # A short analysis may finish before docker stats has delivered its first
    # sample; this must remain explicit and must not be converted into zeros.
    elif summary.get("status") != "unavailable" or not summary.get("reason"):
        raise ValueError("Absent external samples were not explicitly reported")
    return {"status": summary.get("status"), "sample_count": len(samples)}


def check_cleanup(run: Path, *, status: str) -> dict:
    record = document(run / "run.json")
    if record.get("status") != status:
        raise ValueError(f"Unexpected recorded status: {record.get('status')}")
    commands = record.get("commands", [])
    if not commands or any(command.get("container_cleanup", {}).get("status") != "removed"
                           for command in commands):
        raise ValueError("Owned analysis containers were not removed")
    for command in commands:
        identifier = command.get("container_diagnostics", {}).get("container_id")
        if not isinstance(identifier, str) or len(identifier) != 64:
            raise ValueError("Run is missing verified container identity")
        if docker(["container", "ls", "--all", "--quiet", "--no-trunc", "--filter", f"id={identifier}"]).strip():
            raise ValueError("An analysis container still exists after cleanup")
    return record


def verify(root: Path, identifier: str) -> dict:
    project = root / "client"
    project.mkdir()
    shutil.copyfile(PROJECT / "compose.yaml", project / "compose.yaml")
    layout = ProjectLayout(project, root, root / "data", root / "runs", project / "compose.yaml")
    inputs = fixtures(identifier, root)
    original = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in inputs.rglob("*") if path.is_file()}
    runs = []
    with patch.dict(os.environ, {"NIPAT_RUNTIME_IMAGE": identifier, "NIPAT_BACKEND": "native"}):
        for enabled in (False, True):
            runner = DockerComposeRunner(layout, options=ExecutionOptions(performance_diagnostics=enabled))
            run = Workflows(layout, runner).dnp_call(
                bam=inputs / "bams/sample_0001.bam", reference=inputs / "reference.fa",
                panel=inputs / "DNP_list.txt", run_name="dnp-measured" if enabled else "dnp-baseline",
            )
            check_dnp_outputs(run, ("A",))
            check_cleanup(run, status="succeeded")
            runs.append(run)
        if (runs[0] / "performance").exists():
            raise ValueError("Diagnostics were collected without an opt-in")
        compare_dnp_tables(*runs)
        measured = {"engine": check_engine_evidence(runs[1]), "external": check_external_evidence(runs[1])}
        print("PASS: one synthetic BAM, independent DNP counts, unchanged canonical tables, "
              "opt-in cgroup/process/phase evidence and owned-container cleanup.", flush=True)

        # Separate from the scientific equivalence check. The observer runs on
        # the host, while only this disposable container is allowed 128 MiB.
        # This synthetic process waits a bounded time for the external observer
        # to flush its first sample before triggering the intentional OOM.
        runner = DockerComposeRunner(layout, options=ExecutionOptions(
            memory_mb=128, performance_diagnostics=True,
        ))
        failed = layout.new_run_dir("diagnostic-check", "intentional-container-oom")
        try:
            with runner.record_run(failed, workflow="diagnostic-check", inputs=[], parameters={},
                                   bundled_workflow="dnp-call"):
                runner.run([
                    "python3", "-c",
                    "import pathlib,sys,time\n"
                    "path=pathlib.Path(sys.argv[1]); deadline=time.monotonic()+30\n"
                    "while time.monotonic()<deadline:\n"
                    "    if path.is_file() and path.stat().st_size: break\n"
                    "    time.sleep(0.1)\n"
                    "else: sys.exit(23)\n"
                    "block=bytearray(512*1024*1024)\n"
                    "block[::4096]=b'x'*(len(block)//4096)\n",
                    layout.container_path(failed / "performance/container-samples.jsonl"),
                ])
        except RuntimeExecutionError:
            pass
        else:
            raise ValueError("The controlled container memory limit did not produce an OOM")
        record = check_cleanup(failed, status="failed")
        observation = record["commands"][-1]["container_diagnostics"]
        if (observation.get("state", {}).get("oom_killed") is not True
                or observation.get("diagnosis", {}).get("kind") != "oom_confirmed"):
            raise ValueError("The deliberate failure lacks Docker-confirmed OOM evidence")
        oom = check_external_evidence(failed, require_samples=True)
        print("PASS: Docker-confirmed OOM retains external resource samples and removes only its container.", flush=True)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != wanted for path, wanted in original.items()):
        raise ValueError("Performance diagnostics modified original scientific inputs")
    if {path.name for path in project.iterdir()} != {"compose.yaml"}:
        raise ValueError("Host scientific files were unexpectedly required")
    return {"schema_version": 1, "image_id": identifier, "status": "passed",
            "scope": "Synthetic single-BAM correctness and bounded failure evidence; not a speed benchmark",
            "dnp": measured, "intentional_oom": oom}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.output_dir is None:
        root = Path(tempfile.mkdtemp(prefix="nipat-performance-check-")).resolve()
    else:
        root = args.output_dir.resolve()
        root.mkdir(parents=True, exist_ok=False)
    print(f"Performance correctness artifacts: {root}", flush=True)
    report = verify(root, image_id(args.image))
    (root / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: opt-in performance instrumentation; no speed-up claim inferred.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
