"""Reuse successful CI science only for identical source trees and Docker images.

This optional cache never authorizes a release. Any unavailable or mismatched
proof is a cache miss; the installer workflow then runs every scientific gate.
"""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from qualification_evidence import ALLOWED, MAX_ENTRIES, MAX_FILE, MAX_TOTAL, safe_name
import release_acceptance as acceptance


REPOSITORY = "GregorioDalia/nipat-desktop"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}/"
DESCRIPTOR = "scientific-qualification.json"
ARCHIVE = "scientific-evidence.zip"
MAX_DESCRIPTOR = 2 * 1024 * 1024
MAX_DOWNLOAD = MAX_TOTAL + 4 * 1024 * 1024
SEARCH_BUDGET_SECONDS = 120
PRODUCER_STEPS = ("Seal successful scientific qualification for exact-image reuse", "Retain reusable scientific qualification")
CHECK_DIRECTORIES = (
    "nipat-engine-check", "nipat-presentation-check", "nipat-performance-check",
    "nipat-native-r-check", "nipat-five-modules-check", "nipat-r-equivalence-check",
)
RESTORE_DIRECTORIES = (*CHECK_DIRECTORIES, "nipat-validation")
STEPS = (
    "Verify bundled scientific scripts without host sources",
    "Verify original sample labels and unchanged scientific results",
    "Scientific regression and input-mode checks",
    "Verify optional performance evidence and unchanged DNP results",
    "Verify native scientific edge cases and settings in the installed image",
    "Verify updated CPI Contamination and CPIN models",
    "Compare scientific cores with immutable versioned references",
)
REPORTS = {
    "nipat-r-equivalence-check/artifacts/r-equivalence.json": "callers",
    "nipat-five-modules-check/artifacts/five-module-qualification.json": "analyses",
}


class ReuseMiss(ValueError):
    """A safe, locally authored diagnostic suitable for the public receipt."""


def require(condition, message):
    if not condition:
        raise ReuseMiss(message)


def remaining_timeout(deadline=None, maximum=10):
    remaining = maximum if deadline is None else deadline - time.monotonic()
    require(remaining > 0, "Scientific reuse search budget exhausted")
    return min(maximum, remaining)


def error_reason(error):
    # Parser/network exceptions can contain signed URLs or untrusted values.
    return str(error) if isinstance(error, ReuseMiss) else type(error).__name__


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def sha(value, length=40):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value) is not None


def positive(value):
    return type(value) is int and value > 0


def run(*arguments):
    return subprocess.check_output(arguments, text=True, stderr=subprocess.PIPE).strip()


def checkout():
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    require(not run("git", "ls-files", "--others", "--exclude-standard"), "Untracked source files prevent scientific reuse")
    commit, tree = run("git", "rev-parse", "HEAD"), run("git", "rev-parse", "HEAD^{tree}")
    require(sha(commit) and sha(tree), "Invalid checkout identity")
    return {"commit": commit, "tree": tree}


