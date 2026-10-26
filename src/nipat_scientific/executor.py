"""Execute typed scientific plans in the image, including independent SNPcall.

The plan validator and executor support the four bundled workflows.
The executor never imports the desktop application,
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
from nipat_scientific.cpi import POPFREQ_COLUMNS, prepare_cpi
from nipat_scientific.dnp import prepare_dnp
from nipat_scientific.errors import ValidationError
from nipat_scientific.files import (
    DNP_OUTPUT_COLUMNS, require_columns, require_contamination_input,
    require_file, require_sidecar, require_snp_pileup,
)
from nipat_scientific.panels import read_dnp_list, read_position_panel, read_snp_positions
from nipat_scientific.plan import validate_plan
from nipat_scientific.snp import prepare_snp


SUPPORTED_WORKFLOWS = frozenset({"dnp-call", "snp-call", "contamination", "cpi"})
INTERFACE = "workflow-plan-execution-v1"
_NATIVE_PATH = re.compile(r"[A-Za-z0-9_./:-]+\Z")
_CPI_COLUMNS = {
    "Pair", "N_sites_mother", "N_sites_father", "Median_fetal_fraction_raw",
    "Median_fetal_fraction_percent", "Max_logCPI", "Min_logCPI",
    "Median_logCPI", "Mean_logCPI", "CPI_medianFF",
}
_SNP_COLUMNS = {
    "chr", "pos", "Reference", "Alternative", "N_Reference", "N_Alternative",
    "N_Altro", "total_count", "ratio",
}


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
        if step["workflow"] == "cpi":
            popfreq = require_file(Path(inputs["popfreq"]), "Population frequencies")
            require_columns(popfreq, POPFREQ_COLUMNS, "Invalid population frequencies")
            sources.append(popfreq)
            if inputs["cutoffs"] and any(char in str(root) for char in ",="):
                raise PlanExecutionError("execution.alias", "CPI cutoff staging requires a run path without comma or equals characters.")
            for cutoff in inputs["cutoffs"]:
                panel = require_file(Path(cutoff["path"]), "CPI cutoff panel")
                read_position_panel(panel)
                sources.append(panel)
            for pair in inputs["pairs"]:
                for role in ("mother", "father"):
                    reference = pair[role]
                    if "step" not in reference:
                        require_columns(samples[reference["sample"]], DNP_OUTPUT_COLUMNS,
                                        "Invalid imported CPI table", whitespace=True)
            continue
        panel = require_file(Path(inputs["panel"]), "Plan panel")
        sources.append(panel)
        if step["workflow"] == "snp-call":
            mode = step["parameters"]["mode"]
            read_snp_positions(panel, for_bed=mode == "bam")
            sample = samples[inputs["sample"]]
            if mode == "pileup":
                require_snp_pileup(sample)
            else:
                reference = require_file(Path(inputs["reference"]), "FASTA")
                sources.extend((reference, require_sidecar(reference, ".fai", "FASTA index").resolve()))
                if reference.suffix.lower() in {".gz", ".bgz", ".bgzf"}:
                    sources.append(require_sidecar(reference, ".gzi", "FASTA BGZF index").resolve())
                for suffix in (".bai", ".csi"):
                    for sidecar in (Path(str(sample) + suffix), sample.with_suffix(suffix)):
                        if sidecar.is_file():
                            sources.append(sidecar.resolve())
        elif step["workflow"] == "dnp-call":
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


def _cpi_bindings(step: dict) -> tuple[list[dict], list[dict]]:
    """Assign controlled aliases by typed identity, never by biological guesswork."""
    aliases = {}
    inputs, pairs = [], []
    for pair in step["inputs"]["pairs"]:
        names = {}
        for role, prefix in (("mother", "Mother"), ("father", "Father")):
            reference = pair[role]
            key = (reference.get("step"), reference["sample"])
            if key not in aliases:
                native = f"s{len(aliases) + 1:04d}"
                aliases[key] = native
                inputs.append({"source": reference.copy(), "name": f"{prefix}{native}.txt"})
            names[role] = aliases[key]
        pairs.append({
            "pair": pair["id"], "mother": pair["mother"].copy(), "father": pair["father"].copy(),
            "native_pair": f"Mother{names['mother']}-Father{names['father']}_DNPs",
            "native_selection": f"{names['mother']}:{names['father']}",
        })
    return inputs, pairs


def _resolve_table(reference: dict, samples: dict, outputs: dict) -> Path:
    return (outputs[(reference["step"], reference["sample"])] if "step" in reference
            else Path(samples[reference["sample"]]["path"]))


def _pdf_artifact(path: Path, root: Path, output_dir: Path) -> dict:
    artifact = _artifact(path, root, output_dir)
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-" or path.stat().st_size <= 5:
            raise PlanExecutionError("execution.output", f"Invalid CPI PDF: {path.name}")
    return artifact


def _collect_cpi_outputs(step: dict, request: dict, root: Path, output_dir: Path) -> dict:
    summary = output_dir / "Summary_FetalFraction_CPI.csv"
    artifact = _artifact(summary, root, output_dir)
    mode = request["cutoff_mode"]
    with summary.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        required = _CPI_COLUMNS | ({"Cutoff"} if mode != "all" else set())
        if (not required.issubset(columns) or len(columns) != len(set(columns))
                or (mode == "all" and "Cutoff" in columns)):
            raise PlanExecutionError("execution.output", "CPI summary columns do not match the requested cutoff mode.")
        rows = list(reader)
    _, bindings = _cpi_bindings(step)
    cutoffs = ([None] if mode == "all" else [str(Path(request["work_dir"]) / "DNPpanel.txt")]
               if mode == "panel" else [panel["label"] for panel in request["cutoffs"]])
    expected = {(pair["native_pair"], cutoff) for pair in bindings for cutoff in cutoffs}
    found = {}
    for number, row in enumerate(rows, 1):
        if None in row or any(value is None for value in row.values()):
            raise PlanExecutionError("execution.output", "Malformed CPI summary row.")
        key = (row["Pair"], row.get("Cutoff"))
        if key in found:
            raise PlanExecutionError("execution.output", "CPI summary contains duplicate pair/cutoff rows.")
        found[key] = number
    if set(found) != expected:
        raise PlanExecutionError("execution.output", "CPI summary does not match the declared pairs and cutoffs.")
    plots = output_dir / "plots"
    expected_plots = {"All_CPIplots.pdf", *(f"{pair['native_pair']}_CPIplot.pdf" for pair in bindings)}
    if {path.name for path in plots.glob("*.pdf")} != expected_plots:
        raise PlanExecutionError("execution.output", "CPI plots do not match the declared pair identities.")
    pairs = []
    for pair in bindings:
        pairs.append({
            "pair": pair["pair"], "mother": pair["mother"], "father": pair["father"],
            "native_pair": pair["native_pair"],
            "summary_rows": [{"row": found[(pair["native_pair"], cutoff)], "cutoff": cutoff} for cutoff in cutoffs],
            "plot": _pdf_artifact(plots / f"{pair['native_pair']}_CPIplot.pdf", root, output_dir),
        })
    return {"summary": artifact, "cpi-pairs": pairs,
            "combined-plot": _pdf_artifact(plots / "All_CPIplots.pdf", root, output_dir)}


def _collect_outputs(step: dict, request: dict, root: Path, output_dir: Path) -> dict:
    if step["workflow"] == "cpi":
        return _collect_cpi_outputs(step, request, root, output_dir)
    if step["workflow"] == "snp-call":
        path = output_dir / "SNPcall_output.txt"
        artifact = _artifact(path, root, output_dir)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            columns = reader.fieldnames or []
            if not _SNP_COLUMNS.issubset(columns) or len(columns) != len(set(columns)):
                raise PlanExecutionError("execution.output", "SNPcall result columns are missing or duplicated.")
            found = set()
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise PlanExecutionError("execution.output", "Malformed SNPcall result row.")
                try:
                    found.add((row["chr"], int(row["pos"])))
                except ValueError as exc:
                    raise PlanExecutionError("execution.output", "Invalid SNPcall result coordinate.") from exc
        expected = set(read_snp_positions(Path(request["panel"]), for_bed=request["mode"] == "bam"))
        # R outer-joins the selected panel, retaining zero-coverage loci. A
        # header-only file is therefore incomplete for every valid panel.
        if found != expected:
            raise PlanExecutionError("execution.output", "SNPcall result loci do not match the selected panel.")
        preparation = []
        if request["mode"] == "bam":
            work = Path(request["work_dir"])
            preparation = [{"kind": kind, **_artifact(work / name, root, work)}
                           for kind, name in (("regions-bed", "snp_regions.bed"), ("pileup", "pileup.txt"))]
        return {"snp-tables": [{"sample": step["inputs"]["sample"], **artifact}],
                "preparation": preparation}
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
                       "work_dir": str(work), "out_dir": str(output)}
            if step["workflow"] == "dnp-call":
                request.update({"panel": step["inputs"]["panel"],
                                "samples": [{"path": samples[identifier]["path"], "sample_id": f"sample_{number:04d}"}
                                            for number, identifier in enumerate(step["inputs"]["samples"], 1)],
                                "reference": step["inputs"]["reference"], "parallel": step["parameters"]["parallel"]})
                _atomic_json(directory / "request.json", request)
                prepared = prepare_dnp(request)
                native, cwd = prepared.native_arguments, prepared.working_dir
            elif step["workflow"] == "snp-call":
                mode = step["parameters"]["mode"]
                path = samples[step["inputs"]["sample"]]["path"]
                record["sample_mapping"] = {"sample": step["inputs"]["sample"], "mode": mode, "path": path}
                request.update({"mode": mode, "panel": step["inputs"]["panel"],
                                "bam": path if mode == "bam" else None,
                                "pileup": path if mode == "pileup" else None,
                                "reference": step["inputs"]["reference"]})
                _atomic_json(directory / "request.json", request)
                _atomic_json(root / "workflow-state.json", state)
                prepared = prepare_snp(request)
                native, cwd = prepared.native_arguments, work
                if prepared.preparation_command is not None:
                    if cancellation.signum is not None:
                        raise KeyboardInterrupt
                    record["preparation_command"] = prepared.preparation_command
                    record["preparation_log"] = f"steps/{step['id']}/preparation.log"
                    _atomic_json(root / "workflow-state.json", state)
                    print(f"Workflow step {step['id']}: samtools preparation (log: {record['preparation_log']})",
                          file=sys.stderr, flush=True)
                    code = (run_process(prepared.preparation_command, cwd, directory / "preparation.log")
                            if run_process is not None else
                            _run_process(prepared.preparation_command, cwd, directory / "preparation.log", cancellation))
                    if cancellation.signum is not None:
                        raise KeyboardInterrupt
                    if type(code) is not int or code < 0:
                        raise PlanExecutionError("execution.process", "The preparation process returned an invalid exit code.")
                    record["preparation_exit_code"] = code
                    if code:
                        record["exit_code"] = code
                        raise PlanExecutionError("execution.process",
                                                 f"{step['id']} preparation exited with code {code}; see {record['preparation_log']}.")
                    # A zero exit from samtools does not guarantee usable data.
                    # Keep its log and prevent R from consuming an empty or
                    # structurally incompatible pileup.
                    require_snp_pileup(prepared.generated_pileup)
                    record["preparation_artifacts"] = [
                        {"kind": kind, **_artifact(work / name, root, work)}
                        for kind, name in (("regions-bed", "snp_regions.bed"), ("pileup", "pileup.txt"))
                    ]
                    _atomic_json(root / "workflow-state.json", state)
            elif step["workflow"] == "contamination":
                selected = []
                for number, reference in enumerate(step["inputs"]["samples"], 1):
                    path = _resolve_table(reference, samples, outputs)
                    selected.append({"path": str(path), "name": f"table_{number:04d}.txt"})
                request["panel"] = step["inputs"]["panel"]
                request["samples"] = selected
                _atomic_json(directory / "request.json", request)
                native, cwd = prepare_contamination(request), work
            else:
                selections, pairs = _cpi_bindings(step)
                # Retain the explicit identities even when R leaves only
                # partial plots or preparation fails before any output exists.
                record["pair_mapping"] = [
                    {key: pair[key] for key in ("pair", "mother", "father", "native_pair")}
                    for pair in pairs
                ]
                request.update({
                    "samples": [{"path": str(_resolve_table(item["source"], samples, outputs)), "name": item["name"]}
                                for item in selections],
                    "pairs": ",".join(pair["native_selection"] for pair in pairs),
                    "mother_prefix": "Mother", "father_prefix": "Father",
                    "popfreq": step["inputs"]["popfreq"], "cutoffs": step["inputs"]["cutoffs"],
                    "cutoff_mode": step["parameters"]["cutoff_mode"], "err_const": step["parameters"]["err_const"],
                })
                _atomic_json(directory / "request.json", request)
                _atomic_json(root / "workflow-state.json", state)
                native, cwd = prepare_cpi(request), work
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
