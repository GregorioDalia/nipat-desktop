"""Build the Ubuntu installer from the exact verified Windows scientific archive.

This builder does not pull or rebuild images, provision Docker, or modify the
host. The package manager installs root-owned application files; preparation of
the included image happens later under the invoking user's account.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile


_SPEC = importlib.util.spec_from_file_location(
    "nipat_linux_common_assets", Path(__file__).with_name("build_windows_installer_assets.py")
)
assets = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(assets)
bundle = assets.bundle

PACKAGE = "nipat-desktop"
COMMAND = "nipat"
APP_PATH = Path("opt") / PACKAGE
LAUNCH_SOURCE = "installer/linux/launch.py"
ACTIVITY_DIRECTORY = "/var/lib/nipat-desktop"
ICON_SOURCE = "assets/branding/nipat-symbol.svg"
BUILD_RECORD = "linux-installer-build.json"
DEPENDENCIES = (
    "python3.12 (>= 3.12), python3.12 (<< 3.13), "
    "docker.io | docker-ce, docker-compose-v2 | docker-compose-plugin"
)


def debian_version(version: str) -> str:
    """Keep alpha/beta/RC packages ordered before their corresponding release."""
    match = re.fullmatch(r"([0-9]+\.[0-9]+\.[0-9]+)((?:a|b|rc)[0-9]+)?", version)
    if not match:
        raise ValueError("Versione del pacchetto non valida.")
    return match[1] + ("~" + match[2] if match[2] else "")


def verified_inputs(project: Path, manifest_path: Path, *, require_clean: bool = True,
                    require_archive: bool = True) -> tuple[dict, bytes, list[Path], Path]:
    """Reject untrusted paths and mismatched inputs before creating an output."""
    project = project.resolve()
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Manifest installer mancante o collegamento simbolico.")
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
        if type(manifest) is not dict or type(manifest.get("schema_version")) is not int:
            raise ValueError("Schema del manifest installer non valido.")
        assets.validate_manifest(manifest)
        assets.validate_installation_profile(manifest.get("installation_profile"))
    except (TypeError, AttributeError, KeyError) as exc:
        raise ValueError("Struttura del manifest installer non valida.") from exc
    if not re.fullmatch(r"0\.[67]\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", manifest["version"]):
        raise ValueError("Il pacchetto NIPAT Desktop richiede una versione 0.6 o 0.7.")
    if assets.checked_version(project) != manifest["version"]:
        raise ValueError("Versione dei sorgenti diversa dal manifest runtime.")
    if assets.installation_profile(project) != manifest["installation_profile"]:
        raise ValueError("Profilo dei sorgenti diverso dal manifest runtime.")
    if require_clean:
        source = bundle.git_source(project)
        if (source.get("available") is not True or source.get("dirty") is not False
                or source.get("commit") != manifest["source_commit"]):
            raise ValueError("La compilazione richiede un checkout Git pulito al commit del manifest.")
    provenance = manifest.get("rootfs_provenance", {})
    if (type(provenance) is not dict or type(provenance.get("schema_version")) is not int
            or provenance.get("schema_version") != 1
            or provenance.get("vendor") != "nipat-desktop"
            or provenance.get("source_commit") != manifest["source_commit"]):
        raise ValueError("La provenienza del runtime non corrisponde al commit del manifest.")
    files = bundle.source_files(project)
    hashes = {path.relative_to(project).as_posix(): bundle.sha256_file(path) for path in files}
    if hashes != manifest.get("source_sha256"):
        raise ValueError("I sorgenti non corrispondono al manifest compilato in CI.")
    if not {LAUNCH_SOURCE, ICON_SOURCE, "LICENSE", "THIRD_PARTY_NOTICES.md"}.issubset(hashes):
        raise ValueError("Il manifest dei sorgenti deve includere il launcher Linux, l'icona e le licenze.")
    entry = manifest["assets"]["scientific_image"]
    archive = manifest_path.parent / entry["file"]
    if require_archive and assets.asset_metadata(archive, manifest["release_tag"]) != entry:
        raise ValueError("Archivio scientifico diverso dal manifest.")
    return manifest, manifest_bytes, files, archive


def write_file(path: Path, contents: str | bytes, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contents, str):
        contents = contents.encode("utf-8")
    path.write_bytes(contents)
    path.chmod(0o755 if executable else 0o644)


def generated_files(manifest: dict, manifest_bytes: bytes) -> dict[str, tuple[bytes, int]]:
    """Return the small generated payloads, including their required file modes."""
    release = {
        "schema_version": 1,
        "package_version": manifest["version"],
        "status": "for-domain-validation",
        "built_at_utc": manifest.get("built_at_utc"),
        "source_git": {"commit": manifest["source_commit"], "dirty": False, "available": True},
        "source_sha256": manifest["source_sha256"],
        "installer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "python": {"version": "3.12", "provider": "ubuntu-system", "architecture": "amd64"},
        "runtime": {"image_id": manifest["runtime_image"]},
        "distribution": "native-linux-deb",
    }
    launcher = ("#!/bin/sh\n"
                "exec 9</var/lib/nipat-desktop/activity.lock || { echo 'NIPAT: reinstallare il pacchetto.' >&2; exit 1; }\n"
                "/usr/bin/flock --shared --nonblock 9 || { echo 'NIPAT: aggiornamento in corso.' >&2; exit 1; }\n"
                "test ! -e /var/lib/nipat-desktop/update-in-progress || { echo 'NIPAT: aggiornamento incompleto; completare la configurazione del pacchetto.' >&2; exit 1; }\n"
                "exec /usr/bin/python3.12 -I "
                f"/{APP_PATH.as_posix()}/{LAUNCH_SOURCE} \"$@\"\n")
    desktop = (
        "[Desktop Entry]\nType=Application\nName=NIPAT Desktop\n"
        "Comment=Scientific analysis with the NIPAT guided command line\n"
        f"Exec=/usr/bin/{COMMAND} --desktop\nTryExec=/usr/bin/{COMMAND}\n"
        f"Terminal=true\nIcon=/{APP_PATH.as_posix()}/{ICON_SOURCE}\nCategories=Science;Biology;\n"
    )
    return {
        f"{APP_PATH.as_posix()}/.distribution/{assets.MANIFEST_NAME}": (manifest_bytes, 0o644),
        f"{APP_PATH.as_posix()}/release.json": ((json.dumps(release, indent=2) + "\n").encode(), 0o644),
        f"usr/bin/{COMMAND}": (launcher.encode(), 0o755),
        f"usr/share/applications/{PACKAGE}.desktop": (desktop.encode(), 0o644),
        f"usr/share/doc/{PACKAGE}/copyright": ((
            "NIPAT - https://github.com/GregorioDalia/nipat-desktop\n\n"
            "Copyright remains with the respective authors and contributors.\n"
            "Original NIPAT material is licensed under the GNU General Public\n"
            "License version 3 or, at your option, any later version. Third-party\n"
            "components retain their own notices and applicable license terms.\n\n"
            f"Full NIPAT license: /{APP_PATH.as_posix()}/LICENSE\n"
            f"Component notices: /{APP_PATH.as_posix()}/THIRD_PARTY_NOTICES.md\n"
            "The scientific image preserves the notices of its dependencies.\n"
        ).encode(), 0o644),
    }


def control_bytes(manifest: dict, installed_kib: int) -> bytes:
    return (
        f"Package: {PACKAGE}\nVersion: {debian_version(manifest['version'])}\n"
        "Section: science\nPriority: optional\nArchitecture: amd64\n"
        "Maintainer: NIPAT contributors\n"
        f"Installed-Size: {installed_kib}\nPre-Depends: util-linux\nDepends: {DEPENDENCIES}\n"
        "Homepage: https://github.com/GregorioDalia/nipat-desktop\n"
        "Description: NIPAT Desktop scientific CLI for Ubuntu 24.04 LTS\n"
        " Includes the verified scientific image for local Docker Engine execution.\n"
        " Requires explicit user access to a compatible local Docker daemon.\n"
        " This package does not configure Docker permissions or modify user data.\n"
    ).encode("utf-8")


def maintainer_scripts() -> dict[str, bytes]:
    """Coordinate dpkg transactions with all installed NIPAT sessions.

    The root-owned marker bridges preinst/prerm and postinst: flock alone would
    be released before dpkg unpacks files. The inode is intentionally retained
    after removal so existing readers can never lock an obsolete replacement.
    A failed transaction remains blocked until package configuration succeeds.
    """
    common = """#!/bin/sh
