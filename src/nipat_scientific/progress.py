"""Small, optional progress events independent of performance diagnostics.

Each process/context owns one bounded JSONL file on the existing run mount.
Failure to report progress must never change a scientific result or exit code.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

INTERFACE = "nipat-progress-v1"
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024
_PHASE = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")
_SOURCE = re.compile(r"[a-f0-9]{32}-[0-9]+-[a-f0-9]{12}\Z")
_LOCK = threading.RLock()
_WRITERS = {}


def _text(value, *, nullable=False):
    return (nullable and value is None) or (isinstance(value, str) and 0 < len(value) <= 256
            and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value))


def validate_event(value):
    """Reject malformed events without trusting paths, counters or terminal text."""
    required = {"schema_version", "interface", "source_id", "sequence", "event", "workflow",
                "step_id", "phase", "sample_ids"}
    if not isinstance(value, dict) or not required <= value.keys():
        return False
    if value.keys() - required - {"completed", "total", "unit", "outcome"}:
        return False
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["interface"] != INTERFACE or not isinstance(value["source_id"], str)
            or not _SOURCE.fullmatch(value["source_id"])
            or type(value["sequence"]) is not int or value["sequence"] < 1
            or not isinstance(value["event"], str) or value["event"] not in {"start", "progress", "end"}
            or not _text(value["workflow"]) or not _text(value["step_id"], nullable=True)
            or not isinstance(value["phase"], str) or not _PHASE.fullmatch(value["phase"])
            or not isinstance(value["sample_ids"], list) or len(value["sample_ids"]) > 256
            or not all(_text(x) for x in value["sample_ids"])):
        return False
    counters = {"completed", "total", "unit"} & value.keys()
    if counters:
        if counters != {"completed", "total", "unit"}:
            return False
        if (type(value["completed"]) is not int or type(value["total"]) is not int
                or not 0 <= value["completed"] <= value["total"] <= 2**53
                or not _text(value["unit"])):
            return False
    if value["event"] == "end":
        return isinstance(value.get("outcome"), str) and value["outcome"] in {"succeeded", "failed", "cancelled"}
    return "outcome" not in value


def emit(event, phase, *, workflow=None, step_id=None, sample_ids=(),
         completed=None, total=None, unit=None, outcome=None):
    """Append a validated event, or quietly leave scientific execution untouched."""
    directory = os.environ.get("NIPAT_PROGRESS_DIR")
    if not directory:
        return
    try:
        workflow = workflow or os.environ.get("NIPAT_PROGRESS_WORKFLOW", "analysis")
        step_id = step_id or os.environ.get("NIPAT_PROGRESS_STEP_ID") or None
        if not sample_ids:
            sample_ids = json.loads(os.environ.get("NIPAT_PROGRESS_SAMPLE_IDS", "[]"))
        sample_map = json.loads(os.environ.get("NIPAT_PROGRESS_SAMPLE_MAP", "{}"))
        sample_ids = [sample_map.get(value, value) for value in sample_ids]
        token = os.environ.get("NIPAT_PROGRESS_SOURCE", "")
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            token = "0" * 32
        key = (directory, workflow, step_id, token, os.getpid())
        with _LOCK:
            writer = _WRITERS.get(key)
            if writer is None:
                # A fresh nonce when an embedding caller has not provided one.
                nonce = token if token != "0" * 32 else uuid.uuid4().hex
                suffix = hashlib.sha256(f"{workflow}:{step_id}".encode()).hexdigest()[:12]
                writer = [f"{nonce}-{os.getpid()}-{suffix}", 0, 0]
                if len(_WRITERS) >= 64:
                    _WRITERS.clear()
                _WRITERS[key] = writer
            writer[1] += 1
            document = {"schema_version": 1, "interface": INTERFACE, "source_id": writer[0],
                        "sequence": writer[1], "event": event, "workflow": workflow,
                        "step_id": step_id, "phase": phase, "sample_ids": list(sample_ids)}
            if any(x is not None for x in (completed, total, unit)):
                document.update(completed=completed, total=total, unit=unit)
            if outcome is not None:
                document["outcome"] = outcome
            if not validate_event(document):
                return
            encoded = (json.dumps(document, ensure_ascii=True, separators=(",", ":"),
                                  allow_nan=False) + "\n").encode("utf-8")
            if len(encoded) > MAX_LINE_BYTES or writer[2] + len(encoded) > MAX_FILE_BYTES:
                return
            root = Path(directory)
            if not root.is_absolute() or root.is_symlink():
                return
            root.mkdir(parents=True, exist_ok=True)
            target = root / (writer[0] + ".jsonl")
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND
                                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(descriptor, "ab") as stream:
                stream.write(encoded)
                stream.flush()
            writer[2] += len(encoded)
    except Exception:
        return


@contextmanager
def context(workflow, *, step_id=None, sample_ids=(), sample_map=None):
    """Supply a stable scope and a fresh invocation nonce to Python and R children."""
    updates = {"NIPAT_PROGRESS_WORKFLOW": workflow, "NIPAT_PROGRESS_STEP_ID": step_id or "",
               "NIPAT_PROGRESS_SAMPLE_IDS": json.dumps(list(sample_ids)),
               "NIPAT_PROGRESS_SAMPLE_MAP": json.dumps(sample_map or {}),
               "NIPAT_PROGRESS_SOURCE": uuid.uuid4().hex,
               "NIPAT_PROGRESS_R_HELPER": str(Path(__file__).with_suffix(".R"))}
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def phase(name, *, workflow=None, step_id=None, sample_ids=()):
    """Report a real boundary; caller can set outcome for a returned nonzero code."""
    scope = dict(workflow=workflow, step_id=step_id, sample_ids=sample_ids)
    state = {"outcome": "succeeded"}
    emit("start", name, **scope)
    try:
        yield state
    except (KeyboardInterrupt, SystemExit):
        state["outcome"] = "cancelled"
        raise
    except BaseException:
        state["outcome"] = "failed"
        raise
    finally:
        emit("end", name, outcome=state["outcome"], **scope)


def request_sample_ids(request):
    """Return request-owned identifiers, never infer biological relationships."""
    if not isinstance(request, dict):
        return []
    presentation = request.get("presentation")
    if isinstance(presentation, dict) and isinstance(presentation.get("samples"), dict):
        return [key for key in presentation["samples"] if _text(key)]
    if request.get("workflow") == "snp-call":
        return ["sample_0001"]
    samples = request.get("samples")
    if not isinstance(samples, list):
        return []
    result = []
    for item in samples:
        if isinstance(item, dict):
            identifier = item.get("sample_id")
            if not identifier and isinstance(item.get("name"), str):
                identifier = Path(item["name"]).stem
            if _text(identifier):
                result.append(identifier)
    return result


def step_sample_ids(step):
    inputs = step["inputs"]
    result = []
    if "sample" in inputs:
        result.append(inputs["sample"])
    for item in inputs.get("samples", []):
        result.append(item if isinstance(item, str) else item["sample"])
    for pair in inputs.get("pairs", []):
        result.extend(pair[role]["sample"] for role in ("mother", "father"))
    return list(dict.fromkeys(result))


@contextmanager
def observed_phase(name, *, workflow=None, step=None):
    """Use the same real boundary for progress and optional performance evidence."""
    from nipat_scientific.performance import phase as performance_phase
    with phase(name, workflow=workflow, step_id=step) as result, \
            performance_phase(name, workflow=workflow, step=step):
        yield result
