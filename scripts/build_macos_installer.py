"""Build one self-contained experimental macOS package per native architecture.

The Linux scientific archive is reused byte for byte. This builder performs no VM
startup, scientific calculation, package installation or public publication.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from xml.sax.saxutils import escape

_SPEC = importlib.util.spec_from_file_location(
    "nipat_mac_assets", Path(__file__).with_name("build_windows_installer_assets.py"))
assets = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(assets)
bundle = assets.bundle

APP_NAME = "NIPAT Experimental08.app"
APP_RELATIVE = Path("Applications") / APP_NAME
IDENTIFIER = "org.nipat.experimental08"
BUILD_RECORD = "macos-installer-build.json"
MACHO_MAGICS = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
                b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def verified_inputs(project: Path, manifest_path: Path, description_path: Path,
                    *, require_clean: bool = True) -> tuple[dict, list[Path], Path, dict]:
    manifest = read_json(manifest_path)
    assets.validate_manifest(manifest)
    if not re.fullmatch(r"0\.8\.\d+(?:a|b|rc)\d+", manifest["version"]):
        raise ValueError("The macOS package requires an experimental 0.8 prerelease.")
    if manifest.get("installation_profile", {}).get("channel") != "experimental08":
        raise ValueError("The package must use the isolated experimental08 identity.")
    if assets.checked_version(project) != manifest["version"]:
        raise ValueError("Source version does not match the scientific manifest.")
    if require_clean:
        source = bundle.git_source(project)
        if (source.get("available") is not True or source.get("dirty") is not False
                or source.get("commit") != manifest["source_commit"]):
            raise ValueError("A clean checkout at the manifest commit is required.")
    files = bundle.source_files(project)
    hashes = {path.relative_to(project).as_posix(): bundle.sha256_file(path) for path in files}
    if hashes != manifest.get("source_sha256"):
        raise ValueError("Source inventory differs from the verified scientific build.")
    required = {"installer/macos/dependencies.json", "installer/macos/launch.py",
                "installer/macos/NIPAT.command", "installer/macos/launcher.c",
                "installer/macos/package-guard.c", "src/nipat/macos_runtime.py",
                "LICENSE", "THIRD_PARTY_NOTICES.md"}
    if not required.issubset(hashes):
        raise ValueError("The distribution allowlist is missing macOS package sources.")
    notices = project / "installer/macos/licenses/python-build-standalone"
    provenance = read_json(notices / "provenance.json")
    notice_hashes = provenance.get("files_sha256", {})
    if not notice_hashes:
        raise ValueError("The Python dependency license inventory is missing.")
    for name, expected in notice_hashes.items():
        notice = notices / name
        if (Path(name).name != name or notice.is_symlink() or not notice.is_file()
                or bundle.sha256_file(notice) != expected
                or notice.relative_to(project).as_posix() not in hashes):
            raise ValueError(f"Python dependency notice missing or changed: {name}")
    entry = manifest["assets"]["scientific_image"]
    archive = manifest_path.parent / entry["file"]
    if assets.asset_metadata(archive, manifest["release_tag"]) != entry:
        raise ValueError("Scientific archive bytes do not match the original manifest.")
    description = read_json(description_path)
    # Engine metadata is produced by the same verified image job, never by the Mac host.
    if not description or not isinstance(description.get("workflows"), (dict, list)):
        raise ValueError("Missing engine describe --json output from the scientific build.")
    return manifest, files, archive, description


def dependency_archive(entry: dict, destination: Path, requested: Path | None = None) -> Path:
    """Only download a fixed HTTPS upstream asset with a committed size and digest."""
    if (not re.fullmatch(r"[a-f0-9]{64}", entry.get("sha256", ""))
            or not isinstance(entry.get("size"), int) or entry["size"] <= 0
            or not entry.get("url", "").startswith("https://github.com/")):
        raise ValueError("Invalid pinned dependency metadata.")
    path = requested if requested is not None else destination / entry["file"]
    if requested is None:
        print(f"Download verificato: {entry['file']}", flush=True)
        with urllib.request.urlopen(entry["url"], timeout=120) as response, path.open("xb") as target:
            received = 0
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > entry["size"]:
                    raise ValueError("Dependency download exceeds its pinned size.")
                target.write(chunk)
    if (path.is_symlink() or not path.is_file() or path.stat().st_size != entry["size"]
            or bundle.sha256_file(path) != entry["sha256"]):
        raise ValueError(f"Dependency archive checksum/size mismatch: {path}")
    return path


def safe_extract(archive: Path, destination: Path) -> None:
    """Preserve dependency symlinks while rejecting paths or links outside the payload."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        seen: set[str] = set()
        for member in members:
            relative = PurePosixPath(member.name)
            if relative.as_posix() == "." and member.isdir():
                continue
            if (relative.is_absolute() or ".." in relative.parts or "\\" in member.name
                    or not relative.parts or relative.as_posix() in seen
                    or not (member.isdir() or member.isfile() or member.issym() or member.islnk())):
                raise ValueError(f"Unsafe dependency archive member: {member.name}")
            seen.add(relative.as_posix())
            target = root / Path(relative)
            if not target.resolve().is_relative_to(root):
                raise ValueError("Dependency archive path escapes the payload.")
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                resolved = (target.parent if member.issym() else root) / Path(link)
                if link.is_absolute() or not resolved.resolve().is_relative_to(root):
                    raise ValueError("Dependency archive link escapes the payload.")
        # Python's data filter also checks symlink traversal during extraction.
        source.extractall(destination, members=members, filter="data")


