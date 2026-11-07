"""Cancel the real engine during measured R DNP block processing.

The generated BAM is deliberately small. The test waits for a completed block
reported by R, cancels the supervising engine, and checks persisted workflow
state, process termination and disk-scratch cleanup without diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from verify_indexed_pileup import children, execute


def descendants(pid):
    result = []
    pending = children(pid)
    while pending:
        child = pending.pop()
        result.append(child)
        pending.extend(children(child))
    return result


def running(pid):
    try:
        state = next(line for line in Path(f"/proc/{pid}/status").read_text().splitlines() if line.startswith("State:"))
        return "Z (" not in state and "X (" not in state
    except (FileNotFoundError, ProcessLookupError):
        return False


def events(directory):
    result = []
    for path in directory.glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                # A live writer may have appended only part of the last line.
                continue
    return result


def audit(bundle: Path, root: Path, samtools: str) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    inputs = root / "inputs"
    inputs.mkdir()
    sequence = "ACGT" * 4000
    reference = inputs / "reference.fa"
    reference.write_text(f">chrCancelSynthetic\n{sequence}\n", encoding="utf-8")
    panel = inputs / "panel.txt"
    panel_rows, records = [], []
    loci = 32
    for index in range(loci):
        position = 60 + 200 * index
        ref = sequence[position - 1:position + 1]
        alt = ref.translate(str.maketrans("ACGT", "TGCA"))
        panel_rows.append(f"chrCancelSynthetic\t{position}\t{position + 1}\t{ref}\t{alt}")
        for number in range(8):
            start = position - 30
            bases = list(sequence[start - 1:start + 89])
            if number % 3 == 1:
                bases[30:32] = alt
            records.append("\t".join(map(str, (f"read_{index}_{number}", 0, "chrCancelSynthetic", start, 60,
                                               "90M", "*", 0, 0, "".join(bases), "I" * 90))))
    panel.write_text("\n".join(panel_rows) + "\n", encoding="utf-8")
    sam = inputs / "Cancellation.sam"
    sam.write_text(f"@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chrCancelSynthetic\tLN:{len(sequence)}\n"
                   + "\n".join(records) + "\n", encoding="utf-8")
    bam = inputs / "sample_0001.bam"
    execute([samtools, "sort", "-O", "BAM", "-o", str(bam), str(sam)])
    execute([samtools, "index", str(bam)])
    execute([samtools, "faidx", str(reference)])
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs.iterdir()}
    plan = {"schema_version": 1, "samples": [{"id": "sample_cancel", "kind": "bam", "path": str(bam)}],
            "steps": [{"id": "dnp", "workflow": "dnp-call", "inputs": {
                "samples": ["sample_cancel"], "reference": str(reference), "panel": str(panel)},
                "parameters": {"parallel": False}}]}
    plan_file = root / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    progress = root / "progress"
    scratch = root / "scratch"
    progress.mkdir()
    scratch.mkdir()
    library = bundle / ("lib" if (bundle / "lib").is_dir() else "src") / "nipat_scientific"
    environment = os.environ.copy()
    environment.update(NIPAT_DNP_BLOCK_LOCI="1", NIPAT_SCRATCH_ROOT=str(scratch),
                       NIPAT_PROGRESS_DIR=str(progress), NIPAT_DNP_BLOCKS_HELPER=str(library / "dnp_blocks.R"))
    environment.pop("NIPAT_PERFORMANCE_DIR", None)
    environment.pop("NIPAT_DNP_KEEP_PILEUP", None)
    run_dir = root / "run"
    engine = bundle / "engine/main.py"
    command = [sys.executable, str(engine), "execute-plan", "--plan", str(plan_file), "--run-dir", str(run_dir), "--json"]
    observed = None
    owned = []
    with (root / "stdout.log").open("wb") as stdout, (root / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, env=environment, stdout=stdout, stderr=stderr)
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and process.poll() is None:
                observed = next((event for event in events(progress)
                                 if event.get("interface") == "nipat-progress-v1"
                                 and event.get("phase") == "dnp-processing" and event.get("event") == "progress"
                                 and event.get("unit") == "loci" and event.get("total") == loci
                                 and 0 < event.get("completed", 0) < loci), None)
                if observed is not None:
                    break
                time.sleep(0.02)
            if observed is None:
                raise AssertionError(f"No measured R block progress before cancellation; engine exit={process.poll()}, see {root}")
            if observed.get("sample_ids") != ["sample_cancel"] or observed.get("step_id") != "dnp":
                raise AssertionError("R block progress lost the plan's sample or step identity")
            owned = descendants(process.pid)
            if not owned:
                raise AssertionError("The engine has no active R child during reported processing")
            # Sample/source identity proves this is an R event from the actual
            # processing child, not just the Python phase wrapper.
            r_pid = int(observed["source_id"].split("-")[1])
            if r_pid not in owned or not running(r_pid):
                raise AssertionError("Measured block progress was not emitted by the engine's live R child")
            started = time.monotonic()
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=15)
            cancellation_seconds = time.monotonic() - started
            if process.returncode != 128 + signal.SIGTERM:
                raise AssertionError(f"Engine cancellation returned {process.returncode}; see {root}")
            deadline = time.monotonic() + 3
            while any(running(pid) for pid in owned) and time.monotonic() < deadline:
                time.sleep(0.02)
            if any(running(pid) for pid in owned):
                raise AssertionError("The cancelled engine left running scientific children")
        finally:
            if process.poll() is None:
                owned = list(set(owned + descendants(process.pid)))
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for pid in owned:
                if running(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
    state_path = run_dir / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state["status"] != "cancelled" or state["exit_code"] != 143 or state["steps"][0]["status"] != "cancelled":
        raise AssertionError("The workflow did not persist cancellation")
    if list(scratch.iterdir()):
        raise AssertionError("The cancelled R invocation left disk scratch files")
    if any(run_dir.rglob("performance.json")):
        raise AssertionError("The cancellation audit unexpectedly enabled performance diagnostics")
    if any(event.get("phase") == "dnp-processing" and event.get("event") == "end"
           and event.get("outcome") == "succeeded" for event in events(progress)):
        raise AssertionError("Cancelled R block processing incorrectly reported success")
    if hashes != {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs.iterdir()}:
        raise AssertionError("Cancellation modified the source fixture")
    return {"schema_version": 1, "status": "passed", "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
            "observed_r_progress": observed, "exit_code": process.returncode, "workflow_status": state["status"],
            "step_status": state["steps"][0]["status"], "cancellation_seconds": cancellation_seconds,
            "running_children_after_cancellation": 0, "scratch_empty": True, "inputs_unchanged": True,
            "diagnostics_required": False, "block_loci_limit": 1, "synthetic_loci": loci}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samtools", default="samtools")
    args = parser.parse_args()
    result = audit(args.bundle.resolve(), args.output_dir.resolve(), args.samtools)
    (args.output_dir / "dnp-cancellation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
