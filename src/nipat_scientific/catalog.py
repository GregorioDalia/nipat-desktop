"""Read-only, source-pinned descriptions of the bundled scientific interfaces.

This module describes reviewed code; it does not set analysis parameters or
infer effective settings from imported data. The engine verifies the R sources
and bundled preparation dependencies before exposing it. Host and build-only
evidence is checked in the source checkout, since those files are not in the engine
image. Offline consultation checks the document structure without reading those
sources or executing any R workflow.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from nipat_scientific.errors import ValidationError


WORKFLOWS = ("dnp-call", "snp-call", "contamination", "cpi")
CATALOG_DIRECTORY = Path(__file__).with_name("catalog_data")
SOURCE_PATHS = {
    "dnp-call": "scientific/vendor/DNPcall/DNPcall.R",
    "snp-call": "scientific/vendor/NEWPAT/SNPcall/SNPcall.R",
    "contamination": "scientific/vendor/NEWPAT/contamination/detect_contamination.R",
    "cpi": "scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R",
}


class CatalogError(ValidationError):
    """The catalog is incomplete, malformed, or no longer matches its source."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CatalogError(message)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _translation(value: object, label: str) -> None:
    _require(isinstance(value, dict) and set(value) == {"it", "en"}
             and all(_text(text) for text in value.values()),
             f"{label}: Italian and English text are required.")


def _lines(value: object, maximum: int | None = None) -> None:
    _require(isinstance(value, list) and len(value) == 2
             and all(type(item) is int for item in value)
             and 1 <= value[0] <= value[1]
             and (maximum is None or value[1] <= maximum),
             "Catalog source line range is invalid.")


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(_text(item) for item in value)


def _evidence_source(evidence: object, identifier: str) -> None:
    _require(isinstance(evidence, dict), f"{identifier}: missing evidence.")
    path = evidence.get("path")
    _require(_text(path) and not PurePosixPath(path).is_absolute()
             and ".." not in PurePosixPath(path).parts
             and PurePosixPath(path).as_posix() == path
             and path != "." and "\\" not in path and ":" not in path,
             f"{identifier}: invalid evidence path.")
    _require(isinstance(evidence.get("sha256"), str)
             and re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"]) is not None,
             f"{identifier}: evidence SHA256 is required.")
    _lines(evidence.get("source_lines"))


def _evidence(entry: dict) -> dict:
    identifier = entry.get("id")
    evidence = entry.get("evidence")
    _evidence_source(evidence, identifier)
    dependencies = evidence.get("dependencies", [])
    _require(isinstance(dependencies, list), f"{identifier}: invalid evidence dependencies.")
    for dependency in dependencies:
        _evidence_source(dependency, identifier)
    return evidence


def verify_review_dependencies(document: dict, source_root: Path, *, require_all: bool = True) -> None:
    """Check exact bytes and cited lines for every preparation dependency.

    The default is a complete source-checkout check, including host CLI and
    preferences. An engine bundle relocates ``src/nipat_scientific`` to
    ``lib/nipat_scientific``. With ``require_all=False`` only in that layout,
    absent host-only ``src/nipat`` evidence and the build-only scientific
    Dockerfile are skipped; engine dependencies and R evidence must still exist
    and match. This is not a full checkout or build-input check.
    """
    root = source_root.resolve()
    bundled = ((root / "lib/nipat_scientific").is_dir()
               and not (root / "src/nipat_scientific").exists())
    checked: dict[Path, tuple[str, int]] = {}
    evidence_sources = []
    for entry in document["preparation_settings"]:
        evidence = _evidence(entry)
        evidence_sources.extend([evidence, *evidence.get("dependencies", [])])
    for evidence in evidence_sources:
        relative = PurePosixPath(evidence["path"])
        path = root / relative
        if bundled and relative.parts[:2] == ("src", "nipat_scientific"):
            path = root / "lib" / Path(*relative.parts[1:])
        elif (bundled and not require_all and not path.exists()
              and (relative.parts[:2] == ("src", "nipat")
                   or relative.as_posix() == "docker/scientific-runtime/Dockerfile")):
            continue
        path = path.resolve()
        _require(path.is_relative_to(root), "Catalog evidence escapes the bundle.")
        if path not in checked:
            try:
                content = path.read_bytes()
                checked[path] = (hashlib.sha256(content).hexdigest(),
                                 len(content.decode("utf-8").splitlines()))
            except (OSError, UnicodeError) as exc:
                raise CatalogError(f"Cannot read catalog evidence: {relative}") from exc
        digest, count = checked[path]
        _require(digest == evidence["sha256"],
                 f"Catalog review is stale: {relative}. Review it against the changed source.")
        _lines(evidence["source_lines"], count)


