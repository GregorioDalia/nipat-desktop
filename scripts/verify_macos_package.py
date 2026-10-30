"""Verify an experimental macOS installer without installing it or starting a VM."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

_SPEC = importlib.util.spec_from_file_location(
    "nipat_mac_builder", Path(__file__).with_name("build_macos_installer.py"))
builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(builder)


def require_virtualization_entitlement(stdout: bytes, stderr: bytes) -> None:
    """A valid ad-hoc signature must retain the Virtualization.framework capability."""
    for output in (stdout, stderr):
        start = output.find(b"<?xml")
        end = output.find(b"</plist>", start)
        if start >= 0 and end >= 0:
            try:
                entitlements = plistlib.loads(output[start:end + len(b"</plist>")])
            except (ValueError, plistlib.InvalidFileException):
                continue
            if isinstance(entitlements, dict) and entitlements.get("com.apple.security.virtualization") is True:
                return
    raise ValueError("Bundled Lima signature lacks the required virtualization entitlement.")


def verify_payload(payload: Path, common: dict, record: dict) -> dict:
    # macOS exposes its temporary directory through /var -> /private/var.
    # Compare canonical roots as well as canonical children; file symlinks
    # inside the payload are still rejected separately below.
    payload = payload.resolve()
    app = payload / builder.APP_RELATIVE
    resources = app / "Contents/Resources"
    installed = resources / "app"
    manifest = builder.read_json(installed / ".distribution/macos-manifest.json")
    for field in ("version", "source_commit", "runtime_image"):
        if manifest.get(field) != common.get(field) or record.get(field) != common.get(field):
            raise ValueError(f"Package scientific/source identity mismatch: {field}")
    if (manifest.get("channel") != "experimental08" or manifest.get("provider") != "lima"
            or manifest.get("architecture") != record.get("architecture")
            or manifest.get("runtime_vm_qualified") is not False
            or record.get("runtime_vm_qualified") is not False):
        raise ValueError("Invalid experimental package qualification or architecture.")
    entry = common["assets"]["scientific_image"]
    if (manifest.get("scientific_asset") != {
            "name": entry["file"], "sha256": entry["sha256"], "size": entry["size"]}
            or record.get("scientific_asset_sha256") != entry["sha256"]):
        raise ValueError("The Mac package does not reuse the original scientific archive.")
    scientific = installed / ".distribution/assets" / entry["file"]
    if scientific.stat().st_size != entry["size"] or builder.bundle.sha256_file(scientific) != entry["sha256"]:
        raise ValueError("Embedded scientific archive is truncated or changed.")
    if manifest.get("source_sha256") != common.get("source_sha256"):
        raise ValueError("Package source inventory differs from the scientific build.")
    for name, expected in common["source_sha256"].items():
        path = installed / name
        if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(installed)
                or builder.bundle.sha256_file(path) != expected):
            raise ValueError(f"Packaged source mismatch: {name}")
    if builder.payload_inventory(payload) != record.get("payload_inventory"):
        raise ValueError("Package inventory differs from the signed build payload.")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if (info.get("CFBundleIdentifier") != builder.IDENTIFIER
            or info.get("LSMinimumSystemVersion") != "14.0"
            or info.get("CFBundleExecutable") != "NIPAT"):
        raise ValueError("Invalid macOS application identity or OS requirement.")
    executable = app / "Contents/MacOS/NIPAT"
    if not executable.is_file() or not executable.stat().st_mode & 0o111:
        raise ValueError("Native application launcher is missing or not executable.")
    for name in ("NIPAT.command", "python/bin/python3.12", "lima/bin/limactl"):
        if not (resources / name).stat().st_mode & 0o111:
            raise ValueError(f"Executable permissions missing: {name}")
    return manifest


def verify(package: Path, common_manifest: Path, *, build_record: Path | None = None) -> dict:
    if sys.platform != "darwin":
        raise ValueError("Verify the real .pkg on a macOS runner; Linux tests validate fixture payloads only.")
    common = builder.read_json(common_manifest)
    builder.assets.validate_manifest(common)
    record = builder.read_json(build_record or package.parent / builder.BUILD_RECORD)
    if (package.is_symlink() or not package.is_file()
            or package.name != record.get("package")
            or package.stat().st_size != record.get("package_size")
            or builder.bundle.sha256_file(package) != record.get("package_sha256")):
        raise ValueError("Package bytes differ from the build record.")
    if record.get("architecture") != platform.machine():
        raise ValueError("Run package verification on its native architecture.")
    with tempfile.TemporaryDirectory(prefix="nipat-macos-verification-") as temporary:
        expanded = Path(temporary) / "expanded"
        subprocess.run(["/usr/sbin/pkgutil", "--expand-full", str(package), str(expanded)], check=True)
        candidates = list(expanded.glob("*/Payload/Applications/" + builder.APP_NAME))
        if len(candidates) != 1:
            raise ValueError("Expected exactly one NIPAT application payload.")
        app = candidates[0]
        payload = app.parents[1]
        installed = verify_payload(payload, common, record)
        distribution = ET.parse(expanded / "Distribution").getroot()
        options = distribution.find("options")
        minimum = distribution.find("allowed-os-versions/os-version")
        if (options is None or options.get("hostArchitectures") != record["architecture"]
                or minimum is None or minimum.get("min") != "14.0"):
            raise ValueError("Installer OS/architecture restrictions are missing.")
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
        resources = app / "Contents/Resources"
        python = resources / "python/bin/python3.12"
        for executable in (python, resources / "lima/bin/limactl", app / "Contents/MacOS/NIPAT"):
            detected = subprocess.check_output(["/usr/bin/lipo", "-archs", str(executable)], text=True).strip().split()
            if record["architecture"] not in detected:
                raise ValueError(f"Wrong executable architecture: {executable.name}")
        python_version = subprocess.check_output([str(python), "--version"], text=True).strip()
        if python_version != "Python " + installed["python_version"]:
            raise ValueError("Bundled Python version mismatch.")
        lima_version = subprocess.check_output([str(resources / "lima/bin/limactl"), "--version"], text=True).strip()
        if lima_version != "limactl version " + installed["lima_version"]:
            raise ValueError("Bundled Lima version mismatch.")
        entitlements = subprocess.run(["/usr/bin/codesign", "--display", "--entitlements", ":-",
                                       str(resources / "lima/bin/limactl")], check=True, capture_output=True)
        require_virtualization_entitlement(entitlements.stdout, entitlements.stderr)
        cli_version = subprocess.check_output([
            str(python), "-I", "-B", "-c",
            "import sys;sys.path.insert(0,sys.argv.pop(1));from nipat.cli import main;raise SystemExit(main())",
            str(resources / "app/src"), "--version"], text=True).strip()
        if cli_version != "NIPAT " + common["version"]:
            raise ValueError("Packaged CLI does not report the expected version.")
        validate_template = '''import json, pathlib, subprocess, sys
sys.path.insert(0, sys.argv.pop(1))
from nipat.macos_runtime import LimaRuntime
project, executable, destination = map(pathlib.Path, sys.argv[1:])
home = pathlib.Path.home()
runtime = LimaRuntime(project, home / "Library/Application Support/NIPAT-Experimental08",
                      executable, home=home)
manifest = json.loads((project / ".distribution/macos-manifest.json").read_text())
owner = {"token": "d" * 32, "mounts": runtime.default_mounts()}
destination.write_text(json.dumps(runtime.template(manifest, owner)))
subprocess.run([*runtime.host_prefix(), "validate", str(destination)], check=True)
'''
        subprocess.run([str(python), "-I", "-B", "-c", validate_template,
                        str(resources / "app/src"), str(resources / "app"),
                        str(resources / "lima/bin/limactl"),
                        str(Path(temporary) / "lima.yaml")], check=True)
    return {
        "schema_version": 1, "verified": True, "platform": "darwin",
        "architecture": record["architecture"], "version": common["version"],
        "source_commit": common["source_commit"], "package_sha256": record["package_sha256"],
        "scientific_asset_sha256": record["scientific_asset_sha256"],
        "runtime_image": common["runtime_image"], "runtime_vm_qualified": False,
        "checks": ["package-sha256", "full-payload-inventory", "scientific-archive-reuse",
                   "source-inventory", "installer-os-and-architecture", "ad-hoc-code-signatures",
                   "native-python", "native-lima", "lima-virtualization-entitlement",
                   "packaged-cli-version", "generated-lima-template"],
        "not_tested": ["clean-installation", "first-launch-vm-provisioning", "scientific-execution",
                       "upgrade", "runtime-removal", "gatekeeper-policy"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--build-record", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    options = parser.parse_args()
    if options.report.exists():
        parser.exit(1, "Verification report already exists; choose a new report path.\n")
    try:
        report = verify(options.package.resolve(), options.manifest.resolve(),
                        build_record=options.build_record)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Verifica macOS interrotta: {exc}\n")
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Pacchetto macOS verificato: {options.package}; runtime VM non ancora qualificato.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
