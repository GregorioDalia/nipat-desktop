"""Execute typed DNPcall/Contamination plans inside the scientific image.

The plan validator describes all scientific workflows. This executor deliberately
supports a smaller, explicit subset. It never imports the desktop application,
changes R sources, copies BAMs, executes shell fragments, or resumes an old run.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from nipat_scientific.contamination import prepare_contamination
from nipat_scientific.dnp import prepare_dnp
from nipat_scientific.errors import ValidationError
from nipat_scientific.files import (
    DNP_OUTPUT_COLUMNS, require_columns, require_contamination_input,
    require_file, require_sidecar,
)
from nipat_scientific.panels import read_dnp_list, read_position_panel
from nipat_scientific.plan import validate_plan


SUPPORTED_WORKFLOWS = frozenset({"dnp-call", "contamination"})
INTERFACE = "workflow-plan-execution-v1"
_NATIVE_PATH = re.compile(r"[A-Za-z0-9_./:-]+\Z")


class PlanExecutionError(ValidationError):
    """An execution/preflight failure with a stable language-independent code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encoded(document: object) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _atomic_json(path: Path, document: object) -> None:
    """Replace only our own state file, after flushing its complete new value."""
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_encoded(document))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(path.parent, os.O_DIRECTORY)
            try:
                try:
                    os.fsync(directory)
                except OSError as exc:
                    # DrvFS and other host-backed filesystems can support file
                    # fsync/atomic rename but not directory fsync. Their power-
                    # loss durability is filesystem-specific; process readers
                    # still see a complete old or new JSON document.
                    if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
                        raise
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _preflight(document: object, run_dir: Path, script_paths: dict[str, Path]) -> tuple[dict, Path, dict]:
    report = validate_plan(document)
    plan = report["plan"]
    unsupported = sorted({step["workflow"] for step in plan["steps"]} - SUPPORTED_WORKFLOWS)
    if unsupported:
        raise PlanExecutionError("execution.workflow", "Execution is not available for: " + ", ".join(unsupported))
    requested = Path(run_dir)
    if not requested.is_absolute() or requested.is_symlink() or requested.exists():
        raise PlanExecutionError("execution.destination", "Choose a new absolute run directory; existing runs cannot be reused.")
    root = requested.resolve()
    if not root.parent.is_dir():
        raise PlanExecutionError("execution.destination", "The parent of the run directory must already exist.")

    # Resolve/read every external input before claiming a new run. Scientific
    # content validation remains in the shared adapters and unchanged R scripts.
    sources = []
    samples = {}
    for item in plan["samples"]:
        path = require_file(Path(item["path"]), "Plan sample")
        if any(path.samefile(other) for other in samples.values()):
            raise PlanExecutionError("execution.sample_identity", "The same input file cannot represent two sample identities.")
        samples[item["id"]] = path
        sources.append(path)
    scripts = {}
    for workflow in {step["workflow"] for step in plan["steps"]}:
        if workflow not in script_paths:
            raise PlanExecutionError("execution.script", f"Missing bundled script for {workflow}.")
        scripts[workflow] = require_file(Path(script_paths[workflow]), "Bundled R script")

    for step in plan["steps"]:
        inputs = step["inputs"]
        panel = require_file(Path(inputs["panel"]), "Plan panel")
        sources.append(panel)
        if step["workflow"] == "dnp-call":
            read_dnp_list(panel)
            reference = require_file(Path(inputs["reference"]), "FASTA")
            if not _NATIVE_PATH.fullmatch(reference.as_posix()):
                raise PlanExecutionError("execution.alias", "DNPcall requires a safe container alias for the reference.")
            sources.extend((reference, require_sidecar(reference, ".fai", "FASTA index").resolve()))
            if reference.suffix.lower() in {".gz", ".bgz", ".bgzf"}:
                sources.append(require_sidecar(reference, ".gzi", "FASTA BGZF index").resolve())
            for number, identifier in enumerate(inputs["samples"], 1):
                path = samples[identifier]
                if path.name != f"sample_{number:04d}.bam" or not _NATIVE_PATH.fullmatch(path.as_posix()):
                    raise PlanExecutionError(
                        "execution.alias", f"{step['id']}: sample {identifier} requires a safe mounted alias "
                        f"sample_{number:04d}.bam matching its position in this DNPcall step.",
                    )
                for suffix in (".bai", ".csi"):
                    for sidecar in (Path(str(path) + suffix), path.with_suffix(suffix)):
                        if sidecar.is_file():
                            sources.append(sidecar.resolve())
        else:
            read_position_panel(panel)
            for reference in inputs["samples"]:
                if "step" not in reference:
                    require_contamination_input(samples[reference["sample"]])
    if any(path.is_relative_to(root) for path in [*sources, *scripts.values()]):
        raise PlanExecutionError("execution.overlap", "Inputs and bundled scripts must be outside the new run directory.")
    return report, root, scripts