def image_identity(reference):
    require(isinstance(reference, str) and reference and not reference.startswith("-"), "Invalid image reference")
    images = json.loads(run("docker", "image", "inspect", reference))
    require(isinstance(images, list) and len(images) == 1, "Expected exactly one Docker image")
    image = images[0]
    result = {"id": image.get("Id"), "os": image.get("Os"), "architecture": image.get("Architecture")}
    require(isinstance(result["id"], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", result["id"])
            and result["os"] == "linux" and result["architecture"] == "amd64", "Expected immutable Linux AMD64 image")
    return result


def selected_path(name):
    if not isinstance(name, str) or not safe_name(name):
        return False
    parts = PurePosixPath(name).parts
    if len(parts) < 2 or PurePosixPath(name).suffix.lower() not in ALLOWED:
        return False
    return (parts[0] in CHECK_DIRECTORIES or
            (len(parts) >= 4 and parts[:2] == ("nipat-validation", "runs")
             and parts[-1] in {"run.json", "execution.log"}))


def raw_evidence(runner_temp):
    require(runner_temp.is_dir() and not runner_temp.is_symlink(), "Invalid runner temporary directory")
    seen, total = set(), 0
    for directory in RESTORE_DIRECTORIES:
        root = runner_temp / directory
        require(root.is_dir() and not root.is_symlink(), "Missing scientific evidence directory")
        for path in sorted(root.rglob("*")):
            require(not path.is_symlink(), "Symlinks are not scientific evidence")
            if not path.is_file():
                continue
            name = path.relative_to(runner_temp).as_posix()
            if not selected_path(name):
                continue
            require(path.stat().st_size <= MAX_FILE, "Scientific evidence file exceeds its bound")
            data = path.read_bytes()
            data.decode("utf-8-sig")  # Validate text without normalizing its bytes.
            require(len(data) <= MAX_FILE and name.casefold() not in seen, "Invalid scientific evidence entry")
            total += len(data)
            require(total <= MAX_TOTAL and len(seen) < MAX_ENTRIES, "Scientific evidence exceeds its bounds")
            seen.add(name.casefold())
            yield name, data


def verify_required(evidence, image):
    require(all(f"{directory}/verification.log" in evidence for directory in CHECK_DIRECTORIES),
            "Scientific gate logs are incomplete")
    require(any(name.startswith("nipat-validation/runs/") and name.endswith("/run.json") for name in evidence)
            and any(name.startswith("nipat-validation/runs/") and name.endswith("/execution.log") for name in evidence),
            "Self-test execution evidence is incomplete")
    performance = json.loads(evidence.get("nipat-performance-check/artifacts/verification.json", b"null"))
    require(isinstance(performance, dict) and performance.get("schema_version") == 1
            and performance.get("status") == "passed" and performance.get("image_id") == image["id"],
            "Performance qualification report is missing or belongs to another image")
    for name, kind in REPORTS.items():
        require(name in evidence, "Scientific qualification report is missing")
        report = json.loads(evidence[name])
        require(isinstance(report, dict) and report.get("status") == "passed"
                and report.get("inputs_unchanged") is True, "Scientific qualification report did not pass")
        if kind == "callers":
            require(report.get("schema_version") == 1 and report.get("runtime_image") == image["id"]
                    and isinstance(report.get("cases"), list) and bool(report["cases"])
                    and isinstance(report.get("candidate_r_sha256"), dict) and bool(report["candidate_r_sha256"]),
                    "Caller report identity or internals are invalid")
            required_cases = {name for name, workflow in {**acceptance.R_CASES, **acceptance.R_AUDIT_CASES,
                **acceptance.SNP2_CASES}.items() if workflow in {"dnp-call", "snp-call"}}
            cases = report["cases"]
            require(all(isinstance(case, dict) for case in cases)
                    and len(cases) == len({case.get("case") for case in cases})
                    and required_cases <= {case.get("case") for case in cases}
                    and all(case.get("status") == "passed" for case in cases), "Caller execution coverage is incomplete")
            helpers = report.get("helpers")
            required_helpers = {path for path in acceptance.R_HELPERS | acceptance.R_AUDIT_HELPERS | {acceptance.PRESENTATION_HELPER}
                if not path.startswith(("tests/r_optimization/cpi/", "tests/r_optimization/contamination/"))}
            require(isinstance(helpers, list) and all(isinstance(helper, dict) for helper in helpers)
                    and len(helpers) == len({helper.get("path") for helper in helpers})
                    and required_helpers <= {helper.get("path") for helper in helpers}
                    and all(helper.get("status") == "passed" and sha(helper.get("sha256"), 64) for helper in helpers),
                    "Caller focused comparison coverage is incomplete")
        else:
            require(report.get("schema_version") == 2 and report.get("runtime", {}).get("image_id") == image["id"]
                    and report.get("runtime", {}).get("kind") == "installed-image"
                    and report.get("full_batch_matrix") is True and report.get("source_unchanged") is True
                    and isinstance(report.get("results"), list) and bool(report["results"])
                    and sha(report.get("verification_script_sha256"), 64),
                    "Analysis report identity or internals are invalid")
            cases = report["results"]
            expected = acceptance.analysis_expected_cases()
            require(all(isinstance(case, dict) for case in cases) and len(cases) == len(expected)
                    and {case.get("name") for case in cases} == set(expected), "Analysis execution coverage is incomplete")
            for case in cases:
                workflow = expected[case["name"]][0]
                filename = {"cpin": "Summary_Postnatal_CPI.txt", "cpi": "Summary_FetalFraction_CPI.csv",
                            "contamination": "contamination_summary.txt"}[workflow]
                member = str(PurePosixPath(name).parent / case["name"] / "output" / filename)
                require(case.get("status") == "passed" and case.get("workflow") == workflow
                        and sha(case.get("summary_sha256"), 64) and member in evidence
                        and case.get("output_sha256", {}).get(filename) == case["summary_sha256"]
                        and sha256(evidence[member]) == case["summary_sha256"],
                        "A retained scientific summary is missing or differs from its qualified bytes")


def producer_identity(source):
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "Scientific producer must belong to this repository")
    event = os.environ.get("GITHUB_EVENT_NAME")
    require(event in {"push", "pull_request", "workflow_dispatch"}, "Unsupported scientific producer event")
    require(os.environ.get("GITHUB_SHA") == source["commit"], "Producer checkout differs from the event commit")
    run_id, attempt = int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"])
    require(positive(run_id) and positive(attempt), "Invalid producer run identity")
    result = {"run_id": run_id, "attempt": attempt, "event": event,
              "head_sha": source["commit"], "checkout_commit": source["commit"], "checkout_tree": source["tree"]}
    if event == "pull_request":
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        pull = payload["pull_request"]
        require(pull["head"]["repo"]["full_name"] == pull["base"]["repo"]["full_name"] == REPOSITORY,
                "Fork pull requests cannot supply reusable science")
        result.update(head_sha=pull["head"]["sha"], pull_request={
            "number": payload["number"], "base_sha": pull["base"]["sha"], "head_sha": pull["head"]["sha"],
        })
    return result


