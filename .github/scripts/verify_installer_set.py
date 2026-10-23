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


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition, message):
    if not condition:
        raise ValueError(message)


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
    require(isinstance(checks, dict) and set(checks) == INSTALLATION_CHECKS
            and all(value is True for value in checks.values()),
            "A required Linux installation check is missing or failed")


def verify_set(windows, linux, assets, output, commit, project=PROJECT):
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None, "Invalid source commit")
    require(not output.exists(), "Evidence output directory must not already exist")
    publisher = load_module("nipat_review_publisher", project / ".github/scripts/publish_windows_release.py")
    builder = load_module("nipat_linux_builder", project / "scripts/build_linux_installer.py")
    manifest_path = assets / "installer-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    require((linux / "installer-manifest.json").read_bytes() == manifest_bytes,
            "Windows and Linux must use the same installer manifest bytes")
    # The existing Windows verifier binds all assets and approved source hashes
    # to the exact commit. It does not publish, create tags or contact GitHub.
    with tempfile.TemporaryDirectory(prefix="nipat-review-") as temporary:
        manifest = publisher.prepare_assets(windows, assets, Path(temporary) / "verified", commit)
    require(manifest["version"].startswith("0.5."), "This review contract is for NIPAT 0.5")
    record = read_json(linux / "linux-installer-build.json")
    name = record.get("file", "")
    require(isinstance(name, str) and re.fullmatch(
        r"nipat-05-preview_[0-9]+\.[0-9]+\.[0-9]+(?:~(?:a|b|rc)[0-9]+)?_amd64\.deb", name),
        "Invalid Linux package name")
    package = linux / name
    require(record == builder.verify_package(package, manifest_path, project),
            "Linux build evidence differs from the actual Debian package")
    require((linux / "SHA256SUMS").read_text(encoding="ascii") == f"{record['sha256']}  {name}\n",
            "Linux package checksum file mismatch")
    installation = read_json(linux / "linux-installation-check.json")
    verify_installation_check(installation, manifest, manifest_bytes, record)
    result = {
        "schema_version": 1, "version": manifest["version"], "source_commit": commit,
        "installer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "scientific_archive": {
            key: manifest["assets"]["scientific_image"][key] for key in ("file", "sha256", "size")
        },
        "windows": {"file": "NIPAT-Setup.exe", "sha256": publisher.sha256(windows / "NIPAT-Setup.exe")},
        "linux": {"file": name, "sha256": record["sha256"], "installation_check": installation},
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
    print("Review evidence only; NIPAT 0.5 publication remains disabled.")


if __name__ == "__main__":
    main()