class _Cancellation:
    def __init__(self):
        self.signum = None

    def receive(self, signum, _frame):
        self.signum = signum

    @property
    def exit_code(self):
        return 128 + (self.signum or signal.SIGINT)


def _signal_group(process: subprocess.Popen, signum: int) -> None:
    try:
        if os.name == "posix":
            # The process can exit before its descendants; address the entire
            # group even when poll() already reports the R process finished.
            os.killpg(process.pid, signum)
        elif process.poll() is None:
            process.send_signal(signum)
    except ProcessLookupError:
        pass


def _run_process(command: list[str], cwd: Path, log_path: Path, cancellation: _Cancellation) -> int:
    """Keep R/samtools in one cancellable process group and retain their output."""
    with log_path.open("xb") as output:
        process = subprocess.Popen(
            command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=os.name == "posix",
        )
        cancelled_at = None
        try:
            while True:
                if cancellation.signum is not None and cancelled_at is None:
                    cancelled_at = time.monotonic()
                    _signal_group(process, signal.SIGTERM)
                if cancelled_at is not None and time.monotonic() - cancelled_at >= 2:
                    _signal_group(process, signal.SIGKILL if os.name == "posix" else signal.SIGTERM)
                    process.wait()
                    return cancellation.exit_code
                try:
                    code = process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    continue
                if cancelled_at is not None:
                    # A quickly exiting R parent must not leave samtools or
                    # parallel workers alive after the cancelled step.
                    _signal_group(process, signal.SIGKILL if os.name == "posix" else signal.SIGTERM)
                    return cancellation.exit_code
                return code if code >= 0 else 128 - code
        except BaseException:
            _signal_group(process, signal.SIGKILL if os.name == "posix" else signal.SIGTERM)
            process.wait()
            raise


def _artifact(path: Path, root: Path, output_dir: Path) -> dict:
    resolved_output = output_dir.resolve()
    if (path.is_symlink() or not path.is_file() or not resolved_output.is_relative_to(root.resolve())
            or not path.resolve().is_relative_to(resolved_output)):
        raise PlanExecutionError("execution.output", f"Expected output is missing or outside its directory: {path.name}")
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}


def _output_columns(path: Path, columns: set[str]) -> None:
    try:
        require_columns(path, columns, "Invalid scientific result")
    except ValidationError as exc:
        raise PlanExecutionError("execution.output", str(exc)) from exc