def package_version(version: str) -> str:
    match = re.fullmatch(r"(0\.8\.\d+)(?:a|b|rc)(\d+)", version)
    if not match:
        raise ValueError("Expected an experimental 0.8 prerelease version.")
    return f"{match[1]}.{match[2]}"


def mac_manifest(manifest: dict, architecture: str, dependencies: dict, description: dict) -> dict:
    entry = manifest["assets"]["scientific_image"]
    return {
        "schema_version": 1, "provider": "lima", "channel": "experimental08",
        "version": manifest["version"], "release_tag": manifest["release_tag"],
        "source_commit": manifest["source_commit"], "architecture": architecture,
        "minimum_macos": "14.0", "bundle_identifier": IDENTIFIER,
        "lima_version": dependencies["lima_version"],
        "python_version": dependencies["python_version"],
        "runtime_image": manifest["runtime_image"],
        "scientific_asset": {"name": entry["file"], "sha256": entry["sha256"], "size": entry["size"]},
        "engine_description": description,
        "dependencies": dependencies["architectures"][architecture],
        "source_sha256": manifest["source_sha256"],
        "source_inventory_sha256": hashlib.sha256(json.dumps(
            manifest["source_sha256"], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "runtime_vm_qualified": False,
        "signing": {"application": "ad-hoc", "installer": "unsigned", "notarized": False},
    }


def distribution_xml(version: str, architecture: str) -> str:
    """Installer rejects incompatible hardware/OS before writing application files."""
    return f'''<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>NIPAT Experimental {escape(version)}</title>
  <options customize="never" require-scripts="false" hostArchitectures="{architecture}"/>
  <domains enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true"/>
  <allowed-os-versions><os-version min="14.0"/></allowed-os-versions>
  <welcome file="Welcome.txt" mime-type="text/plain"/>
  <license file="LICENSE.txt" mime-type="text/plain"/>
  <choices-outline><line choice="default"/></choices-outline>
  <choice id="default" visible="false"><pkg-ref id="{IDENTIFIER}"/></choice>
  <pkg-ref id="{IDENTIFIER}" version="{package_version(version)}" onConclusion="none">NIPAT-component.pkg</pkg-ref>
</installer-gui-script>
'''


def payload_inventory(root: Path) -> dict:
    inventory = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            inventory[relative] = {"link": os.readlink(path)}
        elif path.is_file():
            inventory[relative] = {"sha256": bundle.sha256_file(path),
                                   "mode": stat.S_IMODE(path.stat().st_mode)}
    return inventory


def sign_payload(app: Path) -> None:
    """Ad-hoc signing preserves upstream entitlements; it is not Developer ID signing."""
    for path in sorted(app.rglob("*"), reverse=True):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            magic = stream.read(4)
        if magic in MACHO_MAGICS:
            subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none",
                            "--preserve-metadata=entitlements", str(path)], check=True)
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(app)],
                   check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)


