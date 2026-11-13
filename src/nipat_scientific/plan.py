"""Validate a scientific workflow plan without reading files or executing tools.

Version 1 is a deliberately small contract for the five bundled workflows.
Dependencies arise only from typed SNP/DNP output references. It is not a shell,
template language, or generic task scheduler. The executor consumes this contract
separately; validation itself never runs an analysis.
"""

from __future__ import annotations

import heapq
import math
from pathlib import PurePosixPath
import re
import unicodedata

from nipat_scientific.errors import ValidationError
from nipat_scientific.presentation import normalize_presentation


SCHEMA_VERSION = 1
WORKFLOWS = frozenset({"dnp-call", "snp-call", "contamination", "cpi", "cpin"})
SAMPLE_KINDS = frozenset({"bam", "dnp-table", "snp-table", "snp-pileup"})
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
        sample = _identifier(value["sample"], consumer)
        if sample not in samples or samples[sample]["kind"] not in {"dnp-table", "snp-table"}:
            _fail("plan.sample_kind", f"{consumer}: expected a SNP or DNP count table.")
        return {"sample": sample}
    _object(value, {"step", "output", "sample"}, f"{consumer} table reference")
    producer = _identifier(value["step"], f"{consumer} producer")
    if producer not in step_ids:
        _fail("plan.step_missing", f"{consumer}: unknown producer {producer}.")
    if value["output"] not in {"dnp-tables", "snp-tables"}:
        _fail("plan.output_kind", f"{consumer}: only dnp-tables and snp-tables are compatible with this input.")
    sample = _identifier(value["sample"], f"{consumer} output sample")
    dependencies[consumer].add(producer)
    references.append((consumer, producer, sample, value["output"]))
    return {"step": producer, "output": value["output"], "sample": sample}


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

    Input fields are schema_version, samples and steps, with optional presentation. The return value
    is a validation report: {schema_version, plan, execution_order}. Its ``plan``
    can be validated again unchanged; the report itself is not a request.
    Scientific overrides are validated against the shared readable registry.
    """
    fields = {"schema_version", "samples", "steps"}
    _object(document, fields | ({"presentation"} if isinstance(document, dict) and "presentation" in document else set()), "Plan")
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
        inputs = step["inputs"]
        if not isinstance(step["parameters"], dict):
            _fail("plan.fields", f"{identifier}: parameters must be an object.")
        parameters = dict(step["parameters"])
        scientific_settings = parameters.pop("scientific_settings", None)
        marker_type = parameters.pop("marker_type", None)
        if marker_type is not None and (not isinstance(marker_type, str) or marker_type not in {"SNP", "DNP"}):
            _fail("plan.marker_type", f"{identifier}: marker_type must be SNP or DNP.")
        if scientific_settings is not None:
            from nipat_scientific.settings import normalize_settings
            try:
                scientific_settings = normalize_settings(workflow, scientific_settings)
            except ValidationError as exc:
                _fail("plan.parameter", str(exc))
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
        elif workflow == "cpi":
            _object(inputs, {"pairs", "popfreq", "cutoffs"}, identifier)
            _object(parameters, {"cutoff_mode"} | ({"err_const"} if "err_const" in parameters else set()), f"{identifier} parameters")
            error = parameters.get("err_const")
            try:
                valid_error = type(error) in {int, float} and math.isfinite(error) and error >= 0
            except OverflowError:
                valid_error = False
            if error is not None and not valid_error:
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
            values = {"cutoff_mode": parameters["cutoff_mode"]}
            if error is not None:
                values["err_const"] = error
        else:
            _object(inputs, {"trios", "popfreq", "markers"}, identifier)
            _object(parameters, set(), f"{identifier} parameters")
            trios, ids, combinations = [], [], set()
            role_samples = {role: set() for role in ("mother", "father", "child")}
            for trio in _list(inputs["trios"], f"{identifier} trios"):
                _object(trio, {"id", "mother", "father", "child"}, f"{identifier} trio")
                trio_id = _identifier(trio["id"], f"{identifier} trio id")
                ids.append(trio_id)
                row = {"id": trio_id}
                for role in role_samples:
                    row[role] = _table_reference(trio[role], samples, set(step_ids), identifier, dependencies, references)
                    role_samples[role].add(row[role]["sample"])
                identity = tuple(row[role]["sample"] for role in role_samples)
                if len(set(identity)) != 3:
                    _fail("plan.roles", f"{identifier}: mother, father and child must be distinct samples.")
                if identity in combinations:
                    _fail("plan.duplicate", f"{identifier}: duplicate trio.")
                combinations.add(identity)
                trios.append(row)
            _unique(ids, f"{identifier} trios")
            roles = list(role_samples.values())
            if any(roles[a] & roles[b] for a in range(3) for b in range(a + 1, 3)):
                _fail("plan.roles", f"{identifier}: inconsistent roles across trios.")
            selected = {"trios": trios, "popfreq": _path(inputs["popfreq"], f"{identifier} popfreq"),
                        "markers": _path(inputs["markers"], f"{identifier} markers") if inputs["markers"] is not None else None}
        if scientific_settings is not None:
            values["scientific_settings"] = scientific_settings
        if marker_type is not None:
            values["marker_type"] = marker_type
        normalized[identifier] = {"id": identifier, "workflow": workflow,
                                  "inputs": selected, "parameters": values}

    order = _order(dependencies)
    for consumer, producer, sample, kind in references:
        source = normalized[producer]
        expected_workflow = "snp-call" if kind == "snp-tables" else "dnp-call"
        if source["workflow"] != expected_workflow:
            _fail("plan.output_kind", f"{consumer}: {producer} does not produce {kind}.")
        produced_samples = ([source["inputs"]["sample"]] if expected_workflow == "snp-call" else source["inputs"]["samples"])
        if sample not in produced_samples:
            _fail("plan.output_sample", f"{consumer}: {producer} does not produce sample {sample}.")
    for step in normalized.values():
        if step["workflow"] in {"dnp-call", "snp-call"}:
            continue
        inp = step["inputs"]
        refs = (inp["samples"] if step["workflow"] == "contamination" else
                [family[role] for family in inp.get("pairs", inp.get("trios", []))
                 for role in (("mother", "father", "child") if step["workflow"] == "cpin" else ("mother", "father"))])
        kinds = {("SNP" if ref["output"] == "snp-tables" else "DNP") if "step" in ref else
                 ("SNP" if samples[ref["sample"]]["kind"] == "snp-table" else "DNP") for ref in refs}
        if len(kinds) != 1:
            _fail("plan.marker_type", f"{step['id']}: SNP and DNP tables must be analyzed separately.")
        inferred = kinds.pop()
        declared = step["parameters"].get("marker_type", inferred)
        if declared != inferred:
            _fail("plan.marker_type", f"{step['id']}: declared marker type differs from its inputs.")
        step["parameters"]["marker_type"] = inferred
        if step["workflow"] == "cpi" and "err_const" in step["parameters"]:
            from nipat_scientific.settings import normalize_settings
            overrides = dict(step["parameters"].get("scientific_settings", {}))
            overrides[f"err_const_{inferred.lower()}"] = step["parameters"]["err_const"]
            try:
                step["parameters"]["scientific_settings"] = normalize_settings("cpi", overrides)
            except ValidationError as exc:
                _fail("plan.parameter", str(exc))
    presentation = None
    if "presentation" in document:
        pair_ids = {family["id"] for step in normalized.values() if step["workflow"] in {"cpi", "cpin"}
                    for family in step["inputs"].get("pairs", step["inputs"].get("trios", []))}
        try:
            presentation = normalize_presentation(document["presentation"], set(samples), pair_ids)
        except ValidationError as exc:
            _fail("plan.presentation", str(exc))
    return {
        "schema_version": SCHEMA_VERSION,
        "plan": {"schema_version": SCHEMA_VERSION,
                 "samples": [samples[name] for name in sorted(samples)],
                 "steps": [normalized[name] for name in order],
                 **({"presentation": presentation} if presentation is not None else {})},
        "execution_order": order,
    }
