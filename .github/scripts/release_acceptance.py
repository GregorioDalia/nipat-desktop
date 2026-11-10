"""Bind an explicit desktop or research acceptance policy to one verified build."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile
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
RELIABILITY_DIGESTS = {"qualification_evidence_sha256", "linux_upgrade_check_sha256"}
RELIABILITY_RESEARCH_FIELDS = REVIEWED_RESEARCH_FIELDS | RELIABILITY_DIGESTS
MACOS_DIGESTS = {"macos_arm64_installer_sha256", "macos_x86_64_installer_sha256"}
MULTIPLATFORM_RESEARCH_FIELDS = RELIABILITY_RESEARCH_FIELDS | MACOS_DIGESTS | {"macos_validation"}
SCIENTIFIC_RESEARCH_FIELDS = MULTIPLATFORM_RESEARCH_FIELDS | {"scientific_equivalence"}
REVISED_R_SOURCE_SCOPE = "reviewed-operative-changes-with-tested-r-equivalence-v1"
R_REFERENCE_COMMIT = "eafadf7002a9c7d7c1b9af9ccafc47d698a059e5"
R_REFERENCE_ROOT = "tests/reference_r/0.8.5"
SNP2_REFERENCE = {
    "repository": "lpistacchia/NEWPAT",
    "source_commit": "ce59f4beeeec710b1b42d425cb87d7aad729f71d",
    "path": "SNPcall/SNPcall.R",
    "frozen_path": "tests/reference_r/2.0/SNPcall.R",
    # Independently pinned upstream bytes, never supplied by the candidate report.
    "sha256": "855a96c897d1bcb8ce30b725baecfa739d01be323252da07554a63aa66965da4",
}
SNP2_CASES = dict.fromkeys(
    ("snp-varied-qualities", "snp-overlapping-windows", "snp-zero-coverage"), "snp-call")
PRESENTATION_HELPER = "tests/r_optimization/presentation/check_plots.R"
PRESENTATION_SOURCE = "src/nipat_scientific/plots.R"
R_WORKFLOWS = {
    "scientific/vendor/DNPcall/DNPcall.R": "dnp-call",
    "scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R": "cpi",
    "scientific/vendor/NEWPAT/SNPcall/SNPcall.R": "snp-call",
    "scientific/vendor/NEWPAT/contamination/detect_contamination.R": "contamination",
}
R_CASES = {
    **dict.fromkeys(("dnp-single", "dnp-multi", "dnp-parallel", "dnp-varied-qualities"), "dnp-call"),
    **dict.fromkeys(("snp-edge", "snp-extra-columns"), "snp-call"),
    **dict.fromkeys(("cpi-all", "cpi-panels", "cpi-zero-error", "cpi-shared-parents"), "cpi"),
    **dict.fromkeys(("contamination-batch", "contamination-single", "contamination-panel-only"), "contamination"),
}
R_REQUIRED_PDFS = {
    "dnp-single": 5, "dnp-multi": 10, "dnp-parallel": 10, "dnp-varied-qualities": 5,
    "cpi-all": 4, "cpi-panels": 4, "cpi-zero-error": 4, "cpi-shared-parents": 6,
}
R_HELPERS = {
    "tests/r_optimization/cpi/check_core.R", "tests/r_optimization/dnp/check_blocks.R",
    "tests/r_optimization/snp/check_reads.R", "tests/r_optimization/performance/check_costs.R",
}
R_AUDIT_CASES = {
    **dict.fromkeys(("dnp-blocks-1", "dnp-blocks-2", "dnp-blocks-3", "dnp-numeric-blocks",
                    "dnp-repeated-qname-compatibility", "dnp-multi-blocks-2", "dnp-multi-blocks-3",
                    "dnp-multi-blocks-6"), "dnp-call"),
    **dict.fromkeys(("cpi-single-intervals", "cpi-single-cutoffs"), "cpi"),
}
R_AUDIT_HELPERS = {
    "tests/r_optimization/dnp/check_parallel_samples.R", "tests/r_optimization/dnp/check_parallel_blocks.R",
    "tests/r_optimization/dnp/check_reader.R", "tests/r_optimization/dnp/check_reader_ranges.R",
    "tests/r_optimization/parallel/check_budget.R", "tests/r_optimization/parallel/check_acquisition_budget.R",
    "tests/r_optimization/contamination/check_parallel.R",
}
# Frozen multi-BAM fixtures emit four plots per sample plus two shared plots
# (coverage UpSet and unassigned genotypes), as observed with the 0.8.5 oracle.
R_MULTIBAM_PDFS = {"dnp-multi-blocks-2": 10, "dnp-multi-blocks-3": 14, "dnp-multi-blocks-6": 26}
SOURCE_EQUIVALENCE_SCOPE = "distributed-operative-sources-v1"
REVIEWED_SOURCE_SCOPE = "scientific-runtime-equivalence-with-reviewed-client-changes-v1"
RELIABILITY_SOURCE_SCOPE = "reviewed-operative-changes-with-unchanged-r-v1"
MULTIPLATFORM_SOURCE_SCOPE = "reviewed-operative-changes-with-unchanged-vendored-r-v1"
BASELINE_OBSERVATIONS = {
    "installation_ready", "runtime_diagnostics", "scientific_self_tests", "dnp_sample_analysis",
}
WORKFLOW_BASELINE_OBSERVATIONS = BASELINE_OBSERVATIONS | {"automatic_workflow_sample_analysis"}
REVIEWABLE_CLIENT_PREFIXES = ("src/nipat/", "installer/windows/", "installer/linux/", "scripts/", "tests/")
REVIEWABLE_CLIENT_FILES = {"pyproject.toml", "1_SETUP.cmd", "2_AVVIA.cmd", "nipat.cmd"}
REVIEWABLE_OPERATIVE_PREFIXES = (
    "src/", "engine/", "installer/", "scripts/", "tests/", "docker/", "config/",
)
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


def reliability_contract(version):
    match = re.fullmatch(r"0\.7\.([0-9]+)(?:(?:a|b|rc)[0-9]+)?", version or "")
    return bool(match and int(match[1]) >= 2) or multiplatform_contract(version)


def multiplatform_contract(version):
    match = re.fullmatch(r"0\.8\.([0-9]+)(?:(?:a|b|rc)[0-9]+)?", version or "")
    return bool(match and int(match[1]) >= 2)


def revised_r_contract(version):
    match = re.fullmatch(r"0\.8\.([0-9]+)(?:(?:a|b|rc)[0-9]+)?", version or "")
    return bool(match and int(match[1]) >= 9)


def audited_r_contract(version):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version or "")
    return bool(match and tuple(map(int, match.groups())) >= (0, 8, 20))


def snp2_contract(version):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(?:a|b|rc)[0-9]+)?", version or "")
    return bool(match and tuple(map(int, match.groups())) >= (0, 8, 30))


def verify_presentation_variants(case):
    """Bind corrected plots to serial results and retained parallel renderings."""
    variants = case.get("execution_variants")
    require(isinstance(variants, dict) and "candidate" in variants,
            "Scientific presentation execution variants are missing")
    require(case.get("plots_comparison") == "renderable-and-bounded",
            "Scientific presentation must identify structural serial validation")
    if case["plots"]:
        require(len(variants) >= 2,
                "Scientific PDF evidence lacks a serial-versus-parallel comparison")
    for name, variant in variants.items():
        require(isinstance(name, str) and bool(name) and isinstance(variant, dict)
                and variant.get("status") == "passed"
                and variant.get("unrounded_r_values") == "identical"
                and variant.get("table_sha256") == case["table_sha256"]
                and variant.get("plots") == case["plots"],
                "Scientific presentation variant differs from serial scientific results")
        expected = "renderable-and-bounded" if name == "candidate" else "candidate-serial-exact-pixels"
        require(variant.get("plots_comparison") == expected,
                "Scientific presentation variant has an unsupported PDF comparison claim")
        configuration = variant.get("execution_configuration")
        require(isinstance(configuration, dict)
                and configuration.get("requested_mode") == ("serial" if name == "candidate" else "auto")
                and (configuration.get("requested_max_workers") is None
                     or type(configuration["requested_max_workers"]) is int
                     and configuration["requested_max_workers"] >= 1),
                "Scientific presentation variant has no matching execution configuration")
        if name == "candidate":
            require(configuration.get("requested_max_workers") is None,
                    "Serial scientific presentation has conflicting execution settings")


def verify_multibam_variants(case):
    variants = case.get("execution_variants")
    expected = {"candidate": ("serial", None), "auto": ("auto", None),
                "manual-2": ("auto", 2), "manual-4": ("auto", 4), "manual-4-repeat": ("auto", 4)}
    require(isinstance(variants, dict) and set(variants) == set(expected),
            "Multi-BAM serial/auto/manual/repeat comparisons are missing")
    for name, (mode, cap) in expected.items():
        comparison = variants[name]
        require(isinstance(comparison, dict) and comparison.get("status") == "passed"
                and comparison.get("unrounded_r_values") == "identical"
                and comparison.get("table_sha256") == case["table_sha256"]
                and comparison.get("plots") == case["plots"],
                "Multi-BAM variant does not preserve exact scientific results")
        parallel = comparison.get("parallel_execution")
        require(isinstance(parallel, dict) and parallel.get("requested_mode") == mode
                and parallel.get("requested_max_workers") == cap,
                "Multi-BAM variant has different execution settings")
        planned = parallel.get("maximum_planned_workers")
        observed = parallel.get("maximum_observed_child_workers")
        require(type(planned) is int and planned >= 1 and type(observed) is int and 0 <= observed <= planned
                and (cap is None or planned <= cap), "Multi-BAM observed concurrency exceeds its budget")
        if name == "candidate":
            require(planned == 1 and observed == 0 and parallel.get("simultaneous_child_workers") is False,
                    "Serial Multi-BAM evidence contains child concurrency")
        else:
            require(observed >= 2 and parallel.get("simultaneous_child_workers") is True
                    and parallel.get("overlapping_workers_required") is True,
                    "Parallel Multi-BAM evidence has no observed concurrent workers")
        if name == "manual-4-repeat":
            require(comparison.get("deterministic_repeat_of") == "manual-4",
                    "Multi-BAM deterministic repeat is missing")


def reviewable_path(path, *, reliability=False, multiplatform=False, revised_r=False):
    if revised_r and path in set(R_WORKFLOWS) | {"scientific/SHA256SUMS"}:
        return True
    if reliability:
        # The Python preparation, orchestration and packaging may evolve, but
        # this research policy never authorizes a change to the R algorithms.
        # Schema 5 also reviews Git's checkout normalization rules: they affect
        # the exact bytes packaged on each host and must not be silently exempt.
        metadata = {".gitattributes"} if multiplatform else set()
        return ((PurePosixPath(path).suffix.casefold() != ".r"
                 or multiplatform and not path.startswith("scientific/vendor/"))
                and (path in REVIEWABLE_CLIENT_FILES | {"compose.yaml", ".gitignore"} | metadata
                     or path.startswith(REVIEWABLE_OPERATIVE_PREFIXES)))
    return path in REVIEWABLE_CLIENT_FILES or path.startswith(REVIEWABLE_CLIENT_PREFIXES)


def acceptance_path(version):
    require(isinstance(version, str) and (re.fullmatch(r"0\.[567]\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version)
                                         or multiplatform_contract(version)),
            "Joint publication supports the 0.5–0.7 and official 0.8.2+ desktop contracts")
    return f".github/release-acceptance/v{version}.json"


def identity(installer_set):
    result = {
        "version": installer_set["version"],
        "source_commit": installer_set["source_commit"],
        "installer_manifest_sha256": installer_set["installer_manifest_sha256"],
        "scientific_archive_sha256": installer_set["scientific_archive"]["sha256"],
        "windows_installer_sha256": installer_set["windows"]["sha256"],
        "linux_installer_sha256": installer_set["linux"]["sha256"],
    }
    if multiplatform_contract(installer_set["version"]):
        for architecture in ("arm64", "x86_64"):
            require(isinstance(installer_set.get(f"macos_{architecture}"), dict),
                    "Acceptance requires both native macOS packages")
            result[f"macos_{architecture}_installer_sha256"] = installer_set[f"macos_{architecture}"]["sha256"]
    return result


def template(installer_set, run_id):
    require(type(run_id) is int and run_id > 0, "Invalid build run ID")
    fields = identity(installer_set)
    acceptance_path(fields["version"])
    require(isinstance(fields["source_commit"], str)
            and re.fullmatch(r"[0-9a-f]{40}", fields["source_commit"]), "Invalid source commit")
    for field in DIGESTS | (MACOS_DIGESTS if multiplatform_contract(fields["version"]) else set()):
        require(isinstance(fields[field], str) and re.fullmatch(r"[0-9a-f]{64}", fields[field]),
                f"Invalid digest: {field}")
    if multiplatform_contract(fields["version"]):
        record = {
            "schema_version": 5, **fields, "build_run_id": run_id, "decision": "pending",
            "scope": "pre-1.0-research", "review": {"reviewer": "", "reviewed_at": "", "evidence": []},
            "observed_baseline": {"source_commit": "", "observations": [], "evidence": [],
                                  "role": "historical-platform-evidence",
                                  "source_comparison_scope": MULTIPLATFORM_SOURCE_SCOPE},
            "reviewed_source_changes": [], "deferred_desktop_scenarios": sorted(SCENARIOS),
            "domain_validation": "pending-domain-researchers", "qualification_evidence_sha256": "",
            "linux_upgrade_check_sha256": installer_set.get("linux_upgrade_check", {}).get("sha256", ""),
            "macos_validation": {architecture: {"status": "not-performed", "evidence": []}
                                 for architecture in ("arm64", "x86_64")},
        }
        if revised_r_contract(fields["version"]):
            record["schema_version"] = 6
            record["observed_baseline"]["source_comparison_scope"] = REVISED_R_SOURCE_SCOPE
            record["scientific_equivalence"] = {
                "reference_source_commit": R_REFERENCE_COMMIT,
                "report_path": "", "report_sha256": "", "runtime_image": "",
            }
        return record
    return {
        "schema_version": 1, **fields, "build_run_id": run_id, "decision": "pending",
        "tests": {name: {"result": "pending", "tester": "", "tested_at": "", "evidence": []}
                  for name in sorted(SCENARIOS)},
    }


def validate(record, version, commit, run_id, installer_set=None):
    """Require a committed review under the record's explicit acceptance policy."""
    acceptance_path(version)
    require(not revised_r_contract(version) or isinstance(record, dict)
            and type(record.get("schema_version")) is int and record["schema_version"] == 6,
            "Releases from 0.8.9 require scientific equivalence acceptance schema 6")
    if isinstance(record, dict) and type(record.get("schema_version")) is int and record["schema_version"] in (2, 3, 4, 5, 6):
        validate_research(record, version, commit, run_id, installer_set)
        return
    require(not multiplatform_contract(version), "Official 0.8.2+ releases require four-platform acceptance schema 5")
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
    revised_r = isinstance(record, dict) and type(record.get("schema_version")) is int and record["schema_version"] == 6
    multiplatform = isinstance(record, dict) and type(record.get("schema_version")) is int and record["schema_version"] in (5, 6)
    reliability = isinstance(record, dict) and type(record.get("schema_version")) is int and record["schema_version"] in (4, 5, 6)
    reviewed_delta = isinstance(record, dict) and type(record.get("schema_version")) is int and record["schema_version"] in (3, 4, 5, 6)
    schema = 6 if revised_r else 5 if multiplatform else (4 if reliability else (3 if reviewed_delta else 2))
    require(not revised_r or revised_r_contract(version), "Revised R acceptance is available from 0.8.9 only")
    minor = "7" if reviewed_delta else "6"
    require(multiplatform_contract(version) if multiplatform else
            isinstance(version, str) and re.fullmatch(rf"0\.{minor}\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version),
            f"Research acceptance schema {schema} does not support this release version")
    if reliability:
        require(reliability_contract(version), "Reliability acceptance is available from 0.7.2 only")
    elif reviewed_delta:
        require(not reliability_contract(version),
                "Research releases from 0.7.2 require reliability acceptance schema 4")
    expected_fields = (SCIENTIFIC_RESEARCH_FIELDS if revised_r else MULTIPLATFORM_RESEARCH_FIELDS if multiplatform else RELIABILITY_RESEARCH_FIELDS if reliability else
                       REVIEWED_RESEARCH_FIELDS if reviewed_delta else RESEARCH_FIELDS)
    require(isinstance(record, dict) and set(record) == expected_fields
            and type(record["schema_version"]) is int and record["schema_version"] == schema,
            "Research acceptance record fields are invalid")
    require(record["version"] == version and record["source_commit"] == commit
            and isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit)
            and type(record["build_run_id"]) is int and type(run_id) is int
            and run_id > 0 and record["build_run_id"] == run_id,
            "Acceptance belongs to a different version, source or build run")
    for field in DIGESTS | (RELIABILITY_DIGESTS if reliability else set()) | (MACOS_DIGESTS if multiplatform else set()):
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
    scope_field = "source_comparison_scope" if reliability else "source_equivalence_scope"
    baseline_fields = {"source_commit", "observations", "evidence", scope_field}
    if reliability:
        baseline_fields.add("role")
    require(isinstance(baseline, dict) and set(baseline) == baseline_fields,
            "Invalid observed baseline fields")
    if reliability:
        require(baseline["role"] == "historical-platform-evidence",
                "The baseline cannot attest installation of the changed candidate")
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
    expected_scope = (REVISED_R_SOURCE_SCOPE if revised_r else MULTIPLATFORM_SOURCE_SCOPE if multiplatform else RELIABILITY_SOURCE_SCOPE if reliability else
                      REVIEWED_SOURCE_SCOPE if reviewed_delta else SOURCE_EQUIVALENCE_SCOPE)
    require(baseline[scope_field] == expected_scope,
            "Unsupported baseline source equivalence scope")
    review_evidence(baseline["evidence"], "Observed baseline evidence")
    deferred = record["deferred_desktop_scenarios"]
    require(isinstance(deferred, list) and all(isinstance(item, str) for item in deferred)
            and len(deferred) == len(SCENARIOS) and set(deferred) == SCENARIOS,
            "Research acceptance must explicitly defer all six desktop scenarios")
    require(record["domain_validation"] == ("pending-domain-researchers" if reviewed_delta else "planned-for-0.7"),
            "Research acceptance cannot claim completed domain validation")
    if multiplatform:
        platforms = record["macos_validation"]
        require(isinstance(platforms, dict) and set(platforms) == {"arm64", "x86_64"},
                "Both macOS runtime validation statuses must be explicit")
        for architecture, observation in platforms.items():
            require(isinstance(observation, dict) and set(observation) == {"status", "evidence"},
                    f"Invalid macOS {architecture} runtime validation record")
            if observation["status"] == "passed":
                review_evidence(observation["evidence"], f"macOS {architecture} runtime evidence")
            else:
                require(observation["status"] == "not-performed" and observation["evidence"] == [],
                        "Unperformed macOS validation cannot imply a successful runtime test")
    if revised_r:
        validate_scientific_record(record["scientific_equivalence"])
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
                    and reviewable_path(path, reliability=reliability, multiplatform=multiplatform, revised_r=revised_r),
                    ("Only known scientific scripts and explicit operative sources can be reviewed" if revised_r
                     else "Only operative source changes outside protected vendored R can be reviewed" if multiplatform
                     else "Only explicit non-R operative source changes can be reviewed" if reliability
                     else "Only explicit client, installer and test source changes can be reviewed"))
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
        if reliability:
            upgrade = installer_set.get("linux_upgrade_check", {})
            require(upgrade.get("sha256") == record["linux_upgrade_check_sha256"],
                    "Acceptance does not identify the verified cross-version upgrade report")



