"""Export immutable WSL assets and stage the trusted inputs for Inno Setup."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "nipat_distribution_support", Path(__file__).with_name("distribution_support.py")
)
bundle = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bundle)
_COMPONENT_SPEC = importlib.util.spec_from_file_location(
    "nipat_runtime_component", Path(__file__).resolve().parents[1] / "installer/runtime/component.py"
)
component = importlib.util.module_from_spec(_COMPONENT_SPEC)
_COMPONENT_SPEC.loader.exec_module(component)

RELEASE_REPOSITORY = "GregorioDalia/nipat-desktop"
MAX_ASSET_BYTES = 2 * 1024**3  # GitHub release files must be smaller than 2 GiB.
MANIFEST_NAME = "installer-manifest.json"
APPLICATION_FILES_NAME = "application-files.json"
RUNTIME_INCLUDE_NAME = "runtime-assets.iss"
PROFILE_INCLUDE_NAME = "install-profile.iss"
PROFILE_PATH = Path("installer/windows/install-profile.json")
# This guard excludes Desktop and all other published installation identities.
# The JSON is the shared input for PowerShell, generated Inno directives and metadata.
EXPECTED_INSTALLATION_PROFILE = {
    "schema_version": 1,
    "channel": "experimental08",
    "display_name": "NIPAT Experimental08",
    "app_dir_name": "NIPAT-Experimental08",
    "data_dir_name": "NIPAT-Experimental08",
    "distro_prefix": "NIPAT-Experimental08-",
    "resume_key": "NIPAT-Experimental08-ResumeSetup",
    "mutex_prefix": "Local\\NIPAT-Experimental08-Setup-",
    "app_id": "A83D7E42-162C-438A-9B56-17F86C9F0800",
}


def validate_installation_profile(profile: dict) -> None:
    if (type(profile) is not dict or profile != EXPECTED_INSTALLATION_PROFILE
            or type(profile.get("schema_version")) is not int):
        raise ValueError("Profilo di installazione diverso dal canale NIPAT Experimental08.")


def installation_profile(project: Path) -> dict:
    profile = json.loads((project / PROFILE_PATH).read_text(encoding="utf-8"))
    validate_installation_profile(profile)
    return profile


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


def validate_rootfs_provenance(project: Path, rootfs_provenance: dict, source_commit: str) -> None:
    if not isinstance(rootfs_provenance, dict):
        raise ValueError("Provenienza del componente WSL non valida.")
    if rootfs_provenance.get("schema_version") == 2:
        if (rootfs_provenance.get("source_sha256") != component.source_inventory(project / "installer/runtime")
                or rootfs_provenance.get("component_sha256") != component.component_identity(rootfs_provenance)):
            raise ValueError("La provenienza del componente WSL non corrisponde ai suoi sorgenti.")
    elif (rootfs_provenance.get("vendor") != "nipat-desktop"
          or rootfs_provenance.get("schema_version") != 1
          or rootfs_provenance.get("source_commit") != source_commit):
        raise ValueError("La provenienza del rootfs non corrisponde ai sorgenti dell'installer.")


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
    validate_rootfs_provenance(project, rootfs_provenance, source_commit)
    version = checked_version(project)
    release_tag = f"v{version}"
    sources = bundle.source_files(project)
    return {
        "schema_version": 1,
        "installation_profile": installation_profile(project),
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


def reuse_rootfs(previous_directory: Path | None, expected: dict, destination: Path) -> dict | None:
    """Reuse exact published bytes only for the same freshly resolved component.

    Source pins alone are insufficient: the complete descriptor includes the
    actual installed APT and engine versions. Old schema-1 releases are not reused.
    """
    if previous_directory is None:
        return None
    previous = json.loads((previous_directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    validate_manifest(previous)
    provenance = previous.get("rootfs_provenance", {})
    if provenance.get("schema_version") != 2:
        return None
    identifier = component.component_identity(provenance)
    if provenance.get("component_sha256") != identifier:
        raise ValueError("Identita del componente WSL precedente non valida.")
    if identifier != component.component_identity(expected):
        return None
    metadata = previous["assets"]["rootfs"]
    archive = previous_directory / metadata["file"]
    if asset_metadata(archive, previous["release_tag"]) != metadata:
        raise ValueError("Archivio WSL precedente diverso dal manifest pubblicato.")
    with tarfile.open(archive, "r:gz") as contents:
        markers = [entry for entry in contents if entry.name in {"etc/nipat-runtime.json", "./etc/nipat-runtime.json"}]
        if len(markers) != 1 or not markers[0].isfile() or not 0 < markers[0].size < 1024 * 1024:
            raise ValueError("Provenienza WSL mancante o ambigua nell'archivio precedente.")
        with contents.extractfile(markers[0]) as stream:
            actual = json.load(stream)
    if (actual.get("component_sha256") != identifier
            or component.component_identity(actual) != identifier):
        raise ValueError("Il contenuto WSL precedente non corrisponde al componente dichiarato.")
    with archive.open("rb") as source, destination.open("xb") as target:
        shutil.copyfileobj(source, target)
    if bundle.sha256_file(destination) != metadata["sha256"]:
        destination.unlink()
        raise ValueError("La copia dell'archivio WSL precedente non e integra.")
    print("WSL: riutilizzato l'archivio verificato del componente " + identifier)
    return provenance


def export_assets(
    project: Path, output: Path, *, source_commit: str,
    scientific_reference: str, rootfs_reference: str, reuse_rootfs_directory: Path | None = None,
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
    provenance = json.loads(subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "cat", rootfs_details["Id"],
         "/etc/nipat-runtime.json"], check=True, capture_output=True, text=True, timeout=60,
    ).stdout)
    provenance["rootfs_image_id"] = rootfs_details["Id"]
    reused = reuse_rootfs(reuse_rootfs_directory, provenance, rootfs)
    if reused is not None:
        provenance = reused
    else:
        container = subprocess.run(
            ["docker", "create", rootfs_details["Id"]], check=True,
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", container):
            raise ValueError("Docker non ha restituito l'identificativo del container creato.")
        try:
            # Never-started container: no Docker daemon/image state is embedded.
            gzip_export(["docker", "container", "export", container], rootfs)
        finally:
            subprocess.run(["docker", "container", "rm", "--force", container], check=True)
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
    # Published pre-0.5 archives remain verifiable. This compatibility is read-only:
    # every WSL staging/include writer below independently requires the NIPAT Experimental08 profile.
    major_minor = tuple(int(part) for part in version.split(".")[:2])
    if major_minor == (0, 5):
        raise ValueError("Gli installer Preview 0.5 non appartengono al canale NIPAT Experimental08.")
    if major_minor >= (0, 5) or "installation_profile" in manifest:
        validate_installation_profile(manifest.get("installation_profile"))
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
    validate_installation_profile(manifest.get("installation_profile"))
    lines = ["; Generated from the verified installer manifest. Do not edit."]
    for key in ("rootfs", "scientific_image"):
        entry = manifest["assets"][key]
        lines.append(
            f'Source: "{{#RuntimeAssetsDir}}\\{entry["file"]}"; '
            'DestDir: "{code:GetNipatCacheDir}"; '
            f'DestName: "{entry["sha256"]}-{entry["file"]}"; '
            f'Hash: "{entry["sha256"]}"; '
            'Flags: ignoreversion uninsneveruninstall nocompression solidbreak'
        )
    return "\n".join(lines) + "\n"


def installation_profile_include(manifest: dict) -> str:
    """Generate the complete Windows identity from the same verified manifest."""
    validate_manifest(manifest)
    validate_installation_profile(manifest.get("installation_profile"))
    profile = manifest["installation_profile"]
    values = {
        "NipatVersion": manifest["version"],
        "NipatAppId": "{{" + profile["app_id"] + "}",
        "NipatDisplayName": profile["display_name"],
        "NipatAppDirectory": profile["app_dir_name"],
        "NipatDataDirectory": profile["data_dir_name"],
        "NipatResumeKey": profile["resume_key"],
    }
    return "; Generated from the verified installer manifest. Do not edit.\n" + "".join(
        f'#define {key} "{value}"\n' for key, value in values.items()
    )


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
    profile_include = stage / PROFILE_INCLUDE_NAME
    if profile_include.read_text(encoding="utf-8") != installation_profile_include(manifest):
        raise ValueError("Il profilo Inno di installazione non corrisponde al manifest.")
    if installation_profile(stage / "app") != manifest["installation_profile"]:
        raise ValueError("Il profilo incorporato non corrisponde al manifest.")
    return include


def stage_app(project: Path, manifest_path: Path, stage: Path, python_zip: Path) -> Path:
    project = project.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    validate_installation_profile(manifest.get("installation_profile"))
    if installation_profile(project) != manifest["installation_profile"]:
        raise ValueError("Profilo dei sorgenti diverso dal manifest runtime.")
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
    (stage / PROFILE_INCLUDE_NAME).write_text(installation_profile_include(manifest), encoding="utf-8")
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
        "status": "for-domain-validation",
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


def application_payload(stage: Path) -> dict:
    """Identify the complete Windows payload after compiling both executables."""
    app = stage / "app"
    if app.is_symlink():
        raise ValueError("La cartella applicativa non puo essere un collegamento.")
    manifest = json.loads((app / ".distribution" / MANIFEST_NAME).read_text(encoding="utf-8"))
    validate_manifest(manifest)
    validate_installation_profile(manifest.get("installation_profile"))
    source_hashes = manifest.get("source_sha256", {})
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ValueError("Inventario dei sorgenti mancante.")
    generated = {"release.json", "NIPAT.exe", "installer/windows/EnableWsl.exe",
                 f".distribution/{MANIFEST_NAME}", f".distribution/{bundle.PYTHON_NAME}"}
    inventory_path = f".distribution/{APPLICATION_FILES_NAME}"
    files = []
    seen = set()
    for path in sorted(app.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Il payload contiene un collegamento: {path}")
        if path.is_dir():
            continue
        relative = path.relative_to(app).as_posix()
        if relative == inventory_path:
            continue
        parts = relative.split("/")
        if (any(part in ("", ".", "..") or part.endswith((".", " ")) or
                re.search(r'[<>:"|?*\\\x00-\x1f]', part) or
                re.match(r"(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part)
                for part in parts) or parts[0].casefold() in {".git", ".runtime"} or
                relative.casefold() in seen):
            raise ValueError(f"Percorso payload non sicuro o ambiguo: {relative}")
        seen.add(relative.casefold())
        digest = bundle.sha256_file(path)
        if relative in source_hashes and digest != source_hashes[relative]:
            raise ValueError(f"Sorgente modificato dopo lo staging: {relative}")
        files.append({"path": relative, "sha256": digest})
    if {entry["path"] for entry in files} != set(source_hashes) | generated:
        raise ValueError("Il payload non corrisponde ai sorgenti e ai componenti generati previsti.")
    bundle.require_python_archive(app / ".distribution" / bundle.PYTHON_NAME)
    return {"schema_version": 1, "installation_channel": "experimental08",
            "source_commit": manifest["source_commit"], "files": files}


def write_application_payload(stage: Path) -> Path:
    payload = application_payload(stage)
    destination = stage / "app" / ".distribution" / APPLICATION_FILES_NAME
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return destination


def verify_application_payload(stage: Path) -> Path:
    expected = application_payload(stage)
    path = stage / "app" / ".distribution" / APPLICATION_FILES_NAME
    if json.loads(path.read_text(encoding="utf-8")) != expected:
        raise ValueError("L inventario applicativo non corrisponde ai file da installare.")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export", help="esporta immagini verificate e crea il manifest")
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--source-commit", required=True)
    export.add_argument("--scientific-image", required=True)
    export.add_argument("--rootfs-image", required=True)
    export.add_argument("--reuse-rootfs-directory", type=Path,
                        help="manifest e rootfs di una release pubblicata, riusati solo a identita completa uguale")
    stage = subparsers.add_parser("stage", help="prepara sorgenti approvati e incorporamento runtime per Inno Setup")
    stage.add_argument("--manifest", type=Path, required=True)
    stage.add_argument("--stage-dir", type=Path, required=True)
    stage.add_argument("--python-archive", type=Path)
    verify = subparsers.add_parser("verify-embedded", help="verifica gli asset e le istruzioni prima di compilare l installer unico")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--stage-dir", type=Path, required=True)
    verify.add_argument("--assets-dir", type=Path, required=True)
    for command in ("inventory", "verify-inventory"):
        inventory = subparsers.add_parser(command, help="registra o verifica i file applicativi per la riparazione")
        inventory.add_argument("--stage-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        project = args.project.resolve()
        if args.command == "export":
            result = export_assets(
                project, args.output_dir.resolve(), source_commit=args.source_commit,
                scientific_reference=args.scientific_image, rootfs_reference=args.rootfs_image,
                reuse_rootfs_directory=args.reuse_rootfs_directory,
            )
        elif args.command in ("inventory", "verify-inventory"):
            operation = write_application_payload if args.command == "inventory" else verify_application_payload
            result = operation(args.stage_dir)
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