def validate_catalog(document: object, *, source_root: Path | None = None) -> None:
    """Check structure and R line coverage; optionally verify available sources.

    Source verification includes every preparation dependency in a checkout.
    An engine bundle excludes absent host/build-only evidence, as documented by
    :func:`verify_review_dependencies`.
    """
    _require(isinstance(document, dict), "Catalog must be an object.")
    _require(type(document.get("schema_version")) is int
             and document["schema_version"] == 1, "Unsupported catalog schema.")
    workflow = document.get("workflow")
    _require(isinstance(workflow, str) and workflow in WORKFLOWS, "Unknown catalog workflow.")
    source = document.get("source")
    _require(isinstance(source, dict)
             and source.get("path") == SOURCE_PATHS[workflow]
             and isinstance(source.get("sha256"), str)
             and re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) is not None
             and type(source.get("line_count")) is int and source["line_count"] > 0,
             f"{workflow}: source identity is incomplete.")
    count = source["line_count"]
    seen: set[str] = set()
    for group in ("public_parameters", "fixed_settings", "preparation_settings"):
        entries = document.get(group)
        _require(isinstance(entries, list), f"{workflow}: missing {group}.")
        for entry in entries:
            _require(isinstance(entry, dict), f"{group}: entry must be an object.")
            identifier = entry.get("id")
            _require(isinstance(identifier, str)
                     and re.fullmatch(r"[a-z][a-z0-9_]*", identifier) is not None
                     and identifier not in seen, f"{workflow}: duplicate or invalid identifier.")
            seen.add(identifier)
            _translation(entry.get("description"), identifier)
            if group == "preparation_settings":
                _require("value" in entry and _text(entry.get("origin"))
                         and _text(entry.get("applies_to")),
                         f"{identifier}: preparation origin and scope are required.")
                _evidence(entry)
                continue
            _lines(entry.get("source_lines"), count)
            if group == "fixed_settings":
                _require(isinstance(entry.get("kind"), str) and entry["kind"] in {
                    "filter", "formula", "format", "presentation", "execution", "assumption",
                } and "value" in entry, f"{identifier}: invalid fixed setting.")
                continue
            _require(_strings(entry.get("r_names")) and bool(entry["r_names"])
                     and (entry.get("position") is None or (
                         type(entry["position"]) is int and entry["position"] > 0))
                     and _text(entry.get("type")) and "default" in entry
                     and type(entry.get("required")) is bool and "unit" in entry
                     and (entry["unit"] is None or _text(entry["unit"])),
                     f"{identifier}: incomplete public parameter.")
            mapping = entry.get("nipat")
            _require(isinstance(mapping, dict) and _strings(mapping.get("cli"))
                     and _strings(mapping.get("request_fields"))
                     and isinstance(mapping.get("mapping"), str)
                     and mapping["mapping"] in {"direct", "adapted", "managed", "missing"},
                     f"{identifier}: invalid NIPAT mapping.")

    sections = document.get("audit_sections")
    _require(isinstance(sections, list) and bool(sections), "Missing source coverage.")
    expected = 1
    for section in sections:
        _require(isinstance(section, dict), "Invalid audit section.")
        _lines([section.get("start"), section.get("end")], count)
        _require(section["start"] == expected, "Source coverage has a gap or overlap.")
        _translation(section.get("summary"), "audit section")
        expected = section["end"] + 1
    _require(expected == count + 1, "Source coverage does not reach the end of the script.")

    if source_root is not None:
        root = source_root.resolve()
        path = (root / source["path"]).resolve()
        _require(path.is_relative_to(root), "Catalog source escapes the bundle.")
        try:
            content = path.read_bytes()
            actual_count = len(content.decode("utf-8").splitlines())
        except (OSError, UnicodeError) as exc:
            raise CatalogError(f"Cannot read catalog source: {source['path']}") from exc
        _require(hashlib.sha256(content).hexdigest() == source["sha256"]
                 and actual_count == count,
                 f"Catalog review is stale: {source['path']}. Review it against the changed source.")
        verify_review_dependencies(document, root, require_all=False)


def load_catalog(workflow: str | None = None, *, source_root: Path | None = None) -> dict:
    """Load fresh catalog objects; never return a shared mutable configuration."""
    if workflow is not None and workflow not in WORKFLOWS:
        raise CatalogError(f"Unknown catalog workflow: {workflow}")
    documents = {}
    for name in ((workflow,) if workflow else WORKFLOWS):
        try:
            document = json.loads((CATALOG_DIRECTORY / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise CatalogError(f"Cannot read scientific catalog: {name}") from exc
        validate_catalog(document, source_root=source_root)
        _require(document["workflow"] == name, "Catalog filename and workflow disagree.")
        documents[name] = document
    return {"schema_version": 1, "interface": "scientific-catalog-v1", "workflows": documents}
