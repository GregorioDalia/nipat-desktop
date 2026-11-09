"""Validate Authenticode observations without claiming Smart App Control acceptance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re


EXTENSIONS = {".exe", ".dll", ".pyd", ".ps1", ".psm1"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
# Derived from the exact checksummed CPython archive pinned by
# scripts/distribution_support.py. This lets publication verify every archived
# member offline, rather than trusting a potentially truncated report list.
PYTHON_INPUT = json.loads(Path(__file__).with_name("windows-python-trust-input.json").read_text())


def requires_windows_trust(version: str) -> bool:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(?:a|b|rc)\d+)?", version)
    if match is None:
        raise ValueError("Invalid version for Windows trust inventory")
    return tuple(map(int, match.groups())) >= (0, 8, 20)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Windows trust inventory: {message}")


def _hash(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _safe_path(value: object) -> bool:
    return (isinstance(value, str) and bool(value) and "\\" not in value
            and ":" not in value and not value.startswith("/")
            and all(part not in {"", ".", ".."} for part in value.split("/")))


def verify(report_path: Path, manifest: dict, installer_sha256: str,
           inventory_bytes: bytes) -> dict:
    """Bind CI signature observations to final setup and exact staged inventory.

    These are Windows observations, not a portable re-verification of Windows'
    certificate chain. Archive member observations are bound to the inventoried
    embedded ZIP; the runner inspects every executable member without executing it.
    """
    _require(report_path.is_file() and not report_path.is_symlink(), "missing report")
    raw = report_path.read_bytes()
    _require(0 < len(raw) <= 2 * 1024 * 1024, "invalid report size")
    report = json.loads(raw)
    inventory = json.loads(inventory_bytes)
    _require(type(report.get("schema_version")) is int and report["schema_version"] == 1,
             "invalid schema")
    for key in ("version", "source_commit"):
        _require(report.get(key) == manifest.get(key), f"mismatched {key}")
    _require(inventory.get("source_commit") == manifest.get("source_commit"),
             "application inventory source differs")
    _require(report.get("scope") == "authenticode-inventory", "invalid scope")
    _require(report.get("installer_sha256") == installer_sha256 and _hash(installer_sha256),
             "setup hash differs")
    _require(report.get("smart_app_control") == {"status": "not-performed"},
             "signature inventory cannot attest Smart App Control")
    uninstaller = report.get("uninstaller", {})
    _require(uninstaller.get("status") == "not-inspected"
             and isinstance(uninstaller.get("reason"), str) and bool(uninstaller["reason"]),
             "staged inventory cannot attest the generated uninstaller")
    source_files = inventory.get("files")
    _require(isinstance(source_files, list), "invalid application inventory")
    expected = {}
    all_sources = {}
    for item in source_files:
        _require(isinstance(item, dict) and _safe_path(item.get("path"))
                 and _hash(item.get("sha256")), "invalid inventoried path/hash")
        path = "app/" + item["path"]
        _require(path.casefold() not in {p.casefold() for p in all_sources},
                 "duplicate application inventory path")
        all_sources[path] = item["sha256"]
        if PurePosixPath(path).suffix.casefold() in EXTENSIONS:
            expected[path] = item["sha256"]
    expected["setup/NIPAT-Setup.exe"] = installer_sha256
    archives = report.get("embedded_archives")
    _require(isinstance(archives, list) and len(archives) == 1, "missing embedded CPython archive")
    archive = archives[0]
    _require(isinstance(archive, dict), "invalid embedded archive")
    archive_path = archive.get("path", "")
    _require(archive_path == "app/.distribution/" + PYTHON_INPUT["file"], "invalid embedded CPython path")
    _require(_hash(archive.get("sha256"))
             and all_sources.get(archive_path) == archive["sha256"] == PYTHON_INPUT["sha256"],
             "embedded archive hash differs")
    _require(type(archive.get("size")) is int and archive["size"] == PYTHON_INPUT["size"],
             "invalid embedded archive size")
    expected_members = {entry["path"]: entry for entry in PYTHON_INPUT["executable_files"]}
    files = report.get("files")
    _require(isinstance(files, list) and 0 < len(files) <= 10000, "invalid executable list")
    seen = set()
    found = set()
    members = set()
    counts = {"Valid": 0, "NotSigned": 0}
    for item in files:
        _require(isinstance(item, dict), "invalid executable record")
        path = item.get("path")
        _require(_safe_path(path) and path.casefold() not in seen, "invalid/duplicate executable path")
        seen.add(path.casefold())
        _require(_hash(item.get("sha256")) and type(item.get("size")) is int
                 and 0 < item["size"] < 2 * 1024 * 1024 * 1024, "invalid executable hash/size")
        if path.startswith(archive_path + "!/"):
            member = path[len(archive_path) + 2:]
            _require(_safe_path(member) and PurePosixPath(member).suffix.casefold() in EXTENSIONS,
                     "invalid executable archive member")
            _require(member in expected_members
                     and item["sha256"] == expected_members[member]["sha256"]
                     and item["size"] == expected_members[member]["size"],
                     "executable archive member differs from pinned CPython")
            members.add(member)
        else:
            _require(path in expected and expected[path] == item["sha256"],
                     "executable does not match application inventory")
            found.add(path)
        status = item.get("signature_status")
        _require(status in counts, "invalid signature must not be treated as unsigned")
        counts[status] += 1
        signer = item.get("signer")
        if status == "Valid":
            _require(isinstance(signer, dict) and isinstance(signer.get("subject"), str)
                     and bool(signer["subject"])
                     and isinstance(signer.get("thumbprint"), str)
                     and re.fullmatch(r"[0-9a-f]{40}", signer["thumbprint"]) is not None
                     and isinstance(signer.get("public_key_oid"), str)
                     and re.fullmatch(r"\d+(?:\.\d+)+", signer["public_key_oid"]) is not None,
                     "invalid signer identity")
        else:
            _require(signer is None, "unsigned file has a signer")
    _require(found == set(expected), "missing staged executable/script")
    _require(set(expected_members) == members,
             "embedded Python executables are missing")
    declared_counts = report.get("counts")
    _require(isinstance(declared_counts, dict) and declared_counts == counts
             and all(type(value) is int for value in declared_counts.values()), "incorrect signature totals")
    assessment = "unsigned-components-present" if counts["NotSigned"] else "signatures-valid-not-sac-tested"
    _require(report.get("assessment") == assessment, "misleading signature assessment")
    return {"file": report_path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "assessment": assessment, "counts": counts, "smart_app_control": "not-performed"}