def stage_payload(project: Path, root: Path, manifest: dict, files: list[Path], scientific: Path,
                  description: dict, architecture: str, python_archive: Path, lima_archive: Path,
                  dependencies: dict) -> Path:
    app = root / APP_RELATIVE
    resources = app / "Contents/Resources"
    source_root = resources / "app"
    source_root.mkdir(parents=True)
    for source in files:
        target = source_root / source.relative_to(project)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o644)
    safe_extract(python_archive, resources)
    safe_extract(lima_archive, resources / "lima")
    for required in (resources / "python/bin/python3.12", resources / "lima/bin/limactl"):
        if not required.is_file() or not os.access(required, os.X_OK):
            raise ValueError(f"Bundled executable missing: {required}")
    for notice in (resources / "python/lib/python3.12/LICENSE.txt",
                   resources / "lima/share/doc/lima/LICENSE"):
        if not notice.is_file() or not notice.stat().st_size:
            raise ValueError(f"Upstream runtime license notice missing: {notice}")
    destination = source_root / ".distribution/assets"
    destination.mkdir(parents=True)
    shutil.copyfile(scientific, destination / scientific.name)
    metadata = mac_manifest(manifest, architecture, dependencies, description)
    (source_root / ".distribution/macos-manifest.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(project / "installer/macos/NIPAT.command", resources / "NIPAT.command")
    (resources / "NIPAT.command").chmod(0o755)
    (app / "Contents/MacOS").mkdir()
    plist = {
        "CFBundleIdentifier": IDENTIFIER, "CFBundleName": "NIPAT Experimental08",
        "CFBundleDisplayName": "NIPAT Experimental08", "CFBundleExecutable": "NIPAT",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": re.match(r"\d+\.\d+\.\d+", manifest["version"])[0],
        "CFBundleVersion": manifest["version"], "LSMinimumSystemVersion": "14.0",
        "CFBundleIconFile": "NIPAT.icns", "LSApplicationCategoryType": "public.app-category.education",
        "NSHumanReadableCopyright": "NIPAT contributors; GNU GPL version 3 or later",
    }
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(plist, sort_keys=True))
    return app


