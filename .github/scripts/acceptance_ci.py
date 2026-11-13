"""Check acceptance against a successful build using its bounded evidence bundle."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

from ci_changes import ACCEPTANCE_PATH
import publish_windows_release as publisher
import qualification_evidence as qualification
import release_acceptance as acceptance
from scientific_reuse import download_artifact, fetch_json, read_zip


EVIDENCE_FILES = {"installer-set-check.json", "qualification-evidence.json", "qualification-evidence.zip"}


def read_record(path, revision):
    publisher.require(isinstance(path, str) and ACCEPTANCE_PATH.fullmatch(path), "Invalid acceptance path")
    publisher.require(re.fullmatch(r"[0-9a-f]{40}", revision), "Invalid acceptance revision")
    entry = publisher.command("git", "ls-tree", revision, "--", path)
    publisher.require(entry.startswith("100644 blob "), "Acceptance must be a committed regular JSON file")
    raw = publisher.source_bytes(revision, path)
    publisher.require(len(raw) <= 1024 * 1024, "Acceptance record exceeds its size bound")
    record = json.loads(raw)
    publisher.require(isinstance(record, dict), "Acceptance must be an object")
    source = record.get("source_commit", "")
    publisher.require(isinstance(source, str) and re.fullmatch(r"[0-9a-f]{40}", source), "Invalid accepted source")
    version = publisher.committed_version(source)
    publisher.require(path == acceptance.acceptance_path(version), "Acceptance filename differs from built version")
    acceptance.validate(record, version, source, record.get("build_run_id"))
    subprocess.run(["git", "merge-base", "--is-ancestor", source, revision], check=True)
    return record


def validate_build(record, run, jobs):
    publisher.validate_run(run, record["source_commit"], record["build_run_id"])
    publisher.require(run["event"] == "workflow_dispatch", "Accepted installer build must be manually dispatched")
    for name in publisher.required_build_jobs(record["version"]):
        matches = [job for job in jobs if job.get("name") == name]
        publisher.require(len(matches) == 1 and matches[0].get("conclusion") == "success",
                          f"Missing successful build job: {name}")


def evidence_artifact(document, record):
    matches = [item for item in document["artifacts"] if item.get("name") == "nipat-installer-set-evidence"]
    publisher.require(len(matches) == 1, "Missing or ambiguous build evidence artifact")
    artifact = matches[0]
    identity = artifact.get("workflow_run") or {}
    publisher.require(artifact.get("expired") is False
                      and identity.get("id") == record["build_run_id"]
                      and identity.get("head_sha") == record["source_commit"],
                      "Evidence artifact belongs to a different or expired build")
    return artifact


def verify_evidence(record, directory):
    installer_set = json.loads((directory / "installer-set-check.json").read_bytes())
    publisher.require(installer_set.get("publication_authorized") is False,
                      "Build evidence cannot authorize publication")
    acceptance.validate(record, record["version"], record["source_commit"],
                        record["build_run_id"], installer_set)
    qualification.verify(directory, installer_set)
    publisher.require(publisher.sha256(directory / "qualification-evidence.zip")
                      == record["qualification_evidence_sha256"], "Qualification archive differs from acceptance")
    with zipfile.ZipFile(directory / "qualification-evidence.zip") as archive:
        manifest_bytes = archive.read("components/installer-manifest.json")
    publisher.require(qualification.digest(manifest_bytes) == record["installer_manifest_sha256"],
                      "Manifest bytes differ from acceptance")
    manifest = json.loads(manifest_bytes)
    publisher.require(manifest["source_commit"] == record["source_commit"]
                      and manifest["version"] == record["version"]
                      and manifest["assets"]["scientific_image"]["sha256"] == record["scientific_archive_sha256"],
                      "Scientific manifest identity differs from acceptance")
    publisher.verify_research_baseline(record, acceptance)
    if record.get("schema_version") in (6, 7):
        acceptance.verify_scientific_equivalence(record, directory, manifest, publisher.source_bytes)
    return installer_set


def verify_record(path, revision, *, fetch=fetch_json, download=download_artifact):
    record = read_record(path, revision)
    run_id = record["build_run_id"]
    run = fetch(f"actions/runs/{run_id}")
    jobs = fetch(f"actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    validate_build(record, run, jobs)
    artifact = evidence_artifact(fetch(f"actions/runs/{run_id}/artifacts?per_page=100"), record)
    with tempfile.TemporaryDirectory(prefix="nipat-acceptance-") as temporary:
        directory = Path(temporary)
        archive = directory / "artifact.zip"
        download(artifact, archive)
        entries = read_zip(archive, maximum=qualification.MAX_TOTAL + 4 * 1024 * 1024,
                           max_file=qualification.MAX_TOTAL, max_entries=3,
                           allowed=lambda name: name in EVIDENCE_FILES)
        publisher.require(set(entries) == EVIDENCE_FILES, "Incomplete acceptance evidence artifact")
        for name, data in entries.items():
            (directory / name).write_bytes(data)
        verify_evidence(record, directory)
    print(f"PASS: {path} matches successful build {run_id}, four installer hashes and scientific evidence.")
    return record


def main():
    paths = json.loads(os.environ["ACCEPTANCE_PATHS"])
    publisher.require(isinstance(paths, list) and 0 < len(paths) <= 20
                      and all(isinstance(path, str) for path in paths)
                      and len(paths) == len(set(paths)), "Invalid acceptance path list")
    revision = publisher.command("git", "rev-parse", "HEAD")
    for path in paths:
        verify_record(path, revision)


if __name__ == "__main__":
    main()
