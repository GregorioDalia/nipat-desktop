"""Stage a verified Docker Desktop bundle and bind its single-file Inno installer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import stat
import zipfile
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "nipat_installer_assets", Path(__file__).with_name("build_windows_installer_assets.py")
)
assets = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(assets)
bundle = assets.bundle

MARKER_NAME = ".distribution/docker-desktop.json"
MARKER_BYTES = b'{"schema_version":1,"distribution":"docker-desktop-installer"}\n'
INSTALLER_NAME = "NIPAT-DockerDesktop-Setup.exe"
EVIDENCE_NAME = "docker-installer-build.json"
FILES_INCLUDE = "docker-files.iss"
VERSION_INCLUDE = "docker-version.iss"
PREFIX = "nipat-desktop/"
MAX_BYTES = 2 * 1024**3


def _regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"File mancante o collegamento simbolico: {path}")


def _path(relative: str) -> str:
    # The same string is used on Windows and in generated Inno source code.
    if (not isinstance(relative, str) or not relative
            or any(char in relative for char in '\\:"{};*?<>|')
            or any(ord(char) < 32 for char in relative)
            or any(part in {"", ".", ".."} or part.endswith((".", " "))
                   for part in relative.split("/"))):
        raise ValueError(f"Percorso del pacchetto non sicuro: {relative!r}")
    for part in relative.split("/"):
        if re.fullmatch(r"(?i)(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part):
            raise ValueError(f"Nome Windows riservato: {relative}")
    return relative


def _stream_hash(handle) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def inspect_package(package: Path, manifest_path: Path, launcher: Path) -> dict:
    """Verify all bytes before extracting; return the exact installed-file contract."""
    for path in (package, manifest_path, launcher):
        _regular(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets.validate_manifest(manifest)
    bundle.require_launcher(launcher)
    version = manifest["version"]
    if package.name != f"NIPAT-DockerDesktop-{version}-windows-x64.zip":
        raise ValueError("Nome del bundle Docker Desktop diverso dalla versione verificata.")
    if not 0 < package.stat().st_size < MAX_BYTES:
        raise ValueError("Bundle Docker Desktop vuoto o >= 2 GiB.")
    package_hash = bundle.sha256_file(package)
    launcher_hash = bundle.sha256_file(launcher)
    manifest_hash = bundle.sha256_file(manifest_path)
    expected_build = {
        "schema_version": 1, "version": version,
        "source_commit": manifest["source_commit"], "file": package.name,
        "sha256": package_hash, "size": package.stat().st_size,
        "launcher_sha256": launcher_hash,
    }
    build_path = package.parent / "package-build.json"
    _regular(build_path)
    if json.loads(build_path.read_text(encoding="utf-8-sig")) != expected_build:
        raise ValueError("La provenienza del bundle Docker Desktop non corrisponde ai file.")
    scientific = manifest["assets"]["scientific_image"]
    runtime = {
        "schema_version": 1, "image_id": manifest["runtime_image"],
        "source_reference": manifest["release_tag"], "os": "linux", "architecture": "amd64",
        "archive_sha256": scientific["sha256"], "archive_bytes": scientific["size"],
        "source_commit": manifest["source_commit"], "installer_manifest_sha256": manifest_hash,
    }
    sources = manifest.get("source_sha256")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("Manifest dei sorgenti assente.")
    for name, digest in sources.items():
        _path(name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Hash sorgente non valido.")
    extra = {"release.json", "NIPAT.exe", f".distribution/{bundle.PYTHON_NAME}",
             ".distribution/runtime.tar", ".distribution/runtime.json"}
    if set(sources) & (extra | {MARKER_NAME}):
        raise ValueError("I sorgenti non possono sostituire i metadati della distribuzione.")
    expected_names = set(sources) | extra
    if len({name.casefold() for name in expected_names | {MARKER_NAME}}) != len(expected_names) + 1:
        raise ValueError("Percorsi duplicati senza distinzione maiuscole/minuscole.")
    installed_hashes = {}
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        if len(entries) != len(expected_names) or {info.filename for info in entries} != {
                PREFIX + name for name in expected_names}:
            raise ValueError("Il bundle contiene file mancanti, duplicati o non previsti.")
        for info in entries:
            if info.is_dir() or info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Il bundle deve contenere solo file regolari non cifrati.")
            _path(info.filename)
        release = json.loads(archive.read(PREFIX + "release.json"))
        if (release.get("schema_version") != 1 or release.get("package_version") != version
                or release.get("source_git") != {"commit": manifest["source_commit"],
                                                  "dirty": False, "available": True}
                or release.get("source_sha256") != sources
                or release.get("runtime") != runtime
                or json.loads(archive.read(PREFIX + ".distribution/runtime.json")) != runtime
                or release.get("python") != {"version": "3.12.10", "architecture": "amd64",
                                              "archive_sha256": bundle.PYTHON_SHA256}
                or release.get("launcher") != {"file": "NIPAT.exe", "sha256": launcher_hash,
                                                "size": launcher.stat().st_size}):
            raise ValueError("I metadati del bundle non corrispondono al manifest verificato.")
        expected_hashes = {**sources, "NIPAT.exe": launcher_hash,
                           f".distribution/{bundle.PYTHON_NAME}": bundle.PYTHON_SHA256,
                           ".distribution/runtime.tar": scientific["sha256"]}
        for name in sorted(expected_names):
            with archive.open(PREFIX + name) as handle:
                digest = _stream_hash(handle)
            if name in expected_hashes and digest != expected_hashes[name]:
                raise ValueError(f"Checksum del bundle non valido: {name}")
            installed_hashes[name] = digest
        if (archive.getinfo(PREFIX + ".distribution/runtime.tar").file_size != scientific["size"]
                or archive.getinfo(PREFIX + "NIPAT.exe").file_size != launcher.stat().st_size):
            raise ValueError("Dimensione del runtime o del launcher non valida.")
        with archive.open(PREFIX + ".distribution/runtime.tar") as handle:
            if handle.read(2) != b"\x1f\x8b":
                raise ValueError("Il runtime scientifico deve essere l'archivio gzip verificato.")
    installed_hashes[MARKER_NAME] = hashlib.sha256(MARKER_BYTES).hexdigest()
    return {
        "schema_version": 1, "distribution": "self-contained-docker-desktop",
        "version": version, "source_commit": manifest["source_commit"],
        "package_file": package.name, "package_bytes": package.stat().st_size,
        "package_sha256": package_hash, "installer_manifest_sha256": manifest_hash,
        "launcher_sha256": launcher_hash, "runtime_archive_sha256": scientific["sha256"],
        "runtime_archive_bytes": scientific["size"],
        "staged_files_sha256": dict(sorted(installed_hashes.items())),
    }


def files_include(record: dict) -> str:
    lines = ["; Generated from the verified Docker Desktop package. Do not edit."]
    for relative, digest in record["staged_files_sha256"].items():
        _path(relative)
        winpath = relative.replace("/", "\\")
        parent = relative.rpartition("/")[0].replace("/", "\\")
        destination = "{app}" + ("\\" + parent if parent else "")
        flags = "ignoreversion"
        if relative in {".distribution/runtime.tar", f".distribution/{bundle.PYTHON_NAME}"}:
            flags += " nocompression solidbreak"
        lines.append(f'Source: "{{#StageDir}}\\app\\{winpath}"; DestDir: "{destination}"; '
                     f'Hash: "{digest}"; Flags: {flags}')
    return "\n".join(lines) + "\n"


def version_include(record: dict) -> str:
    return f'#define NipatVersion "{record["version"]}"\n'


def stage_package(package: Path, manifest_path: Path, launcher: Path, stage: Path) -> dict:
    record = inspect_package(package, manifest_path, launcher)
    stage.mkdir(parents=True, exist_ok=False)
    app = stage / "app"
    app.mkdir()
    with zipfile.ZipFile(package) as archive:
        for name in record["staged_files_sha256"]:
            destination = app / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if name == MARKER_NAME:
                destination.write_bytes(MARKER_BYTES)
            else:
                with archive.open(PREFIX + name) as source, destination.open("xb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
    (stage / FILES_INCLUDE).write_text(files_include(record), encoding="utf-8", newline="\n")
    (stage / VERSION_INCLUDE).write_text(version_include(record), encoding="ascii", newline="\n")
    verify_stage(package, manifest_path, launcher, stage)
    return record


def verify_stage(package: Path, manifest_path: Path, launcher: Path, stage: Path) -> dict:
    record = inspect_package(package, manifest_path, launcher)
    app = stage / "app"
    if stage.is_symlink() or app.is_symlink() or not app.is_dir():
        raise ValueError("Directory di staging non valida.")
    for child in stage.rglob("*"):
        if child.is_symlink():
            raise ValueError(f"Collegamento simbolico nello staging: {child}")
    expected = {"app/" + name for name in record["staged_files_sha256"]} | {FILES_INCLUDE, VERSION_INCLUDE}
    actual = {path.relative_to(stage).as_posix() for path in stage.rglob("*") if path.is_file()}
    if actual != expected:
        raise ValueError("Lo staging contiene file mancanti o non previsti.")
    for name, digest in record["staged_files_sha256"].items():
        if bundle.sha256_file(app / name) != digest:
            raise ValueError(f"File dello staging modificato: {name}")
    if ((stage / FILES_INCLUDE).read_bytes() != files_include(record).encode("utf-8")
            or (stage / VERSION_INCLUDE).read_bytes() != version_include(record).encode("ascii")):
        raise ValueError("Le istruzioni Inno non corrispondono allo staging verificato.")
    return record


def record_installer(package: Path, manifest_path: Path, launcher: Path, stage: Path, output: Path) -> Path:
    record = verify_stage(package, manifest_path, launcher, stage)
    executable = output / INSTALLER_NAME
    _regular(executable)
    if any(path.suffix.casefold() == ".bin" for path in output.rglob("*")):
        raise ValueError("L'installer deve essere un unico EXE senza file .bin separati.")
    size = executable.stat().st_size
    if not 0 < size < MAX_BYTES:
        raise ValueError("Installer vuoto o >= 2 GiB.")
    with executable.open("rb") as handle:
        if handle.read(2) != b"MZ":
            raise ValueError("Il risultato non e' un eseguibile Windows.")
    record.update(file=INSTALLER_NAME, size=size, sha256=bundle.sha256_file(executable))
    destination = output / EVIDENCE_NAME
    if destination.exists() or destination.is_symlink():
        raise ValueError("Il rapporto dell'installer esiste gia'.")
    destination.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "verify", "record"))
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    arguments = (args.package, args.manifest, args.launcher, args.stage_dir)
    if args.command == "stage":
        stage_package(*arguments)
    elif args.command == "verify":
        verify_stage(*arguments)
    else:
        if args.output_dir is None:
            parser.error("record richiede --output-dir")
        record_installer(*arguments, args.output_dir)
    print(f"Docker Desktop installer: {args.command} verificato.")


if __name__ == "__main__":
    main()
