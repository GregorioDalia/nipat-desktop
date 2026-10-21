"""Export immutable WSL assets and stage the trusted inputs for Inno Setup."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "nipat_validation_bundle", Path(__file__).with_name("build_validation_bundle.py")
)
bundle = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bundle)

RELEASE_REPOSITORY = "GregorioDalia/nipat-desktop"
MAX_ASSET_BYTES = 2 * 1024**3  # GitHub release files must be smaller than 2 GiB.
MANIFEST_NAME = "installer-manifest.json"
RUNTIME_INCLUDE_NAME = "runtime-assets.iss"


def checked_version(project: Path) -> str:
    import tomllib
    with (project / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:a[0-9]+|b[0-9]+|rc[0-9]+)?", version):
        raise ValueError("Versione del pacchetto non valida per gli asset dell'installer.")
    return version


def asset_metadata(path: Path, release_tag: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Asset mancante o collegamento simbolico: {path}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz", path.name):
        raise ValueError(f"Nome asset non valido: {path.name}")
    size = path.stat().st_size
    if not 0 < size < MAX_ASSET_BYTES:
        raise ValueError(f"Asset vuoto o >= 2 GiB: {path.name} ({size} byte)")
    with path.open("rb") as handle:
        if handle.read(2) != b"\x1f\x8b":
            raise ValueError(f"Asset non compresso con gzip: {path.name}")
    return {
        "file": path.name,
        "sha256": bundle.sha256_file(path),
        "size": size,
        "url": f"https://github.com/{RELEASE_REPOSITORY}/releases/download/{release_tag}/{path.name}",
    }


def inspect_image(reference: str) -> dict:
    result = subprocess.run(
        ["docker", "image", "inspect", reference], check=True,
        capture_output=True, text=True, timeout=60,
    )
    images = json.loads(result.stdout)
    if not isinstance(images, list) or len(images) != 1:
        raise ValueError("Docker deve restituire una sola immagine.")
    details = images[0]
    if (details.get("Os"), details.get("Architecture")) != ("linux", "amd64"):
        raise ValueError("Gli asset Windows x64 richiedono immagini Linux amd64.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", details.get("Id", "")):
        raise ValueError("Identificativo immagine Docker non valido.")
    return details


def gzip_export(command: list[str], destination: Path) -> None:
    """Stream Docker's tar output without storing a second uncompressed copy."""
    created = False
    try:
        with destination.open("xb") as target, tempfile.TemporaryFile() as errors:
            created = True
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
            try:
                with gzip.GzipFile(filename="", fileobj=target, mode="wb", mtime=0) as archive:
                    shutil.copyfileobj(process.stdout, archive, length=1024 * 1024)
                process.stdout.close()
                returncode = process.wait()
            except BaseException:
                process.kill()
                process.wait()
                raise
            if returncode:
                errors.seek(0)
                detail = errors.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Esportazione Docker fallita ({returncode}): {detail}")
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def make_manifest(
    project: Path, *, source_commit: str, runtime_image: str,
    rootfs: Path, scientific_image: Path, rootfs_provenance: dict,
) -> dict:
    # source_files canonicalizes paths, including Windows 8.3 aliases.
    project = project.resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit deve essere lo SHA Git completo dei sorgenti compilati.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", runtime_image):
        raise ValueError("runtime_image deve essere l'ID immutabile dell'immagine scientifica.")
    if (rootfs_provenance.get("vendor") != "nipat-desktop"
            or rootfs_provenance.get("schema_version") != 1
            or rootfs_provenance.get("source_commit") != source_commit):
        raise ValueError("La provenienza del rootfs non corrisponde ai sorgenti dell'installer.")
    version = checked_version(project)
    release_tag = f"v{version}"
    sources = bundle.source_files(project)
    return {
        "schema_version": 1,
        "version": version,
        "release_tag": release_tag,
        "source_commit": source_commit,
        "runtime_image": runtime_image,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "assets": {
            "rootfs": asset_metadata(rootfs, release_tag),
            "scientific_image": asset_metadata(scientific_image, release_tag),
        },
        "rootfs_provenance": rootfs_provenance,
        "source_sha256": {
            path.relative_to(project).as_posix(): bundle.sha256_file(path) for path in sources
        },
    }


