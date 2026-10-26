"""Bind an explicit desktop or research acceptance policy to one verified build."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
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
RESEARCH_FIELDS = (FIELDS - {"tests"}) | {
    "scope", "review", "observed_baseline", "deferred_desktop_scenarios", "domain_validation",
}
REVIEWED_RESEARCH_FIELDS = RESEARCH_FIELDS | {"reviewed_source_changes"}
SOURCE_EQUIVALENCE_SCOPE = "distributed-operative-sources-v1"
REVIEWED_SOURCE_SCOPE = "scientific-runtime-equivalence-with-reviewed-client-changes-v1"
BASELINE_OBSERVATIONS = {
    "installation_ready", "runtime_diagnostics", "scientific_self_tests", "dnp_sample_analysis",
}
WORKFLOW_BASELINE_OBSERVATIONS = BASELINE_OBSERVATIONS | {"automatic_workflow_sample_analysis"}
REVIEWABLE_CLIENT_PREFIXES = ("src/nipat/", "installer/windows/", "installer/linux/", "scripts/", "tests/")
REVIEWABLE_CLIENT_FILES = {"pyproject.toml", "1_SETUP.cmd", "2_AVVIA.cmd", "nipat.cmd"}
REMOVABLE_SIGNING_HELPERS = {
    "installer/windows/verify-signatures.ps1", "installer/windows/test-signatures.ps1",
}
# These inputs must remain part of the distributed inventory being compared.
REQUIRED_OPERATIVE_PATHS = {
    "pyproject.toml", "compose.yaml", "engine/main.py", "src/nipat/cli.py", "scientific/SHA256SUMS",
    "docker/scientific-runtime/Dockerfile", "docker/scientific-runtime/r-packages.tsv",
    "installer/runtime/Dockerfile", "installer/runtime/nipat-engine", "installer/windows/NIPAT.iss",
    "scripts/build_windows_installer_assets.py", "scripts/build_linux_installer.py",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def acceptance_path(version):
    require(isinstance(version, str) and re.fullmatch(r"0\.[567]\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version),
            "Joint publication is supported only for the 0.5, 0.6 and 0.7 desktop contracts")
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
    """Require a committed review under the record's explicit acceptance policy."""
    acceptance_path(version)
    if isinstance(record, dict) and type(record.get("schema_version")) is int and record["schema_version"] in (2, 3):
        validate_research(record, version, commit, run_id, installer_set)
        return
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


def review_timestamp(value, label):
    require(isinstance(value, str)
            and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value),
            f"{label} must be a UTC date and time")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise ValueError(f"Invalid {label}") from error
    require(parsed <= datetime.now(timezone.utc), f"{label} is in the future")


def review_evidence(value, label):
    require(isinstance(value, list) and value and all(isinstance(link, str) for link in value),
            f"Missing {label}")
    for link in value:
        parsed = urlsplit(link)
        require(parsed.scheme == "https" and parsed.hostname and parsed.path not in ("", "/")
                and not parsed.username and not parsed.password and not any(c.isspace() for c in link),
                f"{label} must identify an HTTPS resource")


def validate_research(record, version, commit, run_id, installer_set=None):
    """A limited research decision records deferred qualification, never fictitious passes."""
    reviewed_delta = isinstance(record, dict) and type(record.get("schema_version")) is int and record["schema_version"] == 3
    minor = "7" if reviewed_delta else "6"
    require(isinstance(version, str) and re.fullmatch(rf"0\.{minor}\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version),
            f"Research acceptance schema {3 if reviewed_delta else 2} is limited to the pre-1.0 0.{minor} contract")
    require(isinstance(record, dict) and set(record) == (REVIEWED_RESEARCH_FIELDS if reviewed_delta else RESEARCH_FIELDS)
            and type(record["schema_version"]) is int and record["schema_version"] == (3 if reviewed_delta else 2),
            "Research acceptance record fields are invalid")
    require(record["version"] == version and record["source_commit"] == commit
            and isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit)
            and type(record["build_run_id"]) is int and type(run_id) is int
            and run_id > 0 and record["build_run_id"] == run_id,
            "Acceptance belongs to a different version, source or build run")
    for field in DIGESTS:
        require(isinstance(record[field], str) and re.fullmatch(r"[0-9a-f]{64}", record[field]),
                f"Invalid acceptance digest: {field}")
    require(record["decision"] == "accepted-for-research" and record["scope"] == "pre-1.0-research",
            "Research acceptance is pending, rejected or outside its stated scope")
    review = record["review"]
    require(isinstance(review, dict) and set(review) == {"reviewer", "reviewed_at", "evidence"},
            "Invalid research review fields")
    require(isinstance(review["reviewer"], str) and review["reviewer"].strip(), "Missing research reviewer")
    review_timestamp(review["reviewed_at"], "Research review date")
    review_evidence(review["evidence"], "Research review evidence")
    baseline = record["observed_baseline"]
    require(isinstance(baseline, dict) and set(baseline) == {
        "source_commit", "observations", "evidence", "source_equivalence_scope",
    }, "Invalid observed baseline fields")
    require(isinstance(baseline["source_commit"], str)
            and re.fullmatch(r"[0-9a-f]{40}", baseline["source_commit"]), "Invalid observed baseline commit")
    observations = baseline["observations"]
    allowed_observations = WORKFLOW_BASELINE_OBSERVATIONS if reviewed_delta else BASELINE_OBSERVATIONS
    require(isinstance(observations, list) and all(isinstance(item, str) for item in observations)
            and len(observations) == len(set(observations)) and set(observations) <= allowed_observations
            and "installation_ready" in observations
            and bool(set(observations) & ({"scientific_self_tests", "dnp_sample_analysis"}
                                         | ({"automatic_workflow_sample_analysis"} if reviewed_delta else set()))),
            "Baseline must identify observed installation and scientific execution")
    require(baseline["source_equivalence_scope"] == (REVIEWED_SOURCE_SCOPE if reviewed_delta else SOURCE_EQUIVALENCE_SCOPE),
            "Unsupported baseline source equivalence scope")
    review_evidence(baseline["evidence"], "Observed baseline evidence")
    deferred = record["deferred_desktop_scenarios"]
    require(isinstance(deferred, list) and all(isinstance(item, str) for item in deferred)
            and len(deferred) == len(SCENARIOS) and set(deferred) == SCENARIOS,
            "Research acceptance must explicitly defer all six desktop scenarios")
    require(record["domain_validation"] == ("pending-domain-researchers" if reviewed_delta else "planned-for-0.7"),
            "Research acceptance cannot claim completed domain validation")
    if reviewed_delta:
        changes = record["reviewed_source_changes"]
        require(isinstance(changes, list), "Reviewed source changes must be an explicit list")
        paths = []
        for item in changes:
            require(isinstance(item, dict) and set(item) == {"path", "before_sha256", "after_sha256"},
                    "Invalid reviewed source change fields")
            path = item["path"]
            require(isinstance(path, str) and path and PurePosixPath(path).as_posix() == path
                    and not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts
                    and "\\" not in path and not any(character.isspace() for character in path)
                    and PurePosixPath(path).suffix.casefold() != ".md"
                    and (path in REVIEWABLE_CLIENT_FILES or path.startswith(REVIEWABLE_CLIENT_PREFIXES)),
                    "Only explicit client, installer and test source changes can be reviewed")
            for field in ("before_sha256", "after_sha256"):
                digest = item[field]
                require(digest is None or isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest),
                        "Invalid reviewed source digest")
            require(item["before_sha256"] != item["after_sha256"], "Reviewed source change must identify different bytes")
            paths.append(path)
        require(paths == sorted(set(paths)), "Reviewed source changes must be sorted and unique")
    if installer_set is not None:
        require(all(record[field] == value for field, value in identity(installer_set).items()),
                "Acceptance hashes do not identify these verified installers")