def valid_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def safe_evidence_path(value):
    return (isinstance(value, str) and bool(value) and PurePosixPath(value).as_posix() == value
            and not PurePosixPath(value).is_absolute() and ".." not in PurePosixPath(value).parts
            and "\\" not in value and ":" not in value and not any(c.isspace() for c in value))


def validate_scientific_record(evidence):
    require(isinstance(evidence, dict) and set(evidence) == {
        "reference_source_commit", "report_path", "report_sha256", "runtime_image",
    }, "Invalid scientific equivalence record fields")
    require(evidence["reference_source_commit"] == R_REFERENCE_COMMIT,
            "Scientific equivalence requires the frozen 0.8.5 reference")
    require(safe_evidence_path(evidence["report_path"])
            and evidence["report_path"].startswith("scientific/")
            and PurePosixPath(evidence["report_path"]).name == "r-equivalence.json",
            "Scientific equivalence must identify its retained qualification report")
    require(valid_digest(evidence["report_sha256"]), "Invalid scientific equivalence report digest")
    require(isinstance(evidence["runtime_image"], str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", evidence["runtime_image"]),
            "Scientific equivalence requires an immutable runtime image ID")


def verify_scientific_equivalence(record, evidence_directory, manifest, read_source):
    """Bind reviewed R results to Git, the retained build evidence and packaged image.

    The caller must first verify the qualification archive and installer set.
    This check adds scientific content validation; it does not turn synthetic
    equivalence into domain validation or claim execution on users' desktops.
    """
    require(record.get("schema_version") == 6, "Scientific evidence requires acceptance schema 6")
    validate(record, record["version"], record["source_commit"], record["build_run_id"])
    evidence = record["scientific_equivalence"]
    require(manifest.get("source_commit") == record["source_commit"]
            and manifest.get("version") == record["version"]
            and manifest.get("runtime_image") == evidence["runtime_image"],
            "Scientific equivalence does not identify the packaged source and image")
    archive = Path(evidence_directory) / "qualification-evidence.zip"
    require(archive.is_file() and not archive.is_symlink()
            and hashlib.sha256(archive.read_bytes()).hexdigest() == record["qualification_evidence_sha256"],
            "Scientific qualification archive differs from the accepted build")
    try:
        with zipfile.ZipFile(archive) as handle:
            matching = [entry for entry in handle.infolist() if entry.filename == evidence["report_path"]]
            require(len(matching) == 1 and 0 < matching[0].file_size <= 8 * 1024 * 1024,
                    "Missing, duplicate or oversized scientific equivalence report")
            raw = handle.read(matching[0])
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise ValueError("Cannot read retained scientific equivalence report") from error
    require(hashlib.sha256(raw).hexdigest() == evidence["report_sha256"],
            "Scientific equivalence report bytes differ from the review")
    try:
        report = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise ValueError("Invalid scientific equivalence report JSON") from error
    require(isinstance(report, dict) and type(report.get("schema_version")) is int
            and report["schema_version"] == 1 and report.get("status") == "passed"
            and report.get("inputs_unchanged") is True
            and report.get("runtime_image") == evidence["runtime_image"],
            "Scientific equivalence did not pass in the packaged image with unchanged inputs")
    snp2 = snp2_contract(record["version"])
    audited = audited_r_contract(record["version"]) or snp2
    comparison_policy = {"table_bytes": "exact", "unrounded_r": "identical",
                         "pdf_pixels": "exact", "pdf_metadata": "excluded"}
    if snp2:
        comparison_policy.update(pdf_pixels="candidate-serial-vs-parallel",
                                 pdf_reference="structural-and-reviewed-presentation")
    require(report.get("comparison") == comparison_policy,
            "Scientific equivalence must include exact tables, unrounded R values and PDF pixels")

    def source(commit, path):
        try:
            data = read_source(commit, path)
        except (OSError, KeyError, RuntimeError, subprocess.CalledProcessError) as error:
            raise ValueError(f"Cannot read scientific equivalence source: {commit}:{path}") from error
        require(isinstance(data, bytes), "Scientific equivalence requires exact source bytes")
        return data

    commit = record["source_commit"]
    reference = report.get("reference")
    require(isinstance(reference, dict) and set(reference) == {
        "schema_version", "version", "source_commit", "source_tag", "files",
    } and type(reference["schema_version"]) is int and reference["schema_version"] == 1
            and reference["version"] == "0.8.5" and reference["source_tag"] == "v0.8.5"
            and reference["source_commit"] == R_REFERENCE_COMMIT,
            "Scientific report does not identify the immutable 0.8.5 source")
    expected_paths = set(R_WORKFLOWS) | {
        "docker/scientific-runtime/verify-packages.R", "src/nipat_scientific/presentation.R",
    }
    files = reference["files"]
    require(isinstance(files, list) and len(files) == len(expected_paths)
            and all(isinstance(item, dict) and set(item) == {"path", "sha256"}
                    and isinstance(item["path"], str) and valid_digest(item["sha256"]) for item in files)
            and {item["path"] for item in files} == expected_paths,
            "Scientific reference inventory is incomplete")
    for item in files:
        original = source(R_REFERENCE_COMMIT, item["path"])
        require(hashlib.sha256(original).hexdigest() == item["sha256"]
                and source(commit, R_REFERENCE_ROOT + "/" + item["path"]) == original,
                "Frozen scientific reference differs from the released 0.8.5 source")
    try:
        frozen_manifest = json.loads(source(commit, R_REFERENCE_ROOT + "/manifest.json"))
    except (ValueError, UnicodeError) as error:
        raise ValueError("Invalid frozen scientific reference manifest") from error
    require(frozen_manifest == reference, "Scientific report differs from the candidate's frozen reference manifest")
    if snp2:
        require(report.get("snp_reference") == SNP2_REFERENCE,
                "Scientific report does not identify the immutable SNPcall 2.0 source")
        require(hashlib.sha256(source(commit, SNP2_REFERENCE["frozen_path"])).hexdigest()
                == SNP2_REFERENCE["sha256"],
                "Frozen SNPcall 2.0 reference differs from the pinned upstream bytes")
        supporting = report.get("supporting_source_sha256")
        require(isinstance(supporting, dict) and supporting.get(PRESENTATION_SOURCE)
                == hashlib.sha256(source(commit, PRESENTATION_SOURCE)).hexdigest(),
                "Scientific presentation evidence used different plotting sources")
    candidate_hashes = {path: hashlib.sha256(source(commit, path)).hexdigest() for path in R_WORKFLOWS}
    require(report.get("candidate_r_sha256") == candidate_hashes,
            "Scientific equivalence was performed on different candidate R sources")
    try:
        manifest_rows = [line.split() for line in source(commit, "scientific/SHA256SUMS").decode("ascii").splitlines()
                         if line.strip()]
    except UnicodeError as error:
        raise ValueError("Invalid scientific source hash manifest") from error
    require(len(manifest_rows) == len(candidate_hashes)
            and all(len(row) == 2 for row in manifest_rows)
            and {"scientific/" + row[1]: row[0] for row in manifest_rows} == candidate_hashes,
            "Scientific source hash manifest differs from the tested candidate R sources")

    cases = report.get("cases")
    require(isinstance(cases, list) and all(isinstance(case, dict) for case in cases),
            "Scientific differential cases are missing")
    names = [case.get("case") for case in cases]
    required_cases = {**R_CASES, **(R_AUDIT_CASES if audited else {}), **(SNP2_CASES if snp2 else {})}
    require(all(isinstance(name, str) and name for name in names) and len(set(names)) == len(names)
            and set(required_cases) <= set(names), "Required scientific differential cases are missing or duplicated")
    plots_verified = 0
    for case in cases:
        require(case.get("status") == "passed" and case.get("unrounded_r_values") == "identical"
                and case.get("workflow") in set(R_WORKFLOWS.values())
                and (case["case"] not in required_cases or case["workflow"] == required_cases[case["case"]]),
                "A scientific differential case failed or has a different workflow")
        if snp2:
            expected_reference = "SNPcall 2.0" if case["workflow"] == "snp-call" else "NIPAT 0.8.5"
            require(case.get("scientific_reference") == expected_reference,
                    "Scientific differential case used the wrong algorithm reference")
        tables = case.get("table_sha256")
        require(isinstance(tables, dict) and tables
                and all(safe_evidence_path(name) and valid_digest(value) for name, value in tables.items()),
                "Scientific differential table evidence is incomplete")
        plots = case.get("plots")
        require(isinstance(plots, dict)
                and len(plots) >= R_REQUIRED_PDFS.get(case["case"], 0),
                "Scientific PDF comparison evidence is missing or incomplete for a required case")
        for name, plot in plots.items():
            require(safe_evidence_path(name) and isinstance(plot, dict)
                    and type(plot.get("pages")) is int and plot["pages"] > 0
                    and type(plot.get("raster_dpi")) is int and plot["raster_dpi"] >= 36
                    and isinstance(plot.get("page_sha256"), dict)
                    and len(plot["page_sha256"]) == plot["pages"]
                    and all(safe_evidence_path(page) and valid_digest(value)
                            for page, value in plot["page_sha256"].items()),
                    "Scientific PDF pixel comparison evidence is incomplete")
            if snp2:
                dimensions = plot.get("page_size_points")
                require(isinstance(dimensions, list) and len(dimensions) == 2
                        and all(type(value) in (int, float) and 0 < value <= 1440 for value in dimensions),
                        "Scientific PDF dimensions are missing or exceed the reviewed presentation bounds")
            plots_verified += 1
        if snp2:
            verify_presentation_variants(case)
        if audited and case["case"] in R_MULTIBAM_PDFS:
            require(len(plots) >= R_MULTIBAM_PDFS[case["case"]],
                    "Multi-BAM PDF comparisons are incomplete")
            verify_multibam_variants(case)
    require(plots_verified > 0, "Scientific equivalence contains no rendered PDF comparisons")
    helpers = report.get("helpers")
    require(isinstance(helpers, list) and all(isinstance(item, dict) for item in helpers),
            "Scientific focused comparisons are missing")
    paths = [item.get("path") for item in helpers]
    required_helpers = (R_HELPERS | (R_AUDIT_HELPERS if audited else set())
                        | ({PRESENTATION_HELPER} if snp2 else set()))
    require(all(safe_evidence_path(path) and path.startswith("tests/r_optimization/") for path in paths)
            and len(set(paths)) == len(paths) and required_helpers <= set(paths),
            "Required scientific focused comparisons are missing or duplicated")
    for helper in helpers:
        require(helper.get("status") == "passed" and helper.get("sha256") ==
                hashlib.sha256(source(commit, helper["path"])).hexdigest(),
                "Scientific focused comparison failed or used different test sources")
    return {"source_commit": commit, "reference_source_commit": R_REFERENCE_COMMIT,
            **({"snp_reference": SNP2_REFERENCE} if snp2 else {}),
            "runtime_image": evidence["runtime_image"], "report_sha256": evidence["report_sha256"],
            "candidate_r_sha256": candidate_hashes, "cases_verified": len(cases),
            "focused_scripts_verified": len(helpers), "pdfs_verified": plots_verified,
            "scope": "synthetic-equivalence-only", "domain_validation_claimed": False}

def verify_baseline(record, read_source):
    """Compare operative source bytes; this does not assert installer or image identity.

    Markdown documentation and .github maintenance/CI/release procedures are not
    executable inputs of the installed application. The allowlist is compared as
    a normalized inventory. Schema 2 only exempts removal of two obsolete signing
    helpers. Schema 3 requires an exact hash review for permitted client changes
    and keeps scientific, engine and runtime sources immutable. Schema 4 reviews
    non-R operative changes without claiming operational equivalence to the
    historical manual observation. Schema 5 permits reviewed presentation adapters
    while preserving the vendored scientific R sources byte for byte. Schema 6
    allows only the four known scientific scripts and their hash manifest to be
    reviewed; separate evidence verification is mandatory before publication.
    """
    require(isinstance(record, dict) and type(record.get("schema_version")) is int
            and record["schema_version"] in (1, 2, 3, 4, 5, 6), "Unsupported acceptance schema")
    if record["schema_version"] == 1:
        return None
    revised_r = record["schema_version"] == 6
    multiplatform = record["schema_version"] in (5, 6)
    reliability = record["schema_version"] in (4, 5, 6)
    reviewed_delta = record["schema_version"] in (3, 4, 5, 6)
    expected_fields = (SCIENTIFIC_RESEARCH_FIELDS if revised_r else MULTIPLATFORM_RESEARCH_FIELDS if multiplatform else RELIABILITY_RESEARCH_FIELDS if reliability else
                       REVIEWED_RESEARCH_FIELDS if reviewed_delta else RESEARCH_FIELDS)
    require(set(record) == expected_fields,
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
            require(reviewable_path(path, reliability=reliability, multiplatform=multiplatform, revised_r=revised_r),
                    f"Protected scientific or runtime source differs: {path}")
            changes.append({"path": path,
                            "before_sha256": hashlib.sha256(old).hexdigest() if old is not None else None,
                            "after_sha256": hashlib.sha256(new).hexdigest() if new is not None else None})
        require(record["reviewed_source_changes"] == changes,
                "Reviewed source changes do not match the exact baseline-to-candidate delta")
        return {"baseline_source_commit": baseline, "source_commit": candidate,
                "scope": REVISED_R_SOURCE_SCOPE if revised_r else MULTIPLATFORM_SOURCE_SCOPE if multiplatform else RELIABILITY_SOURCE_SCOPE if reliability else REVIEWED_SOURCE_SCOPE,
                "unchanged_files_verified": unchanged,
                "reviewed_source_changes": changes, "candidate_windows_installation_claimed": False,
                **({"operational_equivalence_claimed": False,
                    "vendored_r_sources_unchanged" if multiplatform else "r_sources_unchanged": not revised_r}
                   if reliability else {})}
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
