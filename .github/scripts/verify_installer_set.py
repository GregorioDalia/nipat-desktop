"""Verify a Windows/Linux review build without authorizing publication."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile


PROJECT = Path(__file__).resolve().parents[2]
INSTALLATION_CHECKS = {
    "package_installation", "initial_setup", "immutable_runtime_binding",
    "all_four_workflows", "private_inputs_unchanged", "user_owned_results",
    "repeated_launch", "package_reinstallation",
    "package_removal_preserves_user_data", "shared_docker_unchanged",
}
WORKFLOW_INSTALLATION_CHECKS = {"automatic_workflow_plan", "preferences_preserved"}
WINDOWS_CLIENT_CHECKS = {
    "payload_integrity", "embedded_python", "packaged_imports", "scientific_catalog",
    "wizard_navigation", "composed_workflow_plans", "snp_batch_plans",
    "read_only_input_mounts", "original_inputs_unchanged",
}
DEPENDENCY_CHECKS = {
    "dependencies_initially_absent", "apt_installs_required_packages",
    "installed_cli_help_and_version", "no_automatic_docker_access",
    "no_runtime_preparation", "apt_sources_unchanged", "embedded_manifest_matches",
}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition, message):
    if not condition:
        raise ValueError(message)


def installation_checks(version):
    require(isinstance(version, str) and re.fullmatch(
        r"0\.[67]\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version),
        "This review contract supports NIPAT 0.6 and 0.7")
    return INSTALLATION_CHECKS | (WORKFLOW_INSTALLATION_CHECKS if version.startswith("0.7.") else set())


def read_json(path):
    require(path.is_file() and not path.is_symlink(), f"Missing or invalid evidence: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify_installation_check(evidence, manifest, manifest_bytes, package_record):
    """Bind real installation checks to the package and shared runtime bytes."""
    expected = {
        "schema_version": 1,
        "distribution": "native-linux-deb",
        "platform": "ubuntu-24.04-amd64",
        "scenario": "prepared-ci-runner",
        "source_commit": manifest["source_commit"],
        "installer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "package_sha256": package_record["sha256"],
        "runtime_archive_sha256": manifest["assets"]["scientific_image"]["sha256"],
    }
    require(all(type(evidence.get(key)) is type(value) and evidence.get(key) == value
                for key, value in expected.items()), "Linux installation evidence mismatch")
    uid = evidence.get("nonroot_uid")
    require(type(uid) is int and uid > 0, "Linux installation must be exercised as non-root")
    require(isinstance(evidence.get("resolved_runtime_image"), str) and re.fullmatch(
        r"sha256:[0-9a-f]{64}", evidence["resolved_runtime_image"]),
        "Missing immutable image ID from the installed Linux runtime")
    checks = evidence.get("checks")
    require(isinstance(checks, dict) and set(checks) == installation_checks(manifest.get("version"))
            and all(value is True for value in checks.values()),
            "A required Linux installation check is missing or failed")


def verify_dependency_check(evidence, manifest, manifest_bytes, package_record):
    """Bind missing-dependency proof without claiming desktop acceptance."""
    expected = {
        "schema_version": 1, "distribution": "native-linux-deb",
        "platform": "ubuntu-24.04-amd64", "scenario": "clean-ubuntu-container",
        "source_commit": manifest["source_commit"],
        "installer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "package_sha256": package_record["sha256"],
        "runtime_archive_sha256": manifest["assets"]["scientific_image"]["sha256"],
    }
    require(all(type(evidence.get(key)) is type(value) and evidence.get(key) == value
                for key, value in expected.items()), "Linux dependency evidence mismatch")
    require(isinstance(evidence.get("base_image"), str) and re.fullmatch(
        r"ubuntu:24\.04@sha256:[0-9a-f]{64}", evidence["base_image"]),
        "The dependency check must use a pinned Ubuntu 24.04 image")
    packages = evidence.get("dependency_packages")
    require(isinstance(packages, dict)
            and set(packages) == {"python3.12", "docker.io", "docker-compose-v2", "nipat-desktop"}
            and all(isinstance(version, str) and version.strip() for version in packages.values()),
            "Missing dependency versions from the clean Ubuntu installation")
    checks = evidence.get("checks")
    require(isinstance(checks, dict) and set(checks) == DEPENDENCY_CHECKS
            and all(value is True for value in checks.values()),
            "A required Linux dependency check is missing or failed")


def verify_windows_client_check(evidence, manifest, manifest_bytes, *, installer_sha256,
                                launcher_sha256, inventory_bytes):
    """Bind staged Windows client checks without claiming WSL or installed-desktop execution."""
    expected = {
        "schema_version": 1, "platform": "windows-amd64",
        "scenario": "staged-embedded-python-client", "version": manifest["version"],
        "source_commit": manifest["source_commit"],
        "installer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "installer_sha256": installer_sha256, "launcher_sha256": launcher_sha256,
        "application_inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "python_version": "3.12.10", "scientific_execution": False, "wsl_execution": False,
    }
    require(isinstance(evidence, dict) and set(evidence) == set(expected) | {"checks"}
            and all(type(evidence.get(key)) is type(value) and evidence.get(key) == value
                    for key, value in expected.items()), "Windows client evidence mismatch")
    checks = evidence["checks"]
    require(isinstance(checks, dict) and set(checks) == WINDOWS_CLIENT_CHECKS
            and all(value is True for value in checks.values()),
            "A required Windows client check is missing or failed")
    inventory = json.loads(inventory_bytes.decode("utf-8-sig"))
    require(isinstance(inventory, dict)
            and set(inventory) == {"schema_version", "installation_channel", "source_commit", "files"}
            and type(inventory["schema_version"]) is int and inventory["schema_version"] == 1
            and inventory["installation_channel"] == "desktop"
            and inventory["source_commit"] == manifest["source_commit"],
            "Windows application inventory identity mismatch")
    files = inventory["files"]
    require(isinstance(files, list) and all(
        isinstance(item, dict) and set(item) == {"path", "sha256"}
        and isinstance(item["path"], str) and isinstance(item["sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in files),
        "Windows application inventory entries are invalid")
    require(len({item["path"].casefold() for item in files}) == len(files),
            "Windows application inventory contains ambiguous paths")
    hashes = {item["path"]: item["sha256"] for item in files}
    sources = manifest.get("source_sha256")
    require(isinstance(sources, dict) and sources, "Windows source inventory is missing")
    bundle = load_module("nipat_review_distribution", PROJECT / "scripts/distribution_support.py")
    generated = {"release.json", "NIPAT.exe", "installer/windows/EnableWsl.exe",
                 ".distribution/installer-manifest.json", f".distribution/{bundle.PYTHON_NAME}"}
    require(set(hashes) == set(sources) | generated
            and all(hashes.get(path) == digest for path, digest in sources.items())
            and hashes["NIPAT.exe"] == launcher_sha256
            and hashes[".distribution/installer-manifest.json"] == expected["installer_manifest_sha256"]
            and hashes[f".distribution/{bundle.PYTHON_NAME}"] == bundle.PYTHON_SHA256,
            "Windows application inventory differs from the verified source and embedded client")


def verify_set(windows, linux, assets, output, commit, project=PROJECT):
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "Invalid source commit")
    require(not output.exists(), "Evidence output directory must not already exist")
    # Use the trusted verification implementation, while project may be a
    # read-only snapshot of an earlier exact source commit being published.
    publisher = load_module("nipat_review_publisher", PROJECT / ".github/scripts/publish_windows_release.py")
    builder = load_module("nipat_linux_builder", PROJECT / "scripts/build_linux_installer.py")
    manifest_path = assets / "installer-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    require((linux / "installer-manifest.json").read_bytes() == manifest_bytes,
            "Windows and Linux must use the same installer manifest bytes")
    # The existing Windows verifier binds all assets and approved source hashes
    # to the exact commit. It does not publish, create tags or contact GitHub.
    with tempfile.TemporaryDirectory(prefix="nipat-review-") as temporary:
        manifest = publisher.prepare_assets(windows, assets, Path(temporary) / "verified", commit)
    installation_checks(manifest["version"])
    record = read_json(linux / "linux-installer-build.json")
    name = record.get("file", "")
    require(isinstance(name, str) and re.fullmatch(
        r"nipat-desktop_[0-9]+\.[0-9]+\.[0-9]+(?:~(?:a|b|rc)[0-9]+)?_amd64\.deb", name),
        "Invalid Linux package name")
    package = linux / name
    require(record == builder.verify_package(package, manifest_path, project),
            "Linux build evidence differs from the actual Debian package")
    require((linux / "SHA256SUMS").read_text(encoding="ascii") == f"{record['sha256']}  {name}\n",
            "Linux package checksum file mismatch")
    installation = read_json(linux / "linux-installation-check.json")
    verify_installation_check(installation, manifest, manifest_bytes, record)
    dependencies = read_json(linux / "linux-dependency-check.json")
    verify_dependency_check(dependencies, manifest, manifest_bytes, record)
    windows_record = {"file": "NIPAT-Setup.exe", "sha256": publisher.sha256(windows / "NIPAT-Setup.exe")}
    if manifest["version"].startswith("0.7."):
        client_check = read_json(windows / "windows-client-check.json")
        inventory_path = windows / "application-files.json"
        require(inventory_path.is_file() and not inventory_path.is_symlink(),
                "Missing Windows application inventory evidence")
        verify_windows_client_check(
            client_check, manifest, manifest_bytes, installer_sha256=windows_record["sha256"],
            launcher_sha256=publisher.sha256(windows / "NIPAT.exe"),
            inventory_bytes=inventory_path.read_bytes(),
        )
        windows_record["client_check"] = client_check
    result = {
        "schema_version": 1, "version": manifest["version"], "source_commit": commit,
        "installer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "scientific_archive": {
            key: manifest["assets"]["scientific_image"][key] for key in ("file", "sha256", "size")
        },
        "windows": windows_record,
        "linux": {"file": name, "sha256": record["sha256"], "installation_check": installation,
                  "dependency_check": dependencies},
        "publication_authorized": False,
        "scope": "Build and prepared-runner checks; fresh desktop acceptance is separate.",
    }
    output.mkdir(parents=True)
    (output / "installer-set-check.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-dir", type=Path, required=True)
    parser.add_argument("--linux-dir", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    verify_set(args.windows_dir, args.linux_dir, args.assets_dir, args.output_dir, args.source_commit)
    print("PASS: Windows and Linux installers identify the same verified source and scientific archive.")
    print("Review evidence alone does not authorize publication; desktop acceptance is required.")


if __name__ == "__main__":
    main()
