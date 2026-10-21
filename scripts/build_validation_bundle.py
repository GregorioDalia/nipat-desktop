"""Build a Windows validation ZIP without including local genomic data or runs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PYTHON_NAME = "python-3.12.10-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/3.12.10/{PYTHON_NAME}"
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
BASE_PUBLIC_COMMIT = "70e944b5dcbf84954492798dc387e8d61134343c"
DEFAULT_IMAGE = "nipat-scientific-runtime:0.1.0"
SOURCE_MANIFEST = "distribution-files.txt"
EXCLUDED_PARTS = {
    ".git", ".venv", ".runtime", ".distribution", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", "data", "runs", "logs", "dist", "build",
    "secrets", "credentials",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(project: Path) -> list[Path]:
    """Read the explicit source allowlist; unlisted local files are never inspected."""
    project = project.resolve()
    manifest = project / SOURCE_MANIFEST
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError(f"Manifest della distribuzione mancante o non valido: {manifest}")
    selected: list[Path] = []
    seen: set[str] = set()
    for number, raw_line in enumerate(manifest.read_text(encoding="utf-8-sig").splitlines(), start=1):
        relative = raw_line.strip()
        if not relative or relative.startswith("#"):
            continue
        parts = relative.split("/")
        if ("\\" in relative or ":" in relative
                or any(part in {"", ".", ".."} for part in parts)):
            raise ValueError(f"Percorso non valido nel manifest, riga {number}: {relative}")
        key = relative.casefold()
        if key in seen:
            raise ValueError(f"Percorso duplicato nel manifest: {relative}")
        seen.add(key)
        if any(part.lower() in EXCLUDED_PARTS or part.lower().endswith(".egg-info") for part in parts):
            raise ValueError(f"Cartella locale vietata nel manifest: {relative}")
        if any(part.lower() == ".env" for part in parts):
            raise ValueError(f"Configurazione privata vietata nel manifest: {relative}")
        path = project
        for part in parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f"Collegamento simbolico vietato nel manifest: {relative}")
        if not path.is_file() or not path.resolve().is_relative_to(project):
            raise ValueError(f"File approvato mancante o non valido: {relative}")
        selected.append(path)
    if SOURCE_MANIFEST not in {path.relative_to(project).as_posix() for path in selected}:
        raise ValueError(f"Il manifest deve includere se stesso: {SOURCE_MANIFEST}")
    return sorted(selected)


def require_python_archive(path: Path) -> Path:
    if not path.is_file() or sha256_file(path) != PYTHON_SHA256:
        raise ValueError(f"Archivio Python non valido o checksum errato: {path}")
    return path


def python_archive(project: Path, requested: Path | None, temporary: Path) -> Path:
    if requested is not None:
        return require_python_archive(requested)
    bundled = project / ".distribution" / PYTHON_NAME
    if bundled.is_file():
        return require_python_archive(bundled)
    destination = temporary / PYTHON_NAME
    print(f"Download di Python portabile da {PYTHON_URL}", flush=True)
    with urllib.request.urlopen(PYTHON_URL, timeout=120) as response, destination.open("xb") as target:
        while chunk := response.read(1024 * 1024):
            target.write(chunk)
    return require_python_archive(destination)


def git_source(project: Path) -> dict:
    # No repository is also valid: the release manifest and source hashes identify a ZIP.
    if not (project / ".git").exists():
        return {"commit": None, "dirty": None, "available": False}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, check=True,
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=project,
            check=True, capture_output=True, text=True, timeout=15,
        ).stdout
        return {"commit": commit, "dirty": bool(status), "available": True}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None, "available": False}


def selected_image(project: Path, requested: str | None) -> str:
    if requested:
        return requested
    saved = project / ".runtime" / "runtime-image.txt"
    if saved.is_file():
        image = saved.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise ValueError("Identificativo in .runtime/runtime-image.txt non valido.")
        return image
    return os.environ.get("NIPAT_RUNTIME_IMAGE", DEFAULT_IMAGE)


def export_runtime(project: Path, image: str, temporary: Path) -> tuple[Path, dict]:
    print(f"Verifica dell'immagine Docker locale: {image}", flush=True)
    result = subprocess.run(
        ["docker", "image", "inspect", image], check=True,
        capture_output=True, text=True, timeout=60,
    )
    images = json.loads(result.stdout)
    if not isinstance(images, list) or len(images) != 1:
        raise ValueError("Docker non ha restituito una singola immagine.")
    details = images[0]
    image_id = details.get("Id", "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
        raise ValueError("Docker ha restituito un identificativo immagine non valido.")
    if details.get("Os") != "linux" or details.get("Architecture") != "amd64":
        raise ValueError("Il pacchetto Windows x64 richiede un'immagine Linux amd64.")
    destination = temporary / "runtime.tar"
    print("Esportazione del runtime Docker (l'archivio puo' essere voluminoso)...", flush=True)
    subprocess.run(["docker", "image", "save", "--output", str(destination), image_id], check=True)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ValueError("Docker non ha prodotto un archivio runtime valido.")
    metadata = {
        "schema_version": 1,
        "image_id": image_id,
        "source_reference": image,
        "os": details["Os"],
        "architecture": details["Architecture"],
        "archive_sha256": sha256_file(destination),
        "archive_bytes": destination.stat().st_size,
    }
    return destination, metadata


def require_launcher(path: Path) -> Path:
    """Accept only an explicit Windows x64 PE; never harvest local executables."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Launcher mancante o collegamento simbolico: {path}")
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError("Il launcher deve essere un eseguibile Windows x64.")
        offset = struct.unpack_from("<I", header, 60)[0]
        if offset < 64 or offset > path.stat().st_size - 26:
            raise ValueError("Intestazione PE del launcher non valida.")
        stream.seek(offset)
        pe = stream.read(26)
        if (pe[:4] != b"PE\0\0" or struct.unpack_from("<H", pe, 4)[0] != 0x8664
                or struct.unpack_from("<H", pe, 24)[0] != 0x20B):
            raise ValueError("Il launcher deve essere un eseguibile Windows x64 PE32+.")
    return path


