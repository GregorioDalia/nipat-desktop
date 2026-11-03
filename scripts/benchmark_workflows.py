"""Run a reproducible DNPcall/Contamination workload matrix on supplied BAMs.

This is an opt-in performance tool, not a default CI gate. Reports remain local
and include input paths; review them before sharing. No synthetic performance
claims are inferred when the requested number of distinct samples is absent.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nipat.errors import NipatError
from nipat.execution.options import ExecutionOptions
from nipat.execution.runner import PLAN_WORKFLOWS, _finish_cleanup
from nipat.execution.workflows import _select_bams


def _reported_ram(log: str) -> list[float]:
    return [float(value) for value in re.findall(
        r"Peak RAM(?: usage)? \(MB\):\s*([0-9]+(?:\.[0-9]+)?)", log)]


def _run_file(run_dir: Path, relative: str) -> Path:
    """Resolve recorded evidence only within this run, without following links."""
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or ":" in relative or any(ord(char) < 32 for char in relative)):
        raise ValueError("Invalid relative evidence path")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or any(part in {".", ".."} for part in relative.split("/")):
        raise ValueError("Evidence path escapes the run directory")
    root = run_dir.resolve()
    path = root
    for part in parts.parts:
        path = path / part
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("Linked evidence paths are not read")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Evidence path escapes the run directory")
    return path


def _step_seconds(step: dict) -> float | None:
    """Recorded wall-clock duration includes preparation, R and output checks."""
    try:
        start = datetime.fromisoformat(step["started_utc"])
        finish = datetime.fromisoformat(step["finished_utc"])
        if start.utcoffset() is None or finish.utcoffset() is None:
            return None
        seconds = (finish - start).total_seconds()
        return seconds if seconds >= 0 else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _performance_evidence(run_dir: Path, *, requested: bool) -> dict:
    """Read only bounded summaries; keep absent/partial telemetry explicit."""
    result = {"requested": requested, "host": None, "engine": None, "errors": {}}
    if not requested:
        return result
    for source, relative in (("host", "performance/summary.json"),
                             ("engine", "performance/engine/summary.json")):
        try:
            path = _run_file(run_dir, relative)
            with path.open("rb") as handle:
                content = handle.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise ValueError("Performance summary exceeds 1 MiB")
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ValueError("Performance summary must be an object")
            result[source] = value
        except (OSError, ValueError, RecursionError) as exc:
            result["errors"][source] = type(exc).__name__
    return result


def _workflow_evidence(run_dir: Path, *, required: bool = False) -> tuple[list[dict], str | None]:
    """Read a plan's recorded steps; missing/unsafe evidence remains explicit."""
    try:
        state_path = _run_file(run_dir, "output/workflow/workflow-state.json")
        if not state_path.exists():
            return [], "Workflow state is unavailable" if required else None
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if (not isinstance(state, dict) or type(state.get("schema_version")) is not int
                or state["schema_version"] != 1 or not isinstance(state.get("steps"), list)
                or any(not isinstance(step, dict) for step in state["steps"])):
            raise ValueError("Invalid workflow state")
    except (OSError, ValueError, RecursionError) as exc:
        return [], str(exc)
    observations = []
    for step in state["steps"]:
        observation = {
            "id": step.get("id"), "workflow": step.get("workflow"),
            "status": step.get("status"), "started_utc": step.get("started_utc"),
            "finished_utc": step.get("finished_utc"),
            "duration_seconds": _step_seconds(step),
            "duration_scope": "Recorded step wall time, including preparation, R and output checks",
            "log": step.get("log"), "log_error": None,
            "r_reported_peak_ram_mb": None,
        }
        if step.get("workflow") == "dnp-call":
            try:
                relative = step.get("log")
                if not isinstance(relative, str):
                    raise ValueError("DNP step log path is missing")
                # Reject traversal relative to the workflow, before prefixing it.
                if PurePosixPath(relative).is_absolute():
                    raise ValueError("Invalid absolute step log path")
                log_path = _run_file(run_dir, "output/workflow/" + relative)
                values = _reported_ram(log_path.read_text(encoding="utf-8", errors="replace"))
                observation["r_reported_peak_ram_mb"] = max(values, default=None)
            except (OSError, ValueError) as exc:
                observation["log_error"] = str(exc)
        observations.append(observation)
    return observations, None