def _collect_outputs(step: dict, request: dict, root: Path, output_dir: Path) -> dict:
    if step["workflow"] == "dnp-call":
        directory = output_dir / "individual_outputs"
        expected = {f"full_output_sample_{number:04d}.txt" for number in range(1, len(request["samples"]) + 1)}
        actual = {path.name for path in directory.glob("full_output_*.txt")}
        if expected != actual:
            raise PlanExecutionError("execution.output", f"{step['id']}: DNP tables do not match the declared sample identities.")
        tables = []
        for number, identifier in enumerate(step["inputs"]["samples"], 1):
            name = f"sample_{number:04d}"
            path = directory / f"full_output_{name}.txt"
            artifact = _artifact(path, root, output_dir)
            _output_columns(path, DNP_OUTPUT_COLUMNS)
            tables.append({"sample": identifier, "native_name": name, **artifact})
        return {"dnp-tables": tables}

    summary = output_dir / "contamination_summary.txt"
    artifact = _artifact(summary, root, output_dir)
    _output_columns(summary, {"individuo", "informative_DNPs", "mean_contamination", "sd_contamination"})
    with summary.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    expected_names = [Path(sample["name"]).stem for sample in request["samples"]]
    if sorted(row["individuo"] for row in rows) != sorted(expected_names):
        raise PlanExecutionError("execution.output", "Contamination summary does not match the selected sample identities.")
    tables = []
    for reference, name in zip(step["inputs"]["samples"], expected_names, strict=True):
        path = output_dir / f"contamination_{name}.txt"
        table_artifact = _artifact(path, root, output_dir)
        _output_columns(path, {"chr", "pos1", "pos2", "contamination"})
        tables.append({"sample": reference["sample"], "source": reference.copy(),
                       "native_name": name, **table_artifact})
    return {"summary": artifact, "contamination-tables": tables}