def verify_baseline(record, read_source):
    """Compare operative source bytes; this does not assert installer or image identity.

    Markdown documentation and .github maintenance/CI/release procedures are not
    executable inputs of the installed application. The allowlist is compared as
    a normalized inventory. Schema 2 only exempts removal of two obsolete signing
    helpers. Schema 3 requires an exact hash review for permitted client changes
    and keeps scientific, engine and runtime sources immutable.
    """
    require(isinstance(record, dict) and type(record.get("schema_version")) is int
            and record["schema_version"] in (1, 2, 3), "Unsupported acceptance schema")
    if record["schema_version"] == 1:
        return None
    reviewed_delta = record["schema_version"] == 3
    require(set(record) == (REVIEWED_RESEARCH_FIELDS if reviewed_delta else RESEARCH_FIELDS),
            "Research acceptance record fields are invalid")
    validate_research(record, record["version"], record["source_commit"], record["build_run_id"])
    baseline = record["observed_baseline"]["source_commit"]
    candidate = record["source_commit"]

    def read(commit, path):
        try:
            result = read_source(commit, path)
        except (OSError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
            raise ValueError(f"Cannot read baseline equivalence input: {commit}:{path}") from error
        require(isinstance(result, bytes), "Source equivalence requires exact file bytes")
        return result

    def inventory(commit):
        try:
            lines = read(commit, "distribution-files.txt").decode("utf-8").splitlines()
        except UnicodeError as error:
            raise ValueError("Invalid source inventory encoding") from error
        paths = set()
        for line in lines:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            path = PurePosixPath(value)
            require(not path.is_absolute() and path.as_posix() == value and ".." not in path.parts
                    and "\\" not in value and value not in paths, "Invalid or duplicate source inventory path")
            paths.add(value)
        require("distribution-files.txt" in paths and REQUIRED_OPERATIVE_PATHS <= paths,
                "Source inventory omits required operative inputs")
        return {path for path in paths if path != "distribution-files.txt"
                and not path.startswith(".github/") and PurePosixPath(path).suffix.casefold() != ".md"}

    before, after = inventory(baseline), inventory(candidate)
    if reviewed_delta:
        changes = []
        unchanged = 0
        for path in sorted(before | after):
            old = read(baseline, path) if path in before else None
            new = read(candidate, path) if path in after else None
            if old == new:
                unchanged += 1
                continue
            require(path in REVIEWABLE_CLIENT_FILES or path.startswith(REVIEWABLE_CLIENT_PREFIXES),
                    f"Protected scientific or runtime source differs: {path}")
            changes.append({"path": path,
                            "before_sha256": hashlib.sha256(old).hexdigest() if old is not None else None,
                            "after_sha256": hashlib.sha256(new).hexdigest() if new is not None else None})
        require(record["reviewed_source_changes"] == changes,
                "Reviewed source changes do not match the exact baseline-to-candidate delta")
        return {"baseline_source_commit": baseline, "source_commit": candidate,
                "scope": REVIEWED_SOURCE_SCOPE, "unchanged_files_verified": unchanged,
                "reviewed_source_changes": changes, "candidate_windows_installation_claimed": False}
    before -= REMOVABLE_SIGNING_HELPERS & (before - after)
    require(before == after, "Baseline operative inventory differs from candidate")
    for path in sorted(after):
        require(read(baseline, path) == read(candidate, path), f"Baseline operative source differs: {path}")
    return {"baseline_source_commit": baseline, "source_commit": candidate,
            "scope": SOURCE_EQUIVALENCE_SCOPE, "files_verified": len(after)}


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