def verified_installer_runtime(project: Path, archive: Path, manifest_path: Path) -> tuple[Path, dict]:
    """Reuse the exact verified WSL scientific asset without a local Docker engine."""
    spec = importlib.util.spec_from_file_location(
        "nipat_installer_assets_for_bundle", Path(__file__).with_name("build_windows_installer_assets.py")
    )
    installer_assets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer_assets)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Manifest installer mancante o non valido.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    installer_assets.validate_manifest(manifest)
    if installer_assets.checked_version(project) != manifest["version"]:
        raise ValueError("Versione dei sorgenti diversa dal manifest runtime.")
    hashes = {path.relative_to(project.resolve()).as_posix(): sha256_file(path)
              for path in source_files(project)}
    if hashes != manifest.get("source_sha256"):
        raise ValueError("I sorgenti non corrispondono al manifest compilato in CI.")
    source = git_source(project)
    if source["available"] and (source["commit"] != manifest["source_commit"] or source["dirty"] is not False):
        raise ValueError("Il checkout Git deve essere pulito e corrispondere al commit del manifest.")
    asset = manifest["assets"]["scientific_image"]
    if (archive.name != asset["file"] or archive.is_symlink() or not archive.is_file()
            or archive.stat().st_size != asset["size"] or sha256_file(archive) != asset["sha256"]):
        raise ValueError("Archivio scientifico diverso da quello verificato nel manifest.")
    with archive.open("rb") as stream:
        if stream.read(2) != b"\x1f\x8b":
            raise ValueError("L'archivio scientifico verificato deve essere gzip.")
    return archive, {
        "schema_version": 1,
        "image_id": manifest["runtime_image"],
        "source_reference": manifest["release_tag"],
        "os": "linux",
        "architecture": "amd64",
        "archive_sha256": asset["sha256"],
        "archive_bytes": asset["size"],
        "source_commit": manifest["source_commit"],
        "installer_manifest_sha256": sha256_file(manifest_path),
    }