set -eu
umask 022
state=/var/lib/nipat-desktop
if [ -L "$state" ]; then echo 'NIPAT: unsafe package state directory.' >&2; exit 1; fi
if [ ! -e "$state" ]; then mkdir -m 0755 "$state"; fi
if [ ! -d "$state" ] || [ "$(stat -c %u "$state")" != 0 ] || [ "$(stat -c %a "$state")" != 755 ]; then
    echo 'NIPAT: invalid package state ownership or permissions.' >&2; exit 1
fi
lock="$state/activity.lock"
marker="$state/update-in-progress"
if [ -L "$lock" ] || [ -L "$marker" ]; then echo 'NIPAT: unsafe package state file.' >&2; exit 1; fi
if [ ! -e "$lock" ]; then (set -C; : > "$lock"); fi
if [ ! -f "$lock" ] || [ "$(stat -c %u "$lock")" != 0 ] || [ "$(stat -c %a "$lock")" != 644 ]; then
    echo 'NIPAT: invalid activity lock.' >&2; exit 1
fi
if [ -e "$marker" ] && { [ ! -f "$marker" ] || [ "$(stat -c %u "$marker")" != 0 ]; }; then
    echo 'NIPAT: invalid update marker.' >&2; exit 1
fi
exec 9<"$lock"
if ! /usr/bin/flock --exclusive --nonblock 9; then
    echo 'NIPAT: close every NIPAT session and wait for analyses to finish, then retry the package operation.' >&2
    exit 1