def export_assets(
    project: Path, output: Path, *, source_commit: str,
    scientific_reference: str, rootfs_reference: str,
) -> Path:
    source = bundle.git_source(project)
    if source.get("commit") != source_commit or source.get("dirty") is not False:
        raise ValueError("L'esportazione richiede un checkout Git pulito allo SHA indicato.")
    version = checked_version(project)
    output.mkdir(parents=True, exist_ok=False)
    scientific_details = inspect_image(scientific_reference)
    rootfs_details = inspect_image(rootfs_reference)
    scientific = output / f"nipat-scientific-runtime-{version}-amd64.tar.gz"
    rootfs = output / f"nipat-wsl-rootfs-{version}-amd64.tar.gz"
    gzip_export(["docker", "image", "save", scientific_details["Id"]], scientific)
    container = subprocess.run(
        ["docker", "create", rootfs_details["Id"]], check=True,
        capture_output=True, text=True, timeout=60,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", container):
        raise ValueError("Docker non ha restituito l'identificativo del container creato.")
    try:
        # Export a fresh, never-started container: no Docker daemon/image state is embedded.
        gzip_export(["docker", "container", "export", container], rootfs)
    finally:
        subprocess.run(["docker", "container", "rm", "--force", container], check=True)
    provenance = json.loads(subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "cat", rootfs_details["Id"],
         "/etc/nipat-runtime.json"], check=True, capture_output=True, text=True, timeout=60,
    ).stdout)
    provenance["rootfs_image_id"] = rootfs_details["Id"]
    manifest = make_manifest(
        project, source_commit=source_commit, runtime_image=scientific_details["Id"],
        rootfs=rootfs, scientific_image=scientific, rootfs_provenance=provenance,
    )
    destination = output / MANIFEST_NAME
    destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "SHA256SUMS").write_text(
        "".join(f"{entry['sha256']}  {entry['file']}\n" for entry in manifest["assets"].values())
        + f"{bundle.sha256_file(destination)}  {MANIFEST_NAME}\n", encoding="ascii",
    )
    return destination