def run_case(command: list[str], run_dir: Path, log_path: Path) -> dict:
    started = time.monotonic()
    interrupted = False
    with log_path.open("x", encoding="utf-8") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT)
        try:
            process.wait()
        except KeyboardInterrupt:
            interrupted = True
            # The scientific CLI receives console SIGINT too. Let it stop the
            # named container and persist evidence before ending this supervisor.
            with _finish_cleanup():
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    elapsed = time.monotonic() - started
    record_path = run_dir / "run.json"
    record = {}
    record_error = None
    if record_path.is_file():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("Run evidence must be a JSON object")
        except (OSError, ValueError, RecursionError) as exc:
            record, record_error = {}, str(exc)
    log = (run_dir / "execution.log").read_text(encoding="utf-8", errors="replace") if (
        run_dir / "execution.log"
    ).is_file() else ""
    steps, workflow_error = _workflow_evidence(
        run_dir, required=(record.get("workflow") == "dnp-contamination"
                           or isinstance(record.get("bundled_workflow"), str)
                           and record["bundled_workflow"] in PLAN_WORKFLOWS),
    )
    reported_ram = _reported_ram(log)
    reported_ram.extend(step["r_reported_peak_ram_mb"] for step in steps
                        if step["r_reported_peak_ram_mb"] is not None)
    return {
        "argv": command, "run_dir": str(run_dir), "returncode": process.returncode,
        "status": record.get("status", "invalid_record" if record_error else "not_created"),
        "record_error": record_error, "wall_seconds": elapsed,
        "interrupted": interrupted,
        "run_files_bytes": sum(path.stat().st_size for path in run_dir.rglob("*")
                               if path.is_file() and not path.is_symlink()) if run_dir.is_dir() else 0,
        "r_reported_peak_ram_mb": max(reported_ram, default=None),
        "runtime": record.get("runtime"), "execution_options": record.get("execution_options"),
        "resource_snapshot": record.get("resource_snapshot"),
        "workflow_steps": steps, "workflow_evidence_error": workflow_error,
        "input_evidence": record.get("inputs", []), "command_log": str(log_path),
        "performance_diagnostics": _performance_evidence(
            run_dir, requested=("--performance-diagnostics" in command
                                or isinstance(record.get("execution_options"), dict)
                                and record["execution_options"].get("performance_diagnostics") is True),
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bamlist", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New directory for the benchmark report and isolated runs")
    parser.add_argument("--sample-counts", type=int, nargs="+", default=[1, 10])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--parallel", action="store_true")
    parser.add_argument("--workflow", choices=["dnp-call", "dnp-contamination"], default="dnp-contamination")
    parser.add_argument("--input-hashes", choices=["auto", "full"], default="auto")
    parser.add_argument("--cpus", type=float)
    parser.add_argument("--memory-mb", type=int)
    parser.add_argument("--pids-limit", type=int)
    parser.add_argument("--performance-diagnostics", action="store_true",
                        help="Collect local resource samples and engine phase times (adds overhead)")
    args = parser.parse_args(argv)
    try:
        options = ExecutionOptions(args.input_hashes, args.cpus, args.memory_mb, args.pids_limit,
                                   performance_diagnostics=args.performance_diagnostics)
        bams, _ = _select_bams(bam=None, bams=None, bamlist=args.bamlist.resolve())
        if (args.repeats < 1 or args.repeats > 100 or not args.sample_counts
                or any(count < 1 or count > len(bams) for count in args.sample_counts)):
            parser.error("Counts require distinct available BAMs; repeats must be between 1 and 100.")
        output = args.output_dir.resolve()
        output.mkdir(parents=True, exist_ok=False)
        runs = output / "runs"
        report = {
            "schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(),
            "workflow": args.workflow, "parallel": args.parallel, "options": options.as_dict(),
            "ram_measurement": "Maximum reported R-process RSS observation; not a continuous or whole-container peak",
            "timing_measurement": "Command wall time includes NIPAT preparation and runtime startup; step times come from recorded UTC timestamps",
            "cases": [],
        }
        report_path = output / "benchmark.json"
        for count in dict.fromkeys(args.sample_counts):
            bamlist = output / f"samples-{count}.txt"
            bamlist.write_text("\n".join(str(path) for path in bams[:count]) + "\n", encoding="utf-8")
            for repeat in range(1, args.repeats + 1):
                name = f"benchmark-{count}-{repeat}-{uuid.uuid4().hex[:8]}"
                command = [sys.executable, "-I", "-c",
                           "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
                           "runpy.run_module('nipat',run_name='__main__')",
                           str(Path(__file__).resolve().parents[1] / "src"), "--runs-dir", str(runs),
                           "--input-hashes", args.input_hashes]
                for flag, value in (("--cpus", args.cpus), ("--memory-mb", args.memory_mb),
                                    ("--pids-limit", args.pids_limit)):
                    if value is not None:
                        command.extend([flag, str(value)])
                if args.performance_diagnostics:
                    command.append("--performance-diagnostics")
                command.extend(["dnp-call"] if args.workflow == "dnp-call" else
                               ["workflow", "dnp-contamination"])
                command.extend(["--bamlist", str(bamlist), "--reference", str(args.reference.resolve()),
                                "--panel", str(args.panel.resolve()), "--run-name", name])
                if args.parallel:
                    command.append("--parallel")
                print(f"Benchmark: {count} samples, repetition {repeat}/{args.repeats}", flush=True)
                observation = run_case(command, runs / name, output / f"{name}.log")
                report["cases"].append({"samples": count, "repeat": repeat, **observation})
                report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                if (observation["returncode"] or observation["interrupted"]
                        or observation["status"] != "succeeded"):
                    print(f"Benchmark stopped after failure. Report: {report_path}", file=sys.stderr)
                    return 1
        print(f"Benchmark report: {report_path}")
        return 0
    except (NipatError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