fi
"""
    return {
        "preinst": (common + "case \"$1\" in install|upgrade) : > \"$marker\";; esac\n").encode(),
        "prerm": (common + "case \"$1\" in remove|upgrade|deconfigure) : > \"$marker\";; esac\n").encode(),
        "postinst": (common + "case \"$1\" in configure) rm -f -- \"$marker\";; esac\n").encode(),
        "postrm": (common + "case \"$1\" in remove|purge) rm -f -- \"$marker\";; esac\n").encode(),
    }


def stage_package(project: Path, stage: Path, manifest: dict, manifest_bytes: bytes,
                  sources: list[Path], archive: Path) -> None:
    app = stage / APP_PATH
    for source in sources:
        relative = source.relative_to(project)
        target = app / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o644)
        if bundle.sha256_file(target) != manifest["source_sha256"][relative.as_posix()]:
            raise ValueError(f"Sorgente cambiato durante la preparazione: {relative}")
    for name, (contents, mode) in generated_files(manifest, manifest_bytes).items():
        write_file(stage / name, contents, executable=mode == 0o755)
    target_archive = app / ".distribution" / archive.name
    shutil.copyfile(archive, target_archive)
    target_archive.chmod(0o644)
    if assets.asset_metadata(target_archive, manifest["release_tag"]) != manifest["assets"]["scientific_image"]:
        raise ValueError("Archivio scientifico cambiato durante la preparazione.")
    installed_kib = (sum(path.stat().st_size for path in stage.rglob("*") if path.is_file()) + 1023) // 1024
    write_file(stage / "DEBIAN/control", control_bytes(manifest, installed_kib))
    for name, contents in maintainer_scripts().items():
        write_file(stage / "DEBIAN" / name, contents, executable=True)
    # A restrictive builder umask must not produce unreadable installation paths.
    stage.chmod(0o755)
    for path in stage.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)


def verify_tar(package: Path, option: str, expected: dict[str, tuple[str, int, int]]) -> None:
    """Inspect dpkg's tar stream without extracting package-controlled paths."""
    directories = {"."}
    for name in expected:
        directories.update(str(parent) for parent in Path(name).parents)
    found = set()
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(["dpkg-deb", option, str(package)], stdout=subprocess.PIPE,
                                   stderr=errors)
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for entry in archive:
                    name = entry.name[2:] if entry.name.startswith("./") else entry.name
                    if name in found or name not in expected and name not in directories:
                        raise ValueError(f"Percorso duplicato o inatteso nel pacchetto: {name}")
                    found.add(name)
                    if entry.uid != 0 or entry.gid != 0:
                        raise ValueError(f"Proprietario non root nel pacchetto: {name}")
                    if name in directories:
                        if not entry.isdir() or entry.mode != 0o755:
                            raise ValueError(f"Directory non valida nel pacchetto: {name}")
                        continue
                    digest, size, mode = expected[name]
                    if not entry.isfile() or entry.size != size or entry.mode != mode:
                        raise ValueError(f"Tipo, dimensione o permessi non validi nel pacchetto: {name}")
                    with archive.extractfile(entry) as stream:
                        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                            raise ValueError(f"Contenuto diverso dal manifest nel pacchetto: {name}")
            process.stdout.close()
            if process.wait(timeout=1800):
                errors.seek(0)
                raise ValueError("dpkg-deb non ha verificato il pacchetto: "
                                 + errors.read().decode("utf-8", errors="replace"))
        except BaseException:
            process.kill()
            process.wait()
            process.stdout.close()
            raise
    if found != set(expected) | directories:
        raise ValueError("Il pacchetto non contiene esattamente i file e le directory previsti.")


