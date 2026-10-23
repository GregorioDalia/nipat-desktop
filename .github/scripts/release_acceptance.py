"""Bind explicit desktop acceptance to one verified Windows/Ubuntu build."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

SCENARIOS = {
    "windows_clean_wsl", "windows_stable_coexistence", "windows_reinstall_removal",
    "ubuntu_clean_dependencies", "ubuntu_existing_docker", "ubuntu_reinstall_removal",
}
DIGESTS = {
    "installer_manifest_sha256", "scientific_archive_sha256",
    "windows_installer_sha256", "linux_installer_sha256",
}
FIELDS = {"schema_version", "version", "source_commit", "build_run_id", "decision", "tests"} | DIGESTS


def require(condition, message):
    if not condition:
        raise ValueError(message)


def acceptance_path(version):
    require(isinstance(version, str) and re.fullmatch(r"0\.5\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version),
            "Joint publication is supported only for the 0.5 preview contract")
    return f".github/release-acceptance/v{version}.json"


def identity(installer_set):
    return {
        "version": installer_set["version"],
        "source_commit": installer_set["source_commit"],
        "installer_manifest_sha256": installer_set["installer_manifest_sha256"],
        "scientific_archive_sha256": installer_set["scientific_archive"]["sha256"],
        "windows_installer_sha256": installer_set["windows"]["sha256"],
        "linux_installer_sha256": installer_set["linux"]["sha256"],
    }


def template(installer_set, run_id):
    require(type(run_id) is int and run_id > 0, "Invalid build run ID")
    fields = identity(installer_set)
    acceptance_path(fields["version"])
    require(isinstance(fields["source_commit"], str)
            and re.fullmatch(r"[0-9a-f]{40}", fields["source_commit"]), "Invalid source commit")
    for field in DIGESTS:
        require(isinstance(fields[field], str) and re.fullmatch(r"[0-9a-f]{64}", fields[field]),
                f"Invalid digest: {field}")
    return {
        "schema_version": 1, **fields, "build_run_id": run_id, "decision": "pending",
        "tests": {name: {"result": "pending", "tester": "", "tested_at": "", "evidence": []}
                  for name in sorted(SCENARIOS)},
    }


def validate(record, version, commit, run_id, installer_set=None):
    """A committed human record is necessary; CI evidence alone is insufficient."""
    acceptance_path(version)
    require(isinstance(record, dict) and set(record) == FIELDS, "Acceptance record fields are invalid")
    require(type(record["schema_version"]) is int and record["schema_version"] == 1,
            "Unsupported acceptance schema")
    require(record["version"] == version and record["source_commit"] == commit
            and type(record["build_run_id"]) is int and record["build_run_id"] == run_id,
            "Acceptance belongs to a different version, source or build run")
    require(record["decision"] == "accepted", "Desktop acceptance is pending or rejected")
    for field in DIGESTS:
        require(isinstance(record[field], str) and re.fullmatch(r"[0-9a-f]{64}", record[field]),
                f"Invalid acceptance digest: {field}")
    tests = record["tests"]
    require(isinstance(tests, dict) and set(tests) == SCENARIOS,
            "A required desktop acceptance scenario is missing")
    for name, test in tests.items():
        require(isinstance(test, dict) and set(test) == {"result", "tester", "tested_at", "evidence"},
                f"Invalid acceptance scenario: {name}")
        require(test["result"] == "passed", f"Desktop acceptance has not passed: {name}")
        require(isinstance(test["tester"], str) and test["tester"].strip(),
                f"Missing tester: {name}")
        timestamp = test["tested_at"]
        require(isinstance(timestamp, str)
                and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", timestamp),
                f"Acceptance timestamp must be a UTC date and time: {name}")
        try:
            tested_at = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError as error:
            raise ValueError(f"Invalid acceptance date: {name}") from error
        require(tested_at <= datetime.now(timezone.utc), f"Acceptance date is in the future: {name}")
        evidence = test["evidence"]
        require(isinstance(evidence, list) and evidence and all(isinstance(link, str) for link in evidence),
                f"Missing acceptance evidence: {name}")
        for link in evidence:
            parsed = urlsplit(link)
            require(parsed.scheme == "https" and parsed.hostname and parsed.path not in ("", "/")
                    and not parsed.username and not parsed.password and not any(c.isspace() for c in link),
                    f"Acceptance evidence must identify an HTTPS resource: {name}")
    if installer_set is not None:
        require(all(record[field] == value for field, value in identity(installer_set).items()),
                "Acceptance hashes do not identify these verified installers")


def load(version, commit, run_id, publication_commit, read_source):
    path = acceptance_path(version)
    try:
        raw = read_source(publication_commit, path)
    except (OSError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
        raise ValueError(f"Missing committed desktop acceptance: {path}") from error
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"Invalid committed desktop acceptance: {path}") from error
    validate(record, version, commit, run_id)
    return record, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer-set", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record = template(json.loads(args.installer_set.read_text(encoding="utf-8")), args.run_id)
    # Never replace an existing acceptance record or represent this template as approval.
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=2) + "\n")
    print("Pending acceptance template written; no publication is authorized.")


if __name__ == "__main__":
    main()
