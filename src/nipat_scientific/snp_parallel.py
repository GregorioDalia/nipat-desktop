"""Bound independent SNP samples to the shared R budget, with isolated workers.

Only the coordinator writes workflow-state.json. Each fresh Python worker owns
one step and one process group, including its R and samtools descendants.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from nipat_scientific.errors import PlanExecutionError
from nipat_scientific.parallel import THREAD_LIMITS

_STARTED = time.monotonic()
_STATE_READ_ATTEMPTS = 20
_STATE_READ_DELAY = 0.05

def _utc():
    return datetime.now(timezone.utc).isoformat()


def _event(directory, event, budget, coordinator, index=None, outcome=None):
    payload = {"schema_version": 1, "interface": "nipat-parallel-v1", "event": event,
               "label": "snp-samples", "coordinator_pid": coordinator, "pid": os.getpid(),
               "task_index": index, "outcome": outcome, "observed_at_unix": time.time(),
               "elapsed_seconds": time.monotonic() - _STARTED, **budget}
    with (directory / f"worker-{os.getpid()}.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, allow_nan=False, separators=(",", ":")) + "\n")


def _query_budget(tasks, directory, cancellation):
    # R remains the single authority for CPU, memory, cgroups and explicit caps.
    from nipat_scientific.executor import _run_process

    expression = ('a <- commandArgs(TRUE); source(a[[1]]); '
                  'cat(jsonlite::toJSON(nipat_parallel_budget(as.integer(a[[2]])), '
                  'auto_unbox=TRUE, null="null", digits=NA))')
    target = directory / "budget.json"
    code = _run_process(["Rscript", "-e", expression, str(Path(__file__).with_name("parallel.R")), str(tasks)],
                        directory, target, cancellation)
    if cancellation.signum is not None:
        raise KeyboardInterrupt
    if code:
        raise PlanExecutionError("execution.parallel_budget", "Cannot determine the shared SNP process budget; see parallel/snp/budget.json.")
    try:
        budget = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise PlanExecutionError("execution.parallel_budget", "The R process budget is invalid.") from exc
    if (not isinstance(budget, dict) or type(budget.get("workers")) is not int
            or not 1 <= budget["workers"] <= tasks or budget.get("tasks") != tasks):
        raise PlanExecutionError("execution.parallel_budget", "The R process budget is inconsistent with the batch.")
    return budget


def _kill_group(process, signum):
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin can retain an exited group's zombies and return EPERM when
        # no signalable members remain. Never hide denial for a live worker
        # or on platforms where this is not the exited-group convention.
        if sys.platform != "darwin" or process.poll() is None:
            raise


def _stop_workers(active):
    # Python receives SIGTERM as cancellation while R/samtools receive it in
    # their inherited group. SIGKILL also reaches any stubborn grandchildren.
    for process, _record, _path, _log in active.values():
        _kill_group(process, signal.SIGTERM)
    deadline = time.monotonic() + 3
    while any(item[0].poll() is None for item in active.values()) and time.monotonic() < deadline:
        time.sleep(0.05)
    for process, _record, _path, log in active.values():
        _kill_group(process, signal.SIGKILL)
        process.wait()
        log.close()


def _merge_record(record, path, *, attempts=_STATE_READ_ATTEMPTS):
    """Read a stopped worker's final record, without accepting a stale snapshot.

    Host-backed mounts may briefly delay visibility of the last replacement.
    Retry only read/decoding failures, with at most 0.95 seconds of delay.
    Identity errors are permanent and must never be merged or retried.
    """
    for attempt in range(attempts):
        try:
            updated = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, ValueError) as exc:
            if attempt + 1 == attempts:
                raise PlanExecutionError(
                    "execution.worker_state",
                    f"Cannot read completed SNP step state {path.name} after {attempts} attempt(s): "
                    f"{type(exc).__name__}: {exc}",
                ) from exc
            time.sleep(_STATE_READ_DELAY)
    if (not isinstance(updated, dict) or updated.get("id") != record["id"]
            or updated.get("workflow") != "snp-call"
            or updated.get("script_sha256") != record["script_sha256"]):
        raise PlanExecutionError("execution.worker_state", f"SNP step state {path.name} has a different identity.")
    record.clear()
    record.update(updated)


def execute_independent_snp_steps(plan, state, root, scripts, cancellation, *, atomic_json):
    """Run all ready SNP callers in a mixed plan within the global budget.

    Only the coordinator writes the global state. Fresh worker interpreters
    import the production step runner instead of serializing Python state.
    """
    records = {record["id"]: record for record in state["steps"]}
    steps = [step for step in plan["steps"] if step["workflow"] == "snp-call" and records[step["id"]]["status"] == "pending"]
    if (os.name != "posix" or len(steps) < 2
            or os.environ.get("NIPAT_EXECUTION_MODE", "auto") == "serial"
            or os.environ.get("NIPAT_MAX_WORKERS") == "1"
            or os.environ.get("NIPAT_PARALLEL_CHILD") == "1"):
        return False
    if cancellation.signum is not None:
        raise KeyboardInterrupt
    directory = root / "parallel" / "snp"
    directory.mkdir(parents=True)
    budget = _query_budget(len(steps), directory, cancellation)
    state["snp_parallel"] = {"interface": "nipat-parallel-v1", **budget,
                             "diagnostics": "parallel/snp"}
    _event(directory, "plan", budget, os.getpid())
    atomic_json(root / "workflow-state.json", state)
    if budget["workers"] == 1:
        return False
    environment = {**os.environ, **THREAD_LIMITS, "NIPAT_PARALLEL_CHILD": "1", "NIPAT_MAX_WORKERS": "1"}
    module_root = str(Path(__file__).resolve().parent.parent)
    environment["PYTHONPATH"] = module_root + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    active = {}
    next_index = 0
    try:
        while next_index < len(steps) or active:
            if cancellation.signum is not None:
                raise KeyboardInterrupt
            changed = False
            # Inspect all completed jobs before adding work: a failed sample
            # must not cause a fresh sample to start in the same polling cycle.
            for identifier, (process, record, record_path, log) in list(active.items()):
                code = process.poll()
                if code is None:
                    continue
                process.wait()
                # Intermediate states are worker-owned and may be replaced on
                # Windows/WSL host mounts. Progress already uses its own events;
                # only read the final state once its writer has exited.
                if code:
                    state["exit_code"] = code if code > 0 else 128 - code
                _merge_record(record, record_path)
                changed = True
                log.close()
                del active[identifier]
                if code or record.get("status") != "succeeded":
                    _kill_group(process, signal.SIGKILL)
                    if record.get("status") not in {"failed", "cancelled"}:
                        record.update(status="failed", exit_code=code if code > 0 else 2, finished_utc=_utc(),
                                      error={"code": "execution.worker", "message": "SNP worker exited without a successful result."})
                    state["exit_code"] = record.get("exit_code") or 2
                    atomic_json(root / "workflow-state.json", state)
                    raise PlanExecutionError("execution.process", f"{identifier}: isolated SNP worker failed; see parallel/snp/worker-{identifier}.log.")
            while next_index < len(steps) and len(active) < budget["workers"]:
                if cancellation.signum is not None:
                    raise KeyboardInterrupt
                step = steps[next_index]
                record = records[step["id"]]
                identifier = step["id"]
                job = directory / f"job-{identifier}.json"
                record_path = directory / f"state-{identifier}.json"
                atomic_json(job, {"schema_version": 1, "root": str(root), "step_id": identifier,
                                  "record": record, "scripts": {key: str(value) for key, value in scripts.items()},
                                  "budget": budget, "coordinator_pid": os.getpid(), "task_index": next_index + 1})
                log = (directory / f"worker-{identifier}.log").open("xb")
                try:
                    process = subprocess.Popen([sys.executable, "-m", "nipat_scientific.snp_parallel", "--worker", str(job)],
                                               cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                except BaseException:
                    log.close()
                    raise
                active[identifier] = (process, record, record_path, log)
                record.update(status="running", started_utc=_utc())
                changed = True
                next_index += 1
            if changed:
                atomic_json(root / "workflow-state.json", state)
            if active:
                time.sleep(0.05)
        return True
    finally:
        _stop_workers(active)
        for _process, record, record_path, _log in active.values():
            try:
                _merge_record(record, record_path, attempts=1)
            except PlanExecutionError as exc:
                # Keep the primary failure/cancellation and still finalize all
                # siblings if a killed worker could not commit a readable state.
                record["state_read_error"] = {"code": exc.code, "message": str(exc)}
            if record.get("status") in {"pending", "running"}:
                record.update(status="cancelled", exit_code=cancellation.exit_code, finished_utc=_utc(),
                              error={"code": "execution.stopped", "message": "Stopped with the SNP batch."})
        atomic_json(root / "workflow-state.json", state)


def _worker_process(command, cwd, log_path, cancellation):
    """Keep every command in the worker's group, which its coordinator owns."""
    with log_path.open("xb") as output:
        process = subprocess.Popen(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=False)
        try:
            while True:
                if cancellation.signum is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    return cancellation.exit_code
                try:
                    code = process.wait(timeout=0.05)
                    return code if code >= 0 else 128 - code
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            process.kill()
            process.wait()
            raise


