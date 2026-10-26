"""Run a reproducible DNPcall/Contamination workload matrix on supplied BAMs.

This is an opt-in performance tool, not a default CI gate. Reports remain local
and include input paths; review them before sharing. No synthetic performance
claims are inferred when the requested number of distinct samples is absent.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nipat.errors import NipatError
from nipat.execution.options import ExecutionOptions
from nipat.execution.runner import _finish_cleanup
from nipat.execution.workflows import _select_bams


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
    reported_ram = [float(value) for value in re.findall(
        r"Peak RAM(?: usage)? \(MB\):\s*([0-9]+(?:\.[0-9]+)?)", log)]
    return {
        "argv": command, "run_dir": str(run_dir), "returncode": process.returncode,
        "status": record.get("status", "invalid_record" if record_error else "not_created"),
        "record_error": record_error, "wall_seconds": elapsed,
        "interrupted": interrupted,
        "run_files_bytes": sum(path.stat().st_size for path in run_dir.rglob("*")
                               if path.is_file() and not path.is_symlink()) if run_dir.is_dir() else 0,
        "r_reported_peak_ram_mb": max(reported_ram, default=None),
        "runtime": record.get("runtime"), "execution_options": record.get("execution_options"),
        "input_evidence": record.get("inputs", []), "command_log": str(log_path),
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
    args = parser.parse_args(argv)
    try:
        options = ExecutionOptions(args.input_hashes, args.cpus, args.memory_mb, args.pids_limit)
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
            "ram_measurement": "R-reported peak when available; not whole-container peak RAM",
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
