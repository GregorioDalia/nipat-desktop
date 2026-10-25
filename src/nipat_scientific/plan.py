"""Validate a scientific workflow plan without reading files or executing tools.

Version 1 is a deliberately small contract for the four bundled workflows.
Dependencies arise only from typed DNP output references. It is not a shell,
template language, or generic task scheduler. Execution is a separate increment.
"""

from __future__ import annotations

import heapq
import math
from pathlib import PurePosixPath
import re
import unicodedata

from nipat_scientific.errors import ValidationError


SCHEMA_VERSION = 1
WORKFLOWS = frozenset({"dnp-call", "snp-call", "contamination", "cpi"})
SAMPLE_KINDS = frozenset({"bam", "dnp-table", "snp-pileup"})
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


class PlanValidationError(ValidationError):
    """A format/relationship error with a stable, language-independent code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str):
    raise PlanValidationError(code, message)


def _object(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("plan.fields", f"{label}: expected exactly {', '.join(sorted(fields))}.")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        _fail("plan.identifier", f"{label}: use 1–64 ASCII letters, digits, '-' or '_', starting with a letter.")
    return value


def _path(value: object, label: str) -> str:
    # These are container paths after host-side mounting, not Windows paths.
    # No resolve(), stat(), expansion, interpolation or filesystem access.
    if not isinstance(value, str) or not value or "\\" in value or any(
        unicodedata.category(char) == "Cc" for char in value
    ):
        _fail("plan.path", f"{label}: invalid container path.")
    path = PurePosixPath(value)
    if not path.is_absolute() or value.startswith("//") or any(
        part in {"", ".", ".."} for part in value.split("/")[1:]
    ):
        _fail("plan.path", f"{label}: use an absolute POSIX file path without '.' or '..' components.")
    return value


def _list(value: object, label: str, *, nonempty: bool = True) -> list:
    if not isinstance(value, list) or (nonempty and not value):
        _fail("plan.list", f"{label}: expected {'a nonempty' if nonempty else 'a'} list.")
    return value


def _unique(items: list[str], label: str):
    if len(items) != len({item.casefold() for item in items}):
        _fail("plan.duplicate", f"{label}: duplicate or case-ambiguous identifier.")


def _sample(value: object, samples: dict, expected: str, label: str) -> str:
    identifier = _identifier(value, label)
    if identifier not in samples:
        _fail("plan.sample_missing", f"{label}: unknown sample {identifier}.")
    if samples[identifier]["kind"] != expected:
        _fail("plan.sample_kind", f"{label}: expected {expected}, got {samples[identifier]['kind']}.")
    return identifier


def _table_reference(value: object, samples: dict, step_ids: set[str],
                     consumer: str, dependencies: dict, references: list) -> dict:
    if not isinstance(value, dict):
        _fail("plan.fields", f"{consumer}: expected a table reference object.")
    if set(value) == {"sample"}:
        sample = _sample(value["sample"], samples, "dnp-table", consumer)
        return {"sample": sample}
    _object(value, {"step", "output", "sample"}, f"{consumer} table reference")
    producer = _identifier(value["step"], f"{consumer} producer")
    if producer not in step_ids:
        _fail("plan.step_missing", f"{consumer}: unknown producer {producer}.")
    if value["output"] != "dnp-tables":
        _fail("plan.output_kind", f"{consumer}: only dnp-tables are compatible with this input.")
    sample = _identifier(value["sample"], f"{consumer} output sample")
    dependencies[consumer].add(producer)
    references.append((consumer, producer, sample))
    return {"step": producer, "output": "dnp-tables", "sample": sample}


def _reference_key(reference: dict) -> tuple:
    return (reference.get("step"), reference["sample"])


def _cutoffs(value: object, mode: object, label: str) -> list[dict]:
    if not isinstance(mode, str) or mode not in {"all", "panel", "named"}:
        _fail("plan.cutoff_mode", f"{label}: expected all, panel or named.")
    cutoffs = _list(value, f"{label} cutoffs", nonempty=False)
    if (mode == "all" and cutoffs) or (mode == "panel" and len(cutoffs) != 1) or (
        mode == "named" and not cutoffs
    ):
        _fail("plan.cutoff_mode", f"{label}: cutoff list does not match its mode.")
    result = []
    labels = set()
    for entry in cutoffs:
        _object(entry, {"label", "path"}, f"{label} cutoff")
        name = entry["label"]
        if not isinstance(name, str) or name != name.strip() or (
            mode == "panel" and name != ""
        ) or (mode == "named" and not name) or any(
            char in ",=" or unicodedata.category(char) == "Cc" for char in name
        ):
            _fail("plan.cutoff_label", f"{label}: invalid cutoff label.")
        if name in labels:
            _fail("plan.duplicate", f"{label}: duplicate cutoff label {name}.")
        labels.add(name)
        result.append({"label": name, "path": _path(entry["path"], f"{label} cutoff")})
    return result


def _order(dependencies: dict[str, set[str]]) -> list[str]:
    remaining = {step: set(parents) for step, parents in dependencies.items()}
    ready = [step for step, parents in remaining.items() if not parents]
    heapq.heapify(ready)
    order = []
    while ready:
        step = heapq.heappop(ready)
        order.append(step)
        for child in sorted(remaining):
            if step in remaining[child]:
                remaining[child].remove(step)
                if not remaining[child]:
                    heapq.heappush(ready, child)
    if len(order) != len(remaining):
        _fail("plan.cycle", "Output references contain a dependency cycle.")
    return order


def validate_plan(document: object) -> dict:
    """Return a canonical plan and derived order, never an execution result.

    Input fields are exactly schema_version, samples and steps. The return value
    is a validation report: {schema_version, plan, execution_order}. Its ``plan``
    can be validated again unchanged; the report itself is not a request.
    Every scientific parameter supported by this contract must be explicit.
    """
    _object(document, {"schema_version", "samples", "steps"}, "Plan")
    if type(document["schema_version"]) is not int or document["schema_version"] != SCHEMA_VERSION:
        _fail("plan.schema", "Unsupported plan schema_version.")
    samples = {}
    paths = set()
    for entry in _list(document["samples"], "Samples"):
        _object(entry, {"id", "kind", "path"}, "Sample")
        identifier = _identifier(entry["id"], "Sample id")
        if identifier.casefold() in {sample.casefold() for sample in samples}:
            _fail("plan.duplicate", f"Duplicate or case-ambiguous sample id {identifier}.")
        kind = entry["kind"]
        if not isinstance(kind, str) or kind not in SAMPLE_KINDS:
            _fail("plan.sample_kind", f"{identifier}: unsupported sample kind.")
        path = _path(entry["path"], f"Sample {identifier}")
        if path in paths:
            _fail("plan.duplicate", "One input path cannot define two sample identities.")
        paths.add(path)
        samples[identifier] = {"id": identifier, "kind": kind, "path": path}

    raw_steps = _list(document["steps"], "Steps")
    step_ids = []
    for step in raw_steps:
        _object(step, {"id", "workflow", "inputs", "parameters"}, "Step")
        step_ids.append(_identifier(step["id"], "Step id"))
    _unique(step_ids, "Steps")
    dependencies = {step: set() for step in step_ids}
    references = []
    normalized = {}
    for step in raw_steps:
        identifier, workflow = step["id"], step["workflow"]
        if not isinstance(workflow, str) or workflow not in WORKFLOWS:
            _fail("plan.workflow", f"{identifier}: unknown workflow.")
        inputs, parameters = step["inputs"], step["parameters"]
        selected = {}
        values = {}
        if workflow == "dnp-call":
            _object(inputs, {"samples", "reference", "panel"}, identifier)
            _object(parameters, {"parallel"}, f"{identifier} parameters")
            if type(parameters["parallel"]) is not bool:
                _fail("plan.parameter", f"{identifier}: parallel must be boolean.")
            selected_samples = [
                _sample(sample, samples, "bam", identifier)
                for sample in _list(inputs["samples"], f"{identifier} samples")
            ]
            _unique(selected_samples, f"{identifier} samples")
            selected = {"samples": selected_samples,
                        "reference": _path(inputs["reference"], f"{identifier} reference"),
                        "panel": _path(inputs["panel"], f"{identifier} panel")}
            values = {"parallel": parameters["parallel"]}
        elif workflow == "snp-call":
            _object(inputs, {"sample", "reference", "panel"}, identifier)
            _object(parameters, {"mode"}, f"{identifier} parameters")
            mode = parameters["mode"]
            if not isinstance(mode, str) or mode not in {"bam", "pileup"}:
                _fail("plan.parameter", f"{identifier}: SNP mode must be bam or pileup.")
            sample = _sample(inputs["sample"], samples,
                             "bam" if mode == "bam" else "snp-pileup", identifier)
            if mode == "pileup" and inputs["reference"] is not None:
                _fail("plan.parameter", f"{identifier}: imported pileup requires reference=null.")
            reference = _path(inputs["reference"], f"{identifier} reference") if mode == "bam" else None
            selected = {"sample": sample, "reference": reference,
                        "panel": _path(inputs["panel"], f"{identifier} panel")}
            values = {"mode": mode}
        elif workflow == "contamination":
            _object(inputs, {"samples", "panel"}, identifier)
            _object(parameters, set(), f"{identifier} parameters")
            tables = [_table_reference(item, samples, set(step_ids), identifier,
                                       dependencies, references)
                      for item in _list(inputs["samples"], f"{identifier} samples")]
            if len(tables) != len({_reference_key(table) for table in tables}):
                _fail("plan.duplicate", f"{identifier}: duplicate input table.")
            selected = {"samples": tables, "panel": _path(inputs["panel"], f"{identifier} panel")}
        else:
            _object(inputs, {"pairs", "popfreq", "cutoffs"}, identifier)
            _object(parameters, {"err_const", "cutoff_mode"}, f"{identifier} parameters")
            error = parameters["err_const"]
            try:
                valid_error = type(error) in {int, float} and math.isfinite(error) and error >= 0
            except OverflowError:
                valid_error = False
            if not valid_error:
                _fail("plan.parameter", f"{identifier}: err_const must be finite and nonnegative.")
            pairs, pair_ids, pair_keys, mothers, fathers = [], [], set(), set(), set()
            for pair in _list(inputs["pairs"], f"{identifier} pairs"):
                _object(pair, {"id", "mother", "father"}, f"{identifier} pair")
                pair_id = _identifier(pair["id"], f"{identifier} pair id")
                pair_ids.append(pair_id)
                mother = _table_reference(pair["mother"], samples, set(step_ids), identifier,
                                          dependencies, references)
                father = _table_reference(pair["father"], samples, set(step_ids), identifier,
                                          dependencies, references)
                # The registry identity survives separate DNP runs/panels.
                # Different producers cannot turn the same sample into two roles.
                mother_key, father_key = mother["sample"], father["sample"]
                if mother_key == father_key:
                    _fail("plan.roles", f"{identifier}: one table cannot be both mother cfDNA and father.")
                if (mother_key, father_key) in pair_keys:
                    _fail("plan.duplicate", f"{identifier}: duplicate mother/father pair.")
                pair_keys.add((mother_key, father_key))
                mothers.add(mother_key)
                fathers.add(father_key)
                pairs.append({"id": pair_id, "mother": mother, "father": father})
            _unique(pair_ids, f"{identifier} pairs")
            if mothers & fathers:
                _fail("plan.roles", f"{identifier}: inconsistent mother cfDNA/father roles across pairs.")
            selected = {"pairs": pairs, "popfreq": _path(inputs["popfreq"], f"{identifier} popfreq"),
                        "cutoffs": _cutoffs(inputs["cutoffs"], parameters["cutoff_mode"], identifier)}
            values = {"err_const": error, "cutoff_mode": parameters["cutoff_mode"]}
        normalized[identifier] = {"id": identifier, "workflow": workflow,
                                  "inputs": selected, "parameters": values}

    order = _order(dependencies)
    for consumer, producer, sample in references:
        source = normalized[producer]
        if source["workflow"] != "dnp-call":
            _fail("plan.output_kind", f"{consumer}: {producer} does not produce dnp-tables.")
        if sample not in source["inputs"]["samples"]:
            _fail("plan.output_sample", f"{consumer}: {producer} does not produce sample {sample}.")
    return {
        "schema_version": SCHEMA_VERSION,
        "plan": {"schema_version": SCHEMA_VERSION,
                 "samples": [samples[name] for name in sorted(samples)],
                 "steps": [normalized[name] for name in order]},
        "execution_order": order,
    }