def _worker(job_path):
    from nipat_scientific.executor import _atomic_json, _Cancellation, _execute_step

    job = json.loads(job_path.read_text(encoding="utf-8"))
    root = Path(job["root"])
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    step = next(item for item in plan["steps"] if item["id"] == job["step_id"])
    record = job["record"]
    state_path = job_path.parent / f"state-{step['id']}.json"
    cancellation = _Cancellation()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, cancellation.receive)
    os.environ.update({**THREAD_LIMITS, "NIPAT_PARALLEL_CHILD": "1", "NIPAT_MAX_WORKERS": "1"})
    _event(job_path.parent, "task-start", job["budget"], job["coordinator_pid"], job["task_index"])
    try:
        _execute_step(plan, step, record, root, {key: Path(value) for key, value in job["scripts"].items()},
                      {sample["id"]: sample for sample in plan["samples"]}, {}, cancellation,
                      lambda command, cwd, log: _worker_process(command, cwd, log, cancellation),
                      lambda: _atomic_json(state_path, record))
    except KeyboardInterrupt:
        record.update(status="cancelled", exit_code=cancellation.exit_code, finished_utc=_utc(),
                      error={"code": "execution.cancelled", "message": "SNP worker was cancelled."})
    except Exception as exc:
        record.update(status="failed", exit_code=record.get("exit_code") or 2, finished_utc=_utc(),
                      error={"code": getattr(exc, "code", "execution.worker"), "message": str(exc)})
    finally:
        _atomic_json(state_path, record)
        _event(job_path.parent, "task-end", job["budget"], job["coordinator_pid"], job["task_index"], record["status"])
    return 0 if record["status"] == "succeeded" else record.get("exit_code") or 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", required=True, type=Path)
    return _worker(parser.parse_args().worker)


if __name__ == "__main__":
    raise SystemExit(main())