def package_sources(
    project: Path, destination: Path, python_zip: Path,
    runtime_archive: Path | None = None, runtime_metadata: dict | None = None,
    launcher: Path | None = None,
) -> dict:
    project = project.resolve()
    files = source_files(project)
    mandatory = {"compose.yaml", "pyproject.toml", "1_SETUP.cmd", "2_AVVIA.cmd", "nipat.cmd"}
    names = {path.relative_to(project).as_posix() for path in files}
    if not mandatory.issubset(names):
        raise ValueError(f"Pacchetto sorgente incompleto: {sorted(mandatory - names)}")
    if (runtime_archive is None) != (runtime_metadata is None):
        raise ValueError("Archivio e manifest runtime devono essere forniti insieme.")
    if launcher is not None:
        require_launcher(launcher)
        if any(name.casefold() == "nipat.exe" for name in names):
            raise ValueError("NIPAT.exe deve essere fornito come launcher, non nel manifest sorgente.")
    import tomllib
    with (project / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    hashes = {path.relative_to(project).as_posix(): sha256_file(path) for path in files}
    release = {
        "schema_version": 1,
        "package_version": version,
        "status": "alpha-for-domain-validation",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_public_commit": BASE_PUBLIC_COMMIT,
        "source_git": git_source(project),
        "source_sha256": hashes,
        "python": {"version": "3.12.10", "architecture": "amd64", "archive_sha256": PYTHON_SHA256},
        "runtime": runtime_metadata,
    }
    if launcher is not None:
        release["launcher"] = {
            "file": "NIPAT.exe", "sha256": sha256_file(launcher), "size": launcher.stat().st_size,
        }
    prior_release = project / "release.json"
    if prior_release.is_file():
        previous = json.loads(prior_release.read_text(encoding="utf-8"))
        release["parent_release"] = {
            "package_version": previous.get("package_version"),
            "built_at_utc": previous.get("built_at_utc"),
            "manifest_sha256": sha256_file(prior_release),
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        # Exclusive create protects previous handoff packages, including concurrent builds.
        with destination.open("xb") as output:
            created = True
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for source in files:
                    relative = source.relative_to(project).as_posix()
                    archive.write(source, f"nipat-desktop/{relative}")
                archive.writestr("nipat-desktop/release.json", json.dumps(release, indent=2, ensure_ascii=False) + "\n")
                archive.write(python_zip, f"nipat-desktop/.distribution/{PYTHON_NAME}", compress_type=zipfile.ZIP_STORED)
                if launcher is not None:
                    archive.write(launcher, "nipat-desktop/NIPAT.exe")
                if runtime_archive is not None:
                    with runtime_archive.open("rb") as stream:
                        compressed = stream.read(2) == b"\x1f\x8b"
                    # docker load detects gzip from content; retain the portable setup's path.
                    archive.write(runtime_archive, "nipat-desktop/.distribution/runtime.tar",
                                  compress_type=zipfile.ZIP_STORED if compressed else zipfile.ZIP_DEFLATED)
                    archive.writestr("nipat-desktop/.distribution/runtime.json", json.dumps(runtime_metadata, indent=2) + "\n")
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="nuovo ZIP, mai sovrascritto")
    parser.add_argument("--python-archive", type=Path, help="ZIP Python 3.12.10 x64; altrimenti scaricato dal sito ufficiale")
    parser.add_argument("--include-runtime", action="store_true", help="include l'immagine Docker locale, senza ricostruirla")
    parser.add_argument("--runtime-image", help="tag o ID locale da esportare; predefinito: runtime configurato")
    parser.add_argument("--runtime-archive", type=Path, help="asset scientifico gzip della build installer verificata")
    parser.add_argument("--runtime-manifest", type=Path, help="installer-manifest.json della stessa build")
    parser.add_argument("--launcher", type=Path, help="NIPAT.exe x64 compilato e verificato dalla CI Windows")
    args = parser.parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    destination = args.output.expanduser().resolve()
    try:
        if destination.exists():
            raise ValueError(f"Il pacchetto esiste gia': {destination}")
        if args.runtime_image and not args.include_runtime:
            raise ValueError("--runtime-image richiede --include-runtime.")
        if bool(args.runtime_archive) != bool(args.runtime_manifest):
            raise ValueError("--runtime-archive e --runtime-manifest devono essere forniti insieme.")
        if args.runtime_archive and (args.include_runtime or args.runtime_image):
            raise ValueError("Usare l'archivio verificato oppure l'esportazione Docker locale, non entrambi.")
        if args.launcher is not None:
            require_launcher(args.launcher)
        with tempfile.TemporaryDirectory(prefix="nipat-bundle-") as directory:
            temporary = Path(directory)
            portable = python_archive(project, args.python_archive, temporary)
            runtime = metadata = None
            if args.include_runtime:
                runtime, metadata = export_runtime(project, selected_image(project, args.runtime_image), temporary)
            elif args.runtime_archive:
                runtime, metadata = verified_installer_runtime(project, args.runtime_archive, args.runtime_manifest)
            release = package_sources(project, destination, portable, runtime, metadata, args.launcher)
        print(f"Pacchetto creato: {destination}")
        print(f"Versione: {release['package_version']}; runtime Docker incluso: {'si' if metadata else 'no'}")
        print(f"SHA256: {sha256_file(destination)}")
        if not metadata:
            print("Al primo setup il runtime verra' costruito; per il trasferimento autosufficiente usare --include-runtime.")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Creazione pacchetto fallita: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
