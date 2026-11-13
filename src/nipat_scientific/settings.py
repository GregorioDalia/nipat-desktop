"""Validated scientific parameters and readable model constants for all five modules.

Python and R read the same packaged registry. Input files are never modified.
Execution budgets are a separate contract (parallel.py / parallel.R).
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import tempfile

from nipat_scientific.errors import ValidationError


REGISTRY = Path(__file__).with_name("settings_data.json")


@lru_cache(maxsize=1)
def _registry() -> dict:
    with REGISTRY.open(encoding="utf-8") as stream:
        document = json.load(stream)
    if document.get("schema_version") != 1:
        raise ValidationError("Versione del registro dei parametri non supportata.")
    return document["workflows"]


def describe_settings(workflow: str | None = None) -> dict:
    """Return definitions, defaults, ranges, meanings and immutable constants."""
    if workflow is None:
        return deepcopy(_registry())
    if not isinstance(workflow, str) or workflow not in _registry():
        raise ValidationError(f"Modulo scientifico non riconosciuto: {workflow}")
    return deepcopy(_registry()[workflow])


def defaults(workflow: str) -> dict:
    return {name: entry["default"] for name, entry in
            describe_settings(workflow)["parameters"].items()}


def normalize_settings(workflow: str, overrides: dict | None = None) -> dict:
    """Merge explicit parameters with defaults, rejecting typos and invalid ranges."""
    definitions = describe_settings(workflow)["parameters"]
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict) or any(not isinstance(key, str) for key in overrides):
        raise ValidationError(f"{workflow}: i parametri scientifici devono essere un oggetto JSON.")
    unknown = set(overrides) - set(definitions)
    if unknown:
        raise ValidationError(f"{workflow}: parametri sconosciuti: {', '.join(sorted(unknown))}")
    values = {**defaults(workflow), **overrides}
    for name, value in values.items():
        definition = definitions[name]
        kind = definition["type"]
        valid = ((kind == "boolean" and type(value) is bool)
                 or (kind == "string" and isinstance(value, str))
                 or (kind == "integer" and type(value) is int)
                 or (kind == "number" and type(value) in (int, float)))
        if not valid:
            raise ValidationError(f"{workflow}.{name}: atteso un valore {kind}.")
        if kind in ("integer", "number"):
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValidationError(f"{workflow}.{name}: il valore deve essere finito.")
            low, high = definition.get("minimum"), definition.get("maximum")
            if low is not None and (value < low or
                                   (definition.get("exclusive_minimum") and value == low)):
                raise ValidationError(f"{workflow}.{name}: valore inferiore al limite ammesso.")
            if high is not None and value > high:
                raise ValidationError(f"{workflow}.{name}: valore superiore al limite ammesso.")
        if "choices" in definition and value not in definition["choices"]:
            raise ValidationError(f"{workflow}.{name}: scegliere fra {', '.join(definition['choices'])}.")
    if "heterozygous_min" in values:
        if not (values["homozygous_alt_max"] < values["heterozygous_min"] <=
                values["heterozygous_max"] < values["homozygous_ref_min"]):
            raise ValidationError("Soglie genotipiche sovrapposte: richiedono ALT < HET minimo <= HET massimo < REF.")
    elif "homozygous_alt_max" in values and not (
            values["homozygous_alt_max"] < values["homozygous_ref_min"]):
        raise ValidationError("La soglia omozigote ALT deve precedere quella REF.")
    if "log_cpi_lower" in values and values["log_cpi_lower"] >= values["log_cpi_upper"]:
        raise ValidationError("La guida logCPI inferiore deve essere minore della superiore.")
    if values.get("redo_baq") and not values.get("baq", True):
        raise ValidationError("redo_baq richiede baq=true.")
    return values


def settings_from_environment(workflow: str) -> dict:
    """Read a verified run's effective settings (also used by the pileup helper)."""
    path = os.environ.get("NIPAT_SCIENTIFIC_SETTINGS")
    if not path:
        return defaults(workflow)
    try:
        with Path(path).open(encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, ValueError) as exc:
        raise ValidationError("Impossibile leggere i parametri scientifici del run.") from exc
    if (not isinstance(document, dict) or document.get("schema_version") != 1
            or document.get("workflow") != workflow or not isinstance(document.get("parameters"), dict)):
        raise ValidationError("I parametri scientifici non appartengono al modulo in esecuzione.")
    return normalize_settings(workflow, document["parameters"])


@contextmanager
def settings_context(workflow: str, overrides: dict | None, workdir: Path):
    """Persist actual parameters/constants and scope their environment to this step."""
    effective = normalize_settings(workflow, overrides)
    workdir = Path(workdir)
    if workdir.is_symlink():
        raise ValidationError("La cartella dei parametri non può essere un collegamento simbolico.")
    workdir = workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "effective-scientific-settings.json"
    document = {"schema_version": 1, "workflow": workflow, "parameters": effective,
                "constants": describe_settings(workflow)["constants"]}
    descriptor, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=workdir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        try:
            # Claim a new destination atomically. Reused staging must never
            # replace scientific provenance from a previous invocation.
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink():
                raise ValidationError("Il file dei parametri non può essere un collegamento simbolico.")
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValidationError("Impossibile verificare i parametri scientifici già presenti.") from exc
            if existing != document:
                raise ValidationError("Parametri scientifici diversi già presenti nella cartella di lavoro.")
    finally:
        Path(temporary).unlink(missing_ok=True)
    values = {"NIPAT_SCIENTIFIC_SETTINGS": str(target),
              "NIPAT_SETTINGS_HELPER": str(Path(__file__).with_suffix(".R")),
              "NIPAT_SETTINGS_REGISTRY": str(REGISTRY)}
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield effective
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def samtools_options(workflow: str, overrides: dict | None = None) -> list[str]:
    """Return only deviations from samtools defaults, preserving native defaults."""
    if workflow not in {"snp-call", "dnp-call"}:
        raise ValidationError("Le opzioni pileup richiedono SNPcall o DNPcall.")
    values = normalize_settings(workflow, overrides)
    result = []
    # SNP has always explicitly disabled the samtools depth limit.
    if workflow == "snp-call" or values["max_depth"] != 8000:
        result.extend(["-d", str(values["max_depth"])])
    for key, flag, native_default in (("min_base_quality", "-Q", 13),
                                      ("min_mapping_quality", "-q", 0),
                                      ("mapping_quality_adjustment", "-C", 0),
                                      ("excluded_flags", "--ff", 1796)):
        if values[key] != native_default:
            result.extend([flag, str(values[key])])
    for key, flag, active in (("baq", "-B", False), ("redo_baq", "-E", True),
                              ("count_overlaps", "-x", True), ("include_orphans", "-A", True)):
        if values[key] is active:
            result.append(flag)
    return result