def validate_manifest(manifest: dict) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("Schema del manifest installer non supportato.")
    version = manifest.get("version", "")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:a[0-9]+|b[0-9]+|rc[0-9]+)?", version):
        raise ValueError("Versione nel manifest non valida.")
    tag = manifest.get("release_tag")
    if tag != f"v{version}":
        raise ValueError("Release tag diverso dalla versione del manifest.")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("source_commit", "")):
        raise ValueError("Commit nel manifest non valido.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest.get("runtime_image", "")):
        raise ValueError("Immagine scientifica nel manifest non valida.")
    assets = manifest.get("assets", {})
    if set(assets) != {"rootfs", "scientific_image"}:
        raise ValueError("Il manifest deve contenere esattamente i due asset runtime.")
    if str(assets["rootfs"].get("file", "")).casefold() == str(assets["scientific_image"].get("file", "")).casefold():
        raise ValueError("I due asset runtime devono avere nomi distinti.")
    for entry in assets.values():
        name = entry.get("file", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz", name):
            raise ValueError("Nome file non sicuro nel manifest.")
        expected_url = f"https://github.com/{RELEASE_REPOSITORY}/releases/download/{tag}/{name}"
        if entry.get("url") != expected_url:
            raise ValueError("URL di download diverso dalla release prevista.")
        if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
            raise ValueError("SHA-256 mancante o non valido.")
        size = entry.get("size")
        if type(size) is not int or not 0 < size < MAX_ASSET_BYTES:
            raise ValueError("Dimensione asset non valida o >= 2 GiB.")


def verify_runtime_assets(manifest: dict, asset_directory: Path) -> None:
    """Check the exact archive bytes used by the compiler, not only their names."""
    validate_manifest(manifest)
    for entry in manifest["assets"].values():
        actual = asset_metadata(asset_directory / entry["file"], manifest["release_tag"])
        if actual != entry:
            raise ValueError(f"Asset incorporato diverso dal manifest: {entry['file']}")


def runtime_assets_include(manifest: dict) -> str:
    """Emit portable Inno inputs; each embedded archive becomes its persistent cache file."""
    validate_manifest(manifest)
    lines = ["; Generated from the verified installer manifest. Do not edit."]
    for key in ("rootfs", "scientific_image"):
        entry = manifest["assets"][key]
        lines.append(
            f'Source: "{{#RuntimeAssetsDir}}\\{entry["file"]}"; '
            'DestDir: "{localappdata}\\NIPAT\\cache"; '
            f'DestName: "{entry["sha256"]}-{entry["file"]}"; '
            f'Hash: "{entry["sha256"]}"; '
            'Flags: ignoreversion uninsneveruninstall nocompression solidbreak'
        )
    return "\n".join(lines) + "\n"


def verify_embedded_inputs(manifest_path: Path, stage: Path, asset_directory: Path) -> Path:
    """Recheck downloaded CI artifacts immediately before Windows compilation."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_runtime_assets(manifest, asset_directory)
    embedded_manifest = stage / "app" / ".distribution" / MANIFEST_NAME
    if embedded_manifest.read_bytes() != manifest_path.read_bytes():
        raise ValueError("Il manifest incorporato e diverso dal manifest degli asset.")
    include = stage / RUNTIME_INCLUDE_NAME
    if include.read_text(encoding="utf-8") != runtime_assets_include(manifest):
        raise ValueError("Le istruzioni di incorporamento degli asset non corrispondono al manifest.")
    return include


def stage_app(project: Path, manifest_path: Path, stage: Path, python_zip: Path) -> Path:
    project = project.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    if checked_version(project) != manifest["version"]:
        raise ValueError("Versione dei sorgenti diversa dal manifest runtime.")
    files = bundle.source_files(project)
    hashes = {path.relative_to(project).as_posix(): bundle.sha256_file(path) for path in files}
    if hashes != manifest.get("source_sha256"):
        raise ValueError("I sorgenti non corrispondono al manifest compilato in CI.")
    verify_runtime_assets(manifest, manifest_path.parent)
    bundle.require_python_archive(python_zip)
    stage.mkdir(parents=True, exist_ok=False)
    (stage / RUNTIME_INCLUDE_NAME).write_text(runtime_assets_include(manifest), encoding="utf-8")
    app = stage / "app"
    for source in files:
        target = app / source.relative_to(project)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    distribution = app / ".distribution"
    distribution.mkdir()
    shutil.copyfile(manifest_path, distribution / MANIFEST_NAME)
    shutil.copyfile(python_zip, distribution / bundle.PYTHON_NAME)
    release = {
        "schema_version": 1,
        "package_version": manifest["version"],
        "status": "alpha-for-domain-validation",
        "built_at_utc": manifest.get("built_at_utc"),
        "source_git": {"commit": manifest["source_commit"], "dirty": False, "available": True},
        "source_sha256": hashes,
        "installer_manifest_sha256": bundle.sha256_file(manifest_path),
        "python": {"version": "3.12.10", "architecture": "amd64",
                   "archive_sha256": bundle.PYTHON_SHA256},
        "runtime": {"image_id": manifest["runtime_image"]},
    }
    (app / "release.json").write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export", help="esporta immagini verificate e crea il manifest")
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--source-commit", required=True)
    export.add_argument("--scientific-image", required=True)
    export.add_argument("--rootfs-image", required=True)
    stage = subparsers.add_parser("stage", help="prepara sorgenti approvati e incorporamento runtime per Inno Setup")
    stage.add_argument("--manifest", type=Path, required=True)
    stage.add_argument("--stage-dir", type=Path, required=True)
    stage.add_argument("--python-archive", type=Path)
    verify = subparsers.add_parser("verify-embedded", help="verifica gli asset e le istruzioni prima di compilare l installer unico")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--stage-dir", type=Path, required=True)
    verify.add_argument("--assets-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        project = args.project.resolve()
        if args.command == "export":
            result = export_assets(
                project, args.output_dir.resolve(), source_commit=args.source_commit,
                scientific_reference=args.scientific_image, rootfs_reference=args.rootfs_image,
            )
        elif args.command == "verify-embedded":
            result = verify_embedded_inputs(args.manifest, args.stage_dir, args.assets_dir)
        else:
            with tempfile.TemporaryDirectory() as temporary:
                archive = bundle.python_archive(project, args.python_archive, Path(temporary))
                result = stage_app(project, args.manifest, args.stage_dir.resolve(), archive)
        print(result)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Preparazione installer fallita: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