def verify_package(package: Path, manifest_path: Path, project: Path) -> dict:
    """Bind the actual DEB payload and controls to common Windows/Linux inputs."""
    project = project.resolve()
    manifest, manifest_bytes, sources, _ = verified_inputs(
        project, manifest_path, require_clean=False, require_archive=False,
    )
    name = f"{PACKAGE}_{debian_version(manifest['version'])}_amd64.deb"
    if package.name != name or package.is_symlink() or not package.is_file():
        raise ValueError("Nome o tipo del pacchetto Linux non valido.")
    if not 0 < package.stat().st_size < assets.MAX_ASSET_BYTES:
        raise ValueError("Il pacchetto deve essere minore di 2 GiB.")
    expected = {
        f"{APP_PATH.as_posix()}/{source.relative_to(project).as_posix()}": (
            manifest["source_sha256"][source.relative_to(project).as_posix()],
            source.stat().st_size, 0o644,
        ) for source in sources
    }
    for path, (contents, mode) in generated_files(manifest, manifest_bytes).items():
        if path in expected:
            raise ValueError("Un sorgente approvato collide con un file generato.")
        expected[path] = (hashlib.sha256(contents).hexdigest(), len(contents), mode)
    scientific = manifest["assets"]["scientific_image"]
    expected[f"{APP_PATH.as_posix()}/.distribution/{scientific['file']}"] = (
        scientific["sha256"], scientific["size"], 0o644,
    )
    verify_tar(package, "--fsys-tarfile", expected)
    installed_kib = (sum(size for _, size, _ in expected.values()) + 1023) // 1024
    control = control_bytes(manifest, installed_kib)
    expected_controls = {
        "control": (hashlib.sha256(control).hexdigest(), len(control), 0o644),
    }
    expected_controls.update({
        name: (hashlib.sha256(contents).hexdigest(), len(contents), 0o755)
        for name, contents in maintainer_scripts().items()
    })
    verify_tar(package, "--ctrl-tarfile", expected_controls)
    return {
        "schema_version": 1,
        "distribution": "native-linux-deb",
        "package": PACKAGE,
        "version": manifest["version"],
        "debian_version": debian_version(manifest["version"]),
        "architecture": "amd64",
        "source_commit": manifest["source_commit"],
        "file": name,
        "sha256": bundle.sha256_file(package),
        "size": package.stat().st_size,
        "installer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "embedded_scientific_asset": {
            key: scientific[key] for key in ("file", "sha256", "size")
        },
    }


def build_installer(project: Path, manifest_path: Path, output: Path) -> Path:
    project = project.resolve()
    if output.exists() or output.is_symlink():
        raise ValueError("La cartella di output deve essere nuova.")
    manifest, manifest_bytes, sources, archive = verified_inputs(project, manifest_path)
    compiler = shutil.which("dpkg-deb")
    if compiler is None:
        raise ValueError("La compilazione del pacchetto richiede dpkg-deb su Linux.")
    name = f"{PACKAGE}_{debian_version(manifest['version'])}_amd64.deb"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nipat-linux-package-", dir=output.parent) as temporary:
        temporary = Path(temporary)
        stage = temporary / "root"
        stage.mkdir()
        stage_package(project, stage, manifest, manifest_bytes, sources, archive)
        package = temporary / name
        subprocess.run([compiler, "--root-owner-group", "-Znone", "--build", str(stage), str(package)],
                       check=True, timeout=1800)
        record = verify_package(package, manifest_path, project)
        output.mkdir(exist_ok=False)
        shutil.move(package, output / name)
        write_file(output / assets.MANIFEST_NAME, manifest_bytes)
        write_file(output / BUILD_RECORD, json.dumps(record, indent=2) + "\n")
        write_file(output / "SHA256SUMS", f"{record['sha256']}  {name}\n")
    return output / name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        path = build_installer(args.project, args.manifest, args.output_dir)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"Compilazione installer Linux fallita: {exc}\n")
    print(f"Installer Linux verificato: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
