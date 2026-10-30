"""Bind experimental Windows and macOS packages to one source and scientific archive.

This local, read-only verification has no GitHub publication capability. It does
not change the stable release contract or qualify a desktop/VM installation.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re


PROJECT = Path(__file__).resolve().parents[2]
PROFILE = {
    "schema_version": 1, "channel": "experimental08",
    "display_name": "NIPAT Experimental08", "app_dir_name": "NIPAT-Experimental08",
    "data_dir_name": "NIPAT-Experimental08", "distro_prefix": "NIPAT-Experimental08-",
    "resume_key": "NIPAT-Experimental08-ResumeSetup",
    "mutex_prefix": "Local\\NIPAT-Experimental08-Setup-",
    "app_id": "A83D7E42-162C-438A-9B56-17F86C9F0800",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    require(path.is_file() and not path.is_symlink(), f"Missing or redirected file: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    digest(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_identity(manifest, commit):
    require(isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit), "Invalid commit")
    version = manifest.get("version")
    require(isinstance(version, str) and re.fullmatch(r"0\.8\.[0-9]+(?:a|b|rc)[0-9]+", version),
            "Only explicit 0.8 pre-releases belong to this experimental contract")
    require(manifest.get("schema_version") == 1 and manifest.get("source_commit") == commit
            and manifest.get("release_tag") == f"v{version}", "Manifest source/version mismatch")
    require(manifest.get("installation_profile") == PROFILE,
            "The experiment must use its isolated installation identity")
    require(set(manifest.get("assets", {})) == {"rootfs", "scientific_image"}, "Invalid runtime set")


def verify_windows(windows, assets, commit, read_source=None):
    publisher = load_module("experimental_readonly_helpers", PROJECT / ".github/scripts/publish_windows_release.py")
    read_source = publisher.source_bytes if read_source is None else read_source
    path = assets / "installer-manifest.json"
    manifest_bytes = path.read_bytes()
    manifest = read_json(path)
    validate_identity(manifest, commit)
    require((windows / path.name).read_bytes() == manifest_bytes, "Windows/shared manifests differ")
    require(publisher.committed_version(commit, read_source) == manifest["version"], "Version differs from source")
    publisher.verify_rootfs_source(manifest["rootfs_provenance"], commit, read_source)
    approved = [line.strip() for line in read_source(commit, "distribution-files.txt").decode().splitlines()
                if line.strip() and not line.strip().startswith("#")]
    require(len(set(approved)) == len(approved) and set(approved) == set(manifest["source_sha256"]),
            "Source inventory differs from the exact commit")
    for name in approved:
        relative = PurePosixPath(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe source path")
        require(hashlib.sha256(read_source(commit, name)).hexdigest() == manifest["source_sha256"][name],
                f"Source bytes differ: {name}")
    require(json.loads(read_source(commit, "installer/windows/install-profile.json")) == PROFILE,
            "Committed installation profile differs")
    runtime_hashes = {path.name: digest(path)}
    for key, stem in (("rootfs", "nipat-wsl-rootfs"), ("scientific_image", "nipat-scientific-runtime")):
        asset = manifest["assets"][key]
        name = f"{stem}-{manifest['version']}-amd64.tar.gz"
        require(asset["file"] == name and asset["url"] ==
                f"https://github.com/GregorioDalia/nipat-desktop/releases/download/{manifest['release_tag']}/{name}",
                "Runtime archive name/URL mismatch")
        archive = assets / name
        require(digest(archive) == asset["sha256"] and archive.stat().st_size == asset["size"]
                and 0 < archive.stat().st_size < publisher.MAX_ASSET_BYTES, "Runtime archive changed")
        runtime_hashes[name] = asset["sha256"]
    require(publisher.checksums(assets / "SHA256SUMS") == runtime_hashes, "Runtime checksums differ")
    setup = windows / "NIPAT-Setup.exe"
    setup_hash = digest(setup)
    require(0 < setup.stat().st_size < publisher.MAX_ASSET_BYTES, "Invalid installer size")
    require(publisher.checksums(windows / "SHA256SUMS") == {setup.name: setup_hash}, "Setup checksum differs")
    publisher.verify_installer_build(windows, manifest, manifest_bytes, commit)
    return manifest, {"file": setup.name, "sha256": setup_hash, "size": setup.stat().st_size}


def verify_macos(directory, architecture, manifest):
    expected_name = f"NIPAT-Experimental-{manifest['version']}-macos-{architecture}.pkg"
    package = directory / expected_name
    report = read_json(directory / "macos-package-verification.json")
    expected = {
        "verified": True, "platform": "darwin", "architecture": architecture,
        "version": manifest["version"], "source_commit": manifest["source_commit"],
        "scientific_asset_sha256": manifest["assets"]["scientific_image"]["sha256"],
        "runtime_vm_qualified": False, "package_sha256": digest(package),
    }
    require(all(type(report.get(key)) is type(value) and report.get(key) == value
                for key, value in expected.items()), f"Unbound or failed macOS {architecture} package evidence")
    require(set(item.name for item in directory.glob("*.pkg")) == {expected_name}, "Ambiguous macOS packages")
    return {"file": expected_name, "sha256": expected["package_sha256"], "size": package.stat().st_size,
            "verification_sha256": digest(directory / "macos-package-verification.json"),
            "runtime_vm_qualified": False}


def verify_client(windows, manifest, installer):
    helper = load_module("experimental_client_checks", PROJECT / "scripts/verify_windows_payload.py")
    report = read_json(windows / "windows-client-check.json")
    expected = {
        "schema_version": 1, "platform": "windows-amd64", "scenario": "staged-embedded-python-client",
        "version": manifest["version"], "source_commit": manifest["source_commit"],
        "installer_manifest_sha256": digest(windows / "installer-manifest.json"),
        "installer_sha256": installer["sha256"], "launcher_sha256": digest(windows / "NIPAT.exe"),
        "application_inventory_sha256": digest(windows / "application-files.json"),
        "python_version": "3.12.10", "scientific_execution": False, "wsl_execution": False,
    }
    require(set(report) == set(expected) | {"checks"} and all(
        type(report.get(key)) is type(value) and report.get(key) == value for key, value in expected.items()),
        "Windows client report is not bound to the built package")
    require(set(report["checks"]) == set(helper.CHECKS) and all(value is True for value in report["checks"].values()),
            "Windows client checks are incomplete")
    inventory = read_json(windows / "application-files.json")
    require(inventory.get("installation_channel") == PROFILE["channel"]
            and inventory.get("source_commit") == manifest["source_commit"], "Windows inventory identity differs")
    sources = manifest["source_sha256"]
    files = inventory.get("files", [])
    hashes = {entry["path"]: entry["sha256"] for entry in files}
    generated = {"release.json", "NIPAT.exe", "installer/windows/EnableWsl.exe",
                 ".distribution/installer-manifest.json", f".distribution/{helper.PYTHON_ARCHIVE}"}
    require(len(files) == len(hashes) == len({name.casefold() for name in hashes})
            and set(hashes) == set(sources) | generated
            and all(hashes.get(name) == value for name, value in sources.items())
            and hashes["NIPAT.exe"] == expected["launcher_sha256"]
            and hashes[".distribution/installer-manifest.json"] == expected["installer_manifest_sha256"]
            and hashes[f".distribution/{helper.PYTHON_ARCHIVE}"] == helper.PYTHON_SHA256,
            "Windows payload inventory differs from verified source/client bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows-dir", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--windows-only", action="store_true")
    parser.add_argument("--macos-arm64-dir", type=Path)
    parser.add_argument("--macos-x86-64-dir", type=Path)
    args = parser.parse_args()
    manifest, windows = verify_windows(args.windows_dir, args.assets_dir, args.source_commit)
    report = {"schema_version": 1, "version": manifest["version"], "source_commit": args.source_commit,
              "scientific_archive_sha256": manifest["assets"]["scientific_image"]["sha256"],
              "windows": windows, "publication_authorized": False, "desktop_acceptance": False,
              "runtime_vm_qualified": False}
    if not args.windows_only:
        require(args.macos_arm64_dir is not None and args.macos_x86_64_dir is not None,
                "Both native macOS packages are required")
        verify_client(args.windows_dir, manifest, windows)
        report["macos"] = {architecture: verify_macos(folder, architecture, manifest)
                           for architecture, folder in (("arm64", args.macos_arm64_dir),
                                                        ("x86_64", args.macos_x86_64_dir))}
        inventory = load_module("experimental_inventory", PROJECT / ".github/scripts/component_inventory.py")
        report["component_inventory"] = inventory.verify(args.assets_dir / "component-inventory.json", manifest)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "experimental-installer-check.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: experimental installer identities verified; desktop/VM acceptance remains separate.")


if __name__ == "__main__":
    main()