def tool_version(name):
    result = subprocess.run([name, "-v"], capture_output=True, text=True, check=True)
    lines = (result.stdout + result.stderr).splitlines()
    require(bool(lines), "Missing host tool version")
    return lines[0][:200]


def seal(image, output, runner_temp):
    source = checkout()
    producer = producer_identity(source)
    identity = image_identity(image)
    evidence = dict(raw_evidence(runner_temp))
    verify_required(evidence, identity)
    require(checkout() == source, "Producer checkout changed while sealing")
    require(platform.python_version() == "3.12.10", "Scientific producer must use pinned Python 3.12.10")
    environment = {"python": platform.python_version(), "system": platform.system(), "machine": platform.machine(),
                   "pdfinfo": tool_version("pdfinfo"), "pdftoppm": tool_version("pdftoppm")}
    require(environment["system"] == "Linux" and environment["machine"] == "x86_64", "Unexpected producer host")
    output.mkdir(parents=True, exist_ok=True)
    require(not output.is_symlink() and not any(output.iterdir()), "Scientific qualification output must be empty")
    try:
        with zipfile.ZipFile(output / ARCHIVE, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in evidence.items():
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                archive.writestr(info, data)
        archived = (output / ARCHIVE).read_bytes()
        require(len(archived) <= MAX_TOTAL, "Scientific archive exceeds its bound")
        record = {"schema_version": 1, "repository": REPOSITORY, "producer": producer, "image": identity,
                  "environment": environment, "steps": list(STEPS),
                  "archive": {"file": ARCHIVE, "size": len(archived), "sha256": sha256(archived)},
                  "entries": [{"path": name, "size": len(data), "sha256": sha256(data)} for name, data in evidence.items()]}
        encoded = (json.dumps(record, indent=2) + "\n").encode()
        require(len(encoded) <= MAX_DESCRIPTOR, "Scientific descriptor exceeds its bound")
        (output / DESCRIPTOR).write_bytes(encoded)
        return record
    except BaseException:
        (output / ARCHIVE).unlink(missing_ok=True)
        (output / DESCRIPTOR).unlink(missing_ok=True)
        raise


def api_url(path):
    require(isinstance(path, str) and re.fullmatch(r"[A-Za-z0-9_./?=&-]+", path)
            and not path.startswith("/") and ".." not in path, "Invalid repository API path")
    return API_ROOT + path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def api_request(path):
    request = urllib.request.Request(api_url(path), headers={"Accept": "application/vnd.github+json",
                                                           "User-Agent": "nipat-scientific-reuse"})
    token = os.environ.get("GH_TOKEN", "")
    if token:
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    return request


def fetch_json(path, *, deadline=None):
    with urllib.request.build_opener(NoRedirect()).open(api_request(path), timeout=remaining_timeout(deadline)) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    remaining_timeout(deadline)
    require(len(data) <= 4 * 1024 * 1024, "Repository API response exceeds its bound")
    return json.loads(data)


def allowed_download(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ""
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and not parsed.fragment
                and (host.endswith(".blob.core.windows.net") or host.endswith(".actions.githubusercontent.com")
                     or host.endswith(".s3.amazonaws.com") or re.fullmatch(r"[a-z0-9.-]+\.s3\.[a-z0-9-]+\.amazonaws\.com", host)
                     or host == "objects.githubusercontent.com"))
    except (TypeError, ValueError):
        return False


class ArtifactRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        require(allowed_download(newurl), "Artifact redirected to an unapproved host")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download_artifact(artifact, destination, *, deadline=None):
    require(positive(artifact.get("id")) and type(artifact.get("size_in_bytes")) is int
            and 0 < artifact["size_in_bytes"] <= MAX_DOWNLOAD
            and isinstance(artifact.get("digest"), str) and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"]),
            "Artifact size or GitHub digest is invalid")
    try:
        urllib.request.build_opener(NoRedirect()).open(api_request(f"actions/artifacts/{artifact['id']}/zip"), timeout=remaining_timeout(deadline))
    except urllib.error.HTTPError as error:
        require(error.code in {301, 302, 303, 307, 308}, "Artifact API did not supply a download redirect")
        location = error.headers.get("Location", "")
    else:
        raise ReuseMiss("Artifact API did not supply a download redirect")
    require(allowed_download(location), "Artifact download host is not approved")
    # The signed URL is fetched with a new request: no API token is forwarded.
    total, digest = 0, hashlib.sha256()
    try:
        with urllib.request.build_opener(ArtifactRedirect()).open(location, timeout=remaining_timeout(deadline)) as response, destination.open("xb") as stream:
            while data := response.read(1024 * 1024):
                remaining_timeout(deadline)
                total += len(data)
                require(total <= artifact["size_in_bytes"], "Artifact exceeds declared size")
                digest.update(data)
                stream.write(data)
        require(total == artifact["size_in_bytes"] and "sha256:" + digest.hexdigest() == artifact["digest"],
                "GitHub artifact digest mismatch")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def read_zip(path, *, maximum, max_file, max_entries, allowed):
    result, folded, parents, total = {}, set(), set(), 0
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        require(0 < len(infos) <= max_entries, "Archive entry count exceeds its bound")
        for info in infos:
            mode = stat.S_IFMT(info.external_attr >> 16)
            require(safe_name(info.filename) and allowed(info.filename) and info.filename.casefold() not in folded
                    and not info.is_dir() and mode in {0, stat.S_IFREG} and not info.flag_bits & 1,
                    "Unsafe, duplicate or unexpected archive member")
            name = info.filename.casefold()
            ancestors = {parent.as_posix() for parent in PurePosixPath(name).parents if parent.as_posix() != "."}
            require(name not in parents and not ancestors.intersection(folded), "Archive file/parent collision")
            require(0 <= info.file_size <= max_file, "Archive member exceeds its bound")
            total += info.file_size
            require(total <= maximum, "Expanded archive exceeds its bound")
            data = archive.read(info)
            require(len(data) == info.file_size, "Archive member size mismatch")
            result[info.filename] = data
            folded.add(info.filename.casefold())
            parents.update(ancestors)
    return result


def validate_run(run):
    require(isinstance(run, dict) and positive(run.get("id")) and positive(run.get("run_attempt")) and sha(run.get("head_sha"))
            and run.get("event") in {"push", "pull_request", "workflow_dispatch"}
            and run.get("path") == ".github/workflows/ci.yml"
            and (run.get("status"), run.get("conclusion")) == ("completed", "success"), "CI run is not an eligible successful producer")
    repository, head = run.get("repository", {}), run.get("head_repository", {})
    require(repository.get("full_name") == head.get("full_name") == REPOSITORY
            and positive(repository.get("id")) and repository["id"] == head.get("id"), "CI producer belongs to a fork or another repository")


def validate_job(document, run):
    require(isinstance(document, dict) and isinstance(document.get("jobs"), list)
            and all(isinstance(job, dict) and positive(job.get("id")) for job in document["jobs"]), "Invalid CI job response")
    jobs = document.get("jobs", [])
    require(type(document.get("total_count")) is int and document["total_count"] == len(jobs)
            and len({job["id"] for job in jobs}) == len(jobs), "CI job response is incomplete or duplicated")
    matches = [job for job in jobs if job.get("name") == "scientific"]
    require(len(matches) == 1, "Scientific CI job is missing or ambiguous")
    job = matches[0]
    require(job.get("run_id") == run["id"] and job.get("run_attempt") == run["run_attempt"]
            and job.get("head_sha") == run["head_sha"]
            and (job.get("status"), job.get("conclusion")) == ("completed", "success"), "Scientific CI job did not pass this attempt")
    for name in (*STEPS, *PRODUCER_STEPS):
        matches = [step for step in job.get("steps", []) if step.get("name") == name]
        require(len(matches) == 1 and (matches[0].get("status"), matches[0].get("conclusion")) == ("completed", "success"),
                "A required scientific CI step did not pass")
    return job


def artifact_for(document, run, tree, job):
    require(isinstance(document, dict) and isinstance(document.get("artifacts"), list)
            and all(isinstance(artifact, dict) for artifact in document["artifacts"]), "Invalid artifact list")
    artifacts = document.get("artifacts", [])
    require(type(document.get("total_count")) is int and document["total_count"] == len(artifacts), "Artifact list is incomplete")
    name = f"nipat-scientific-qualification-{run['run_attempt']}-{tree}"
    matches = [artifact for artifact in artifacts if artifact.get("name") == name]
    require(len(matches) == 1 and matches[0].get("expired") is False, "Scientific artifact is missing, expired or ambiguous")
    artifact = matches[0]
    origin = artifact.get("workflow_run", {})
    require(origin.get("id") == run["id"] and origin.get("head_sha") == run["head_sha"]
            and origin.get("repository_id") == origin.get("head_repository_id") == run["repository"]["id"],
            "Artifact belongs to another producer")
    created = datetime.fromisoformat(artifact["created_at"])
    require(datetime.fromisoformat(job["started_at"]) <= created <= datetime.fromisoformat(job["completed_at"]),
            "Artifact was not created during this scientific attempt")
    return artifact


def verify_bundle(artifact_zip, directory, run, source, image, fetch=fetch_json, *, deadline=None):
    outer = read_zip(artifact_zip, maximum=MAX_DOWNLOAD, max_file=MAX_TOTAL, max_entries=2,
                     allowed=lambda name: name in {DESCRIPTOR, ARCHIVE})
    require(set(outer) == {DESCRIPTOR, ARCHIVE} and len(outer[DESCRIPTOR]) <= MAX_DESCRIPTOR, "Scientific artifact files are incomplete")
    record = json.loads(outer[DESCRIPTOR])
    require(isinstance(record, dict) and set(record) == {
        "schema_version", "repository", "producer", "image", "environment", "steps", "archive", "entries"}
        and type(record["schema_version"]) is int and record["schema_version"] == 1 and record["repository"] == REPOSITORY
        and record["steps"] == list(STEPS) and record["image"] == image, "Scientific proof schema, image or gates differ")
    env = record["environment"]
    require(isinstance(env, dict) and env.get("python") == "3.12.10" and env.get("system") == "Linux"
            and env.get("machine") == "x86_64" and all(isinstance(env.get(tool), str) and env[tool] for tool in ("pdfinfo", "pdftoppm")),
            "Scientific producer environment is incomplete")
    producer = record["producer"]
    require(isinstance(producer, dict) and positive(producer.get("run_id")) and positive(producer.get("attempt"))
            and producer.get("run_id") == run["id"] and producer.get("attempt") == run["run_attempt"]
            and producer.get("event") == run["event"] and producer.get("head_sha") == run["head_sha"]
            and sha(producer.get("checkout_commit")) and producer.get("checkout_tree") == source["tree"],
            "Scientific producer identity or checkout tree differs")
    commit = fetch(f"git/commits/{producer['checkout_commit']}", deadline=deadline)
    require(commit.get("sha") == producer["checkout_commit"] and commit.get("tree", {}).get("sha") == source["tree"],
            "GitHub checkout tree does not match the consumer")
    if run["event"] == "pull_request":
        pull = producer.get("pull_request", {})
        require(positive(pull.get("number")) and sha(pull.get("base_sha")) and pull.get("head_sha") == run["head_sha"]
                and (not run.get("pull_requests") or any(item.get("number") == pull["number"] for item in run["pull_requests"]))
                and [parent.get("sha") for parent in commit.get("parents", [])] == [pull["base_sha"], run["head_sha"]],
                "PR checkout is not the recorded merge of the producer head and base")
        # run.pull_requests head/base fields can change after the run. The exact
        # immutable merge parents above bind the historical checkout instead.
    else:
        require(producer["checkout_commit"] == run["head_sha"] and "pull_request" not in producer,
                "Push/manual checkout differs from its producer head")
    archive = record["archive"]
    require(isinstance(archive, dict) and archive == {"file": ARCHIVE, "size": len(outer[ARCHIVE]), "sha256": sha256(outer[ARCHIVE])},
            "Scientific archive digest differs")
    inner = directory / ARCHIVE
    inner.write_bytes(outer[ARCHIVE])
    evidence = read_zip(inner, maximum=MAX_TOTAL, max_file=MAX_FILE, max_entries=MAX_ENTRIES, allowed=selected_path)
    for data in evidence.values():
        data.decode("utf-8-sig")
    entries = record["entries"]
    require(isinstance(entries, list) and len(entries) == len(evidence)
            and all(isinstance(entry, dict) and set(entry) == {"path", "size", "sha256"}
                    and type(entry["size"]) is int and sha(entry["sha256"], 64) for entry in entries),
            "Scientific inventory is incomplete")
    expected = [{"path": name, "size": len(data), "sha256": sha256(data)} for name, data in evidence.items()]
    require(entries == expected, "Scientific inventory does not match raw evidence bytes")
    verify_required(evidence, image)
    return record, evidence


def restore_files(evidence, runner_temp):
    require(runner_temp.is_dir() and not runner_temp.is_symlink(), "Invalid restore root")
    targets = [runner_temp / name for name in RESTORE_DIRECTORIES]
    require(all(not path.exists() and not path.is_symlink() for path in targets), "Scientific restore target already exists")
    installed = []
    with tempfile.TemporaryDirectory(prefix=".nipat-reuse-", dir=runner_temp) as temporary:
        staging = Path(temporary)
        for name, data in evidence.items():
            require(selected_path(name), "Unsafe restore path")
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        try:
            for target in targets:
                require(not target.exists() and not target.is_symlink(), "Scientific restore target appeared concurrently")
                (staging / target.name).rename(target)
                installed.append(target)
        except BaseException:
            for target in reversed(installed):
                shutil.rmtree(target)
            raise


def consumer_identity():
    result = {key: os.environ.get(variable) for key, variable in (
        ("repository", "GITHUB_REPOSITORY"), ("event", "GITHUB_EVENT_NAME"), ("workflow_ref", "GITHUB_WORKFLOW_REF"))}
    for key, variable in (("run_id", "GITHUB_RUN_ID"), ("attempt", "GITHUB_RUN_ATTEMPT")):
        raw = os.environ.get(variable, "")
        result[key] = int(raw) if re.fullmatch(r"[1-9][0-9]*", raw) else None
    return result


def restore(image, output, runner_temp, *, fetch=fetch_json, download=download_artifact):
    deadline = time.monotonic() + SEARCH_BUDGET_SECONDS
    receipt = {"schema_version": 1, "reused": False, "reason": "No matching successful CI scientific qualification",
               "consumer": consumer_identity()}
    try:
        consumer = receipt["consumer"]
        require(consumer["repository"] == REPOSITORY and positive(consumer["run_id"]) and positive(consumer["attempt"])
                and consumer["event"] == "workflow_dispatch" and isinstance(consumer["workflow_ref"], str)
                and consumer["workflow_ref"].startswith(REPOSITORY + "/.github/workflows/windows-installer.yml@refs/heads/"),
                "Scientific reuse requires an identified installer workflow in this repository")
        source, identity = checkout(), image_identity(image)
        require(platform.python_version() == "3.12.10" and platform.system() == "Linux" and platform.machine() == "x86_64",
                "Consumer must use the pinned Linux Python host")
        receipt["consumer"].update(checkout=source, image=identity)
        runs = fetch("actions/workflows/ci.yml/runs?status=completed&per_page=30", deadline=deadline).get("workflow_runs")
        require(isinstance(runs, list) and len(runs) <= 30, "Unexpected CI history response")
        misses = []
        for candidate in runs:
            remaining_timeout(deadline)
            try:
                validate_run(candidate)
                run_id, attempt = candidate["id"], candidate["run_attempt"]
                artifacts = fetch(f"actions/runs/{run_id}/artifacts?per_page=100", deadline=deadline)
                name = f"nipat-scientific-qualification-{attempt}-{source['tree']}"
                require(any(artifact.get("name") == name for artifact in artifacts.get("artifacts", [])), "No artifact for this source tree")
                job = validate_job(fetch(f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100", deadline=deadline), candidate)
                artifact = artifact_for(artifacts, candidate, source["tree"], job)
                with tempfile.TemporaryDirectory(prefix="nipat-scientific-proof-") as temporary:
                    directory = Path(temporary)
                    downloaded = directory / "artifact.zip"
                    download(artifact, downloaded, deadline=deadline)
                    record, evidence = verify_bundle(downloaded, directory, candidate, source, identity, fetch, deadline=deadline)
                    remaining_timeout(deadline)
                    require(checkout() == source and image_identity(image) == identity, "Consumer changed during scientific restore")
                    restore_files(evidence, runner_temp)
                receipt.update(reused=True, reason="Identical Git tree and immutable Docker image; all seven CI gates passed",
                               producer=record["producer"], producer_environment=record["environment"],
                               scientific_job_id=job["id"], artifact={"id": artifact["id"], "name": artifact["name"],
                               "digest": artifact["digest"]}, evidence_archive=record["archive"], evidence_entries=len(evidence))
                break
            except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
                # Never print signed URLs, response bodies or credentials.
                misses.append({"run_id": candidate.get("id") if isinstance(candidate, dict) else None,
                               "reason": error_reason(error)})
                if isinstance(error, OSError):
                    break  # An unavailable API/download must not cause 30 timeout retries.
        if not receipt["reused"]:
            receipt["candidates_checked"] = misses
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        receipt["reason"] = error_reason(error)
    output.mkdir(parents=True, exist_ok=True)
    require(not output.is_symlink() and not (output / "reuse.json").is_symlink(), "Scientific reuse receipt path is a symlink")
    (output / "reuse.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("seal", "restore"))
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runner-temp", type=Path, default=os.environ.get("RUNNER_TEMP"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    require(args.runner_temp is not None, "RUNNER_TEMP is required")
    if args.operation == "seal":
        require(args.output is None, "Seal does not write workflow outputs")
        record = seal(args.image, args.output_dir, args.runner_temp)
        print(f"Sealed {len(record['entries'])} raw scientific evidence files for CI run {record['producer']['run_id']}.")
    else:
        require(args.output is not None, "Restore requires the workflow output file")
        receipt = restore(args.image, args.output_dir, args.runner_temp)
        with args.output.open("a", encoding="utf-8") as stream:
            stream.write(f"reused={str(receipt['reused']).lower()}\n")
        print(f"Scientific reuse {'hit' if receipt['reused'] else 'miss'}: {receipt['reason']}")


if __name__ == "__main__":
    main()