def build(project: Path, manifest_path: Path, output: Path, architecture: str,
          description_path: Path, python_archive: Path | None = None,
          lima_archive: Path | None = None) -> Path:
    if sys.platform != "darwin" or platform.machine() != architecture:
        raise ValueError("Build each macOS installer on a native macOS runner of that architecture.")
    if int(platform.mac_ver()[0].split(".")[0]) < 14:
        raise ValueError("The builder requires macOS 14 or later.")
    manifest, files, scientific, description = verified_inputs(project, manifest_path, description_path)
    dependencies = read_json(project / "installer/macos/dependencies.json")
    output.mkdir(parents=True, exist_ok=True)
    name = f"NIPAT-Experimental-{manifest['version']}-macos-{architecture}.pkg"
    target = output / name
    if target.exists() or (output / BUILD_RECORD).exists():
        raise ValueError("Installer output already exists; choose a new output directory.")
    with tempfile.TemporaryDirectory(prefix="nipat-macos-build-") as temporary:
        work = Path(temporary)
        native = dependencies["architectures"][architecture]
        python = dependency_archive(native["python"], work, python_archive)
        lima = dependency_archive(native["lima"], work, lima_archive)
        payload = work / "payload"
        app = stage_payload(project, payload, manifest, files, scientific, description,
                            architecture, python, lima, dependencies)
        subprocess.run(["/usr/bin/clang", "-Os", "-arch", architecture,
                        "-mmacosx-version-min=14.0", str(project / "installer/macos/launcher.c"),
                        "-o", str(app / "Contents/MacOS/NIPAT")], check=True)
        icons = work / "NIPAT.iconset"
        icons.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                destination = icons / f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["/usr/bin/sips", "-z", str(size * scale), str(size * scale),
                                str(project / "assets/branding/nipat-icon.png"),
                                "--out", str(destination)], check=True, capture_output=True)
        subprocess.run(["/usr/bin/iconutil", "-c", "icns", str(icons), "-o",
                        str(app / "Contents/Resources/NIPAT.icns")], check=True)
        scripts = work / "scripts"
        scripts.mkdir()
        subprocess.run(["/usr/bin/clang", "-Os", "-arch", architecture,
                        "-mmacosx-version-min=14.0", str(project / "installer/macos/package-guard.c"),
                        "-o", str(scripts / "preinstall")], check=True)
        shutil.copy2(scripts / "preinstall", scripts / "postinstall")
        sign_payload(app)
        inventory = payload_inventory(payload)
        components = work / "components.plist"
        subprocess.run(["/usr/bin/pkgbuild", "--analyze", "--root", str(payload), str(components)], check=True)
        component_entries = plistlib.loads(components.read_bytes())
        for component in component_entries:
            component.update({"BundleIsRelocatable": False, "BundleIsVersionChecked": True,
                              "BundleOverwriteAction": "upgrade"})
        components.write_bytes(plistlib.dumps(component_entries))
        subprocess.run(["/usr/bin/pkgbuild", "--root", str(payload), "--identifier", IDENTIFIER,
                        "--version", package_version(manifest["version"]), "--install-location", "/",
                        "--ownership", "recommended", "--scripts", str(scripts),
                        "--component-plist", str(components), str(work / "NIPAT-component.pkg")], check=True)
        (work / "Distribution.xml").write_text(distribution_xml(manifest["version"], architecture))
        welcome = (
            "NIPAT Experimental08\n\n"
            "Installs a separate experimental CLI application for macOS 14 or later.\n"
            "Python, Lima and the scientific image are included. Start NIPAT Experimental08\n"
            "from Applications after installation. The first start needs an Internet connection\n"
            "to prepare its dedicated Linux VM. On Apple Silicon, Rosetta for Linux is required.\n\n"
            "This package has no Developer ID signature or Apple notarization. Local security\n"
            "policy may prevent installation or launch. No security setting is changed.\n"
            "Runtime execution on physical Intel and Apple Silicon Macs is not yet qualified.\n"
            "Data and results remain in your Library/Application Support/NIPAT-Experimental08.\n")
        installer_resources = work / "installer-resources"
        installer_resources.mkdir()
        (installer_resources / "Welcome.txt").write_text(welcome)
        shutil.copyfile(project / "LICENSE", installer_resources / "LICENSE.txt")
        subprocess.run(["/usr/bin/productbuild", "--distribution", str(work / "Distribution.xml"),
                        "--resources", str(installer_resources), "--package-path", str(work), str(target)], check=True)
        record = {
            "schema_version": 1, "distribution": "self-contained-macos-lima",
            "version": manifest["version"], "source_commit": manifest["source_commit"],
            "architecture": architecture, "platform": "darwin", "package": target.name,
            "package_sha256": bundle.sha256_file(target), "package_size": target.stat().st_size,
            "scientific_asset_sha256": manifest["assets"]["scientific_image"]["sha256"],
            "runtime_image": manifest["runtime_image"], "runtime_vm_qualified": False,
            "manual_acceptance": False, "signing": "ad-hoc-app; unsigned-installer; not-notarized",
            "payload_inventory": inventory,
        }
        (output / BUILD_RECORD).write_text(json.dumps(record, indent=2) + "\n")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--engine-description", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--architecture", choices=("arm64", "x86_64"), required=True)
    parser.add_argument("--python-archive", type=Path)
    parser.add_argument("--lima-archive", type=Path)
    options = parser.parse_args()
    try:
        package = build(options.project.resolve(), options.manifest.resolve(), options.output.resolve(),
                        options.architecture, options.engine_description or options.manifest.parent / "engine-description.json",
                        options.python_archive, options.lima_archive)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, tarfile.TarError) as exc:
        parser.exit(1, f"Build macOS interrotta: {exc}\n")
    print(package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