def execute_plan(document: object, *, run_dir: Path, script_paths: dict[str, Path], run_process=None) -> dict:
    """Run a fresh plan sequentially; return persisted status, never hide failure.

    ``run_process`` is an optional embedding/testing hook taking command, cwd and
    log_path; production uses a cancellable subprocess group. Unsupported plans,
    invalid external inputs and unsuitable aliases fail before creating a run.
    Once claimed, the directory remains diagnostic evidence even after failure.
    """
    validated, root, scripts = _preflight(document, run_dir, script_paths)
    plan = validated["plan"]
    samples = {sample["id"]: sample for sample in plan["samples"]}
    state = {
        "schema_version": 1, "interface": INTERFACE, "status": "running", "exit_code": None,
        "started_utc": _utc(), "finished_utc": None, "error": None,
        "plan_sha256": hashlib.sha256(_encoded(plan)).hexdigest(),
        "execution_order": validated["execution_order"],
        "steps": [{
            "id": step["id"], "workflow": step["workflow"], "status": "pending", "exit_code": None,
            "started_utc": None, "finished_utc": None, "error": None, "artifacts": {},
            "work_dir": f"steps/{step['id']}/work", "output_dir": f"steps/{step['id']}/output",
            "log": f"steps/{step['id']}/command.log", "request": f"steps/{step['id']}/request.json",
            "script_sha256": _sha256(scripts[step["workflow"]]),
        } for step in plan["steps"]],
    }
    cancellation = _Cancellation()
    previous = {}
    outputs = {}
    active = None
    # mkdir is the exclusive ownership operation; a concurrent invocation cannot
    # reuse a directory created after preflight.
    try:
        root.mkdir()
    except FileExistsError as exc:
        raise PlanExecutionError("execution.destination", "The run directory was already claimed.") from exc
    _atomic_json(root / "plan.json", plan)
    _atomic_json(root / "workflow-state.json", state)
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, cancellation.receive)
        for step, record in zip(plan["steps"], state["steps"], strict=True):
            if cancellation.signum is not None:
                raise KeyboardInterrupt
            active = record
            record["status"], record["started_utc"] = "running", _utc()
            _atomic_json(root / "workflow-state.json", state)
            directory = root / "steps" / step["id"]
            directory.mkdir(parents=True)
            work, output = directory / "work", directory / "output"
            request = {"schema_version": 1, "workflow": step["workflow"],
                       "panel": step["inputs"]["panel"], "work_dir": str(work), "out_dir": str(output)}
            if step["workflow"] == "dnp-call":
                request.update({"samples": [{"path": samples[identifier]["path"], "sample_id": f"sample_{number:04d}"}
                                            for number, identifier in enumerate(step["inputs"]["samples"], 1)],
                                "reference": step["inputs"]["reference"], "parallel": step["parameters"]["parallel"]})
                _atomic_json(directory / "request.json", request)
                prepared = prepare_dnp(request)
                native, cwd = prepared.native_arguments, prepared.working_dir
            else:
                selected = []
                for number, reference in enumerate(step["inputs"]["samples"], 1):
                    path = (outputs[(reference["step"], reference["sample"])] if "step" in reference
                            else Path(samples[reference["sample"]]["path"]))
                    selected.append({"path": str(path), "name": f"table_{number:04d}.txt"})
                request["samples"] = selected
                _atomic_json(directory / "request.json", request)
                native, cwd = prepare_contamination(request), work
            if cancellation.signum is not None:
                raise KeyboardInterrupt
            command = ["Rscript", str(scripts[step["workflow"]]), *native]
            record["command"] = command
            _atomic_json(root / "workflow-state.json", state)
            print(f"Workflow step {step['id']}: {step['workflow']} (log: {record['log']})", file=sys.stderr, flush=True)
            code = (run_process(command, cwd, directory / "command.log") if run_process is not None
                    else _run_process(command, cwd, directory / "command.log", cancellation))
            if cancellation.signum is not None:
                raise KeyboardInterrupt
            if type(code) is not int or code < 0:
                raise PlanExecutionError("execution.process", "The scientific process returned an invalid exit code.")
            record["exit_code"] = code
            if code:
                raise PlanExecutionError("execution.process", f"{step['id']} exited with code {code}; see {record['log']}.")
            artifacts = _collect_outputs(step, request, root, output)
            if cancellation.signum is not None:
                raise KeyboardInterrupt
            record.update(status="succeeded", artifacts=artifacts, finished_utc=_utc())
            if step["workflow"] == "dnp-call":
                for artifact in artifacts["dnp-tables"]:
                    outputs[(step["id"], artifact["sample"])] = root / artifact["path"]
            _atomic_json(root / "workflow-state.json", state)
            active = None
        if cancellation.signum is not None:
            raise KeyboardInterrupt
        state.update(status="succeeded", exit_code=0)
    except KeyboardInterrupt:
        state.update(status="cancelled", exit_code=cancellation.exit_code,
                     error={"code": "execution.cancelled", "message": "Workflow execution was cancelled."})
        if active is not None:
            active.update(status="cancelled", exit_code=state["exit_code"], error=state["error"], finished_utc=_utc())
    except (ValidationError, OSError, ValueError) as exc:
        code = getattr(exc, "code", "execution.input" if isinstance(exc, ValidationError) else "execution.io")
        state.update(status="failed", exit_code=(active or {}).get("exit_code") or 2,
                     error={"code": code, "message": str(exc)})
        if active is not None:
            active.update(status="failed", exit_code=state["exit_code"], error=state["error"], finished_utc=_utc())
    except Exception as exc:
        # An unexpected preparation/embedding error is still a failed run. Do
        # not leave an apparently running or successful record behind it.
        state.update(status="failed", exit_code=2,
                     error={"code": "execution.internal", "message": f"{type(exc).__name__}: {exc}"})
        if active is not None:
            active.update(status="failed", exit_code=2, error=state["error"], finished_utc=_utc())
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if state["status"] in {"failed", "cancelled"}:
            for record in state["steps"]:
                if record["status"] == "pending":
                    record.update(status="blocked", finished_utc=_utc(),
                                  error={"code": "execution.stopped", "message": "The plan stops after a failed or cancelled step."})
        state["finished_utc"] = _utc()
        _atomic_json(root / "workflow-state.json", state)
    return state
