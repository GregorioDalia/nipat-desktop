"""Publish one already-successful installer build, without rebuilding its assets."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
from urllib.parse import urljoin
import zipfile

REPO = "GregorioDalia/nipat-desktop"
MANIFEST = "installer-manifest.json"
MAX_ASSET_BYTES = 2 * 1024**3
PYTHON_NAME = "python-3.12.10-embed-amd64.zip"
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
DOCKER_INSTALLER_MARKER = b'{"schema_version":1,"distribution":"docker-desktop-installer"}\n'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def api(path):
    return json.loads(command("gh", "api", f"repos/{REPO}/{path}"))


def source_bytes(commit, path):
    return subprocess.check_output(["git", "show", f"{commit}:{path}"])


def validate_run(run, commit, run_id):
    require(run.get("id") == run_id, "Unexpected build run ID")
    require(run.get("head_sha") == commit, "Build commit differs from requested commit")
    require((run.get("status"), run.get("conclusion")) == ("completed", "success"),
            "Build has not completed successfully")
    require(run.get("event") in ("push", "workflow_dispatch"), "PR builds cannot be published")
    require(run.get("path") == ".github/workflows/windows-installer.yml", "Unexpected build workflow")
    require(run.get("repository", {}).get("full_name") == REPO
            and run.get("head_repository", {}).get("full_name") == REPO,
            "Build must originate in this repository")


def checksums(path):
    result = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        require(match is not None, f"Invalid checksum line in {path.name}")
        digest, name = match.groups()
        require(name not in result, "Duplicate checksum entry")
        result[name] = digest
    return result


def requires_desktop_bundle(version):
    # The first published WSL candidate predates the dual distribution protocol.
    return version != "0.3.0a1"


def requires_desktop_installer(version):
    components = re.match(r"([0-9]+)\.([0-9]+)\.([0-9]+)", version)
    return components is not None and tuple(map(int, components.groups())) >= (0, 4, 1)


def verify_installer_build(setup, manifest, manifest_bytes, commit):
    """Bind the self-contained EXE to the inputs checked by the successful build."""
    require(not any(path.suffix.casefold() == ".bin" for path in setup.rglob("*")),
            "Self-contained installer cannot have companion data slices")
    evidence_path = setup / "installer-build.json"
    require(evidence_path.is_file() and not evidence_path.is_symlink(),
            "Missing self-contained installer build evidence")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    installer = setup / "NIPAT-Setup.exe"
    launcher = setup / "NIPAT.exe"
    require(launcher.is_file() and not launcher.is_symlink() and launcher.stat().st_size > 0,
            "Missing WSL build launcher evidence")
    expected = {
        "schema_version": 1, "distribution": "self-contained-wsl",
        "version": manifest["version"], "source_commit": commit,
        "file": "NIPAT-Setup.exe", "sha256": sha256(installer), "size": installer.stat().st_size,
        "installer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "launcher_sha256": sha256(launcher),
        "embedded_assets": {
            key: {field: manifest["assets"][key][field] for field in ("file", "sha256", "size")}
            for key in ("rootfs", "scientific_image")
        },
    }
    require(evidence == expected, "Self-contained installer build evidence mismatch")


def verify_desktop_bundle(desktop, setup, manifest, manifest_bytes, commit):
    """Verify the portable ZIP without extracting or executing its contents."""
    require(desktop is not None, "Docker Desktop package is required for this release")
    version = manifest["version"]
    name = f"NIPAT-DockerDesktop-{version}-windows-x64.zip"
    path = desktop / name
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size < MAX_ASSET_BYTES,
            "Missing or invalid Docker Desktop package")
    evidence_path = desktop / "package-build.json"
    require(evidence_path.is_file() and not evidence_path.is_symlink(), "Missing Docker package build evidence")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    launcher = setup / "NIPAT.exe"
    require(launcher.is_file() and not launcher.is_symlink() and launcher.stat().st_size > 0,
            "Missing WSL build launcher evidence")
    launcher_hash = sha256(launcher)
    expected_evidence = {
        "schema_version": 1, "version": version, "source_commit": commit,
        "file": name, "sha256": sha256(path), "size": path.stat().st_size,
        "launcher_sha256": launcher_hash,
    }
    require(evidence == expected_evidence, "Docker package build hash/source/version mismatch")
    scientific = manifest["assets"]["scientific_image"]
    expected_runtime = {
        "schema_version": 1, "image_id": manifest["runtime_image"],
        "source_reference": manifest["release_tag"], "os": "linux", "architecture": "amd64",
        "archive_sha256": scientific["sha256"], "archive_bytes": scientific["size"],
        "source_commit": commit, "installer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    expected_launcher = {"file": "NIPAT.exe", "sha256": launcher_hash, "size": launcher.stat().st_size}
    expected_python = {"version": "3.12.10", "architecture": "amd64", "archive_sha256": PYTHON_SHA256}
    prefix = "nipat-desktop/"
    expected_names = {prefix + source for source in manifest["source_sha256"]}
    expected_names |= {prefix + item for item in (
        "release.json", "NIPAT.exe", f".distribution/{PYTHON_NAME}",
        ".distribution/runtime.tar", ".distribution/runtime.json",
    )}
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        require(len(names) == len(set(name.casefold() for name in names))
                and set(names) == expected_names, "Docker ZIP contains missing, duplicate or unexpected files")
        require(all(not entry.is_dir() and not stat.S_ISLNK(entry.external_attr >> 16)
                    and not entry.flag_bits & 1 for entry in entries), "Docker ZIP contains unsupported entries")
        release_bytes = archive.read(prefix + "release.json")
        runtime_bytes = archive.read(prefix + ".distribution/runtime.json")
        release = json.loads(release_bytes)
        require(release.get("schema_version") == 1 and release.get("package_version") == version
                and release.get("source_git") == {"commit": commit, "dirty": False, "available": True}
                and release.get("source_sha256") == manifest["source_sha256"],
                "Docker package source/version mismatch")
        require(release.get("runtime") == expected_runtime
                and json.loads(runtime_bytes) == expected_runtime,
                "Docker package runtime differs from WSL runtime")
        require(release.get("launcher") == expected_launcher, "Docker launcher metadata mismatch")
        require(release.get("python") == expected_python, "Docker Python metadata mismatch")
        hashes = dict(manifest["source_sha256"])
        hashes.update({"NIPAT.exe": launcher_hash, f".distribution/{PYTHON_NAME}": PYTHON_SHA256,
                       ".distribution/runtime.tar": scientific["sha256"]})
        require(archive.getinfo(prefix + ".distribution/runtime.tar").file_size == scientific["size"],
                "Docker runtime archive size differs from WSL runtime")
        require(archive.getinfo(prefix + "NIPAT.exe").file_size == launcher.stat().st_size,
                "Docker launcher size differs from WSL launcher")
        for item, expected in hashes.items():
            with archive.open(prefix + item) as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            require(digest == expected, f"Docker ZIP content hash mismatch: {item}")
    staged_hashes = dict(hashes)
    staged_hashes.update({
        "release.json": hashlib.sha256(release_bytes).hexdigest(),
        ".distribution/runtime.json": hashlib.sha256(runtime_bytes).hexdigest(),
        ".distribution/docker-desktop.json": hashlib.sha256(DOCKER_INSTALLER_MARKER).hexdigest(),
    })
    return path, staged_hashes


def verify_desktop_installer(desktop, setup, package, staged_hashes, manifest, manifest_bytes, commit):
    """Bind the Docker EXE to the verified package and compiler-checked stage."""
    require(not any(path.suffix.casefold() == ".bin" for path in desktop.rglob("*")),
            "Docker installer cannot have companion data slices")
    installer = desktop / "NIPAT-DockerDesktop-Setup.exe"
    require(installer.is_file() and not installer.is_symlink()
            and 0 < installer.stat().st_size < MAX_ASSET_BYTES,
            "Missing, invalid or >= 2 GiB Docker installer")
    evidence_path = desktop / "docker-installer-build.json"
    require(evidence_path.is_file() and not evidence_path.is_symlink(),
            "Missing Docker installer build evidence")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    scientific = manifest["assets"]["scientific_image"]
    expected = {
        "schema_version": 1, "distribution": "self-contained-docker-desktop",
        "version": manifest["version"], "source_commit": commit,
        "file": installer.name, "sha256": sha256(installer), "size": installer.stat().st_size,
        "package_file": package.name, "package_sha256": sha256(package), "package_bytes": package.stat().st_size,
        "installer_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "launcher_sha256": sha256(setup / "NIPAT.exe"),
        "runtime_archive_sha256": scientific["sha256"], "runtime_archive_bytes": scientific["size"],
        "staged_files_sha256": staged_hashes,
    }
    require(evidence == expected, "Docker installer build evidence mismatch")
    return installer


def prepare_assets(setup, runtime, output, commit, read_source=source_bytes, desktop=None):
    manifest_bytes = (setup / MANIFEST).read_bytes()
    require(manifest_bytes == (runtime / MANIFEST).read_bytes(), "Installer/runtime manifests differ")
    manifest = json.loads(manifest_bytes)
    version = manifest["version"]
    require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version),
            "Version must be numeric major.minor.patch with an optional a/b/rc suffix")
    tag = f"v{version}"
    require(manifest["schema_version"] == 1 and manifest["release_tag"] == tag
            and manifest["source_commit"] == commit, "Manifest release/source mismatch")
    require(manifest["rootfs_provenance"]["source_commit"] == commit, "Rootfs source mismatch")
    approved = [line.strip() for line in read_source(commit, "distribution-files.txt").decode().splitlines()
                if line.strip() and not line.strip().startswith("#")]
    require(len(approved) == len(set(approved)) and set(approved) == set(manifest["source_sha256"]),
            "Manifest source list differs from the built commit")
    for name in approved:
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts, "Invalid source path")
        require(hashlib.sha256(read_source(commit, name)).hexdigest() == manifest["source_sha256"][name],
                f"Source hash mismatch: {name}")
    require(set(manifest["assets"]) == {"rootfs", "scientific_image"}, "Unexpected runtime asset set")
    files = {"NIPAT-Setup.exe": setup / "NIPAT-Setup.exe", MANIFEST: setup / MANIFEST}
    for key, stem in (("rootfs", "nipat-wsl-rootfs"), ("scientific_image", "nipat-scientific-runtime")):
        asset = manifest["assets"][key]
        name = f"{stem}-{version}-amd64.tar.gz"
        require(asset["file"] == name and asset["url"] ==
                f"https://github.com/{REPO}/releases/download/{tag}/{name}", "Asset name/URL mismatch")
        path = runtime / name
        require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size < MAX_ASSET_BYTES,
                f"Invalid runtime asset: {name}")
        require(path.stat().st_size == asset["size"] and sha256(path) == asset["sha256"],
                f"Runtime asset hash/size mismatch: {name}")
        files[name] = path
    for path in files.values():
        require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size < MAX_ASSET_BYTES,
                f"Missing, invalid or >= 2 GiB file: {path.name}")
    digests = {name: sha256(path) for name, path in files.items()}
    require(checksums(setup / "SHA256SUMS") == {"NIPAT-Setup.exe": digests["NIPAT-Setup.exe"]},
            "Installer checksum mismatch")
    require(checksums(runtime / "SHA256SUMS") == {n: h for n, h in digests.items() if n != "NIPAT-Setup.exe"},
            "Runtime/manifest checksum mismatch")
    if requires_desktop_bundle(version):
        verify_installer_build(setup, manifest, manifest_bytes, commit)
    if requires_desktop_bundle(version) or desktop is not None:
        portable, staged_hashes = verify_desktop_bundle(desktop, setup, manifest, manifest_bytes, commit)
        delivery = (verify_desktop_installer(desktop, setup, portable, staged_hashes, manifest, manifest_bytes, commit)
                    if requires_desktop_installer(version) else portable)
        files[delivery.name] = delivery
        digests[delivery.name] = sha256(delivery)
    output.mkdir()
    for name, path in files.items():
        shutil.copyfile(path, output / name)
    (output / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for n, h in sorted(digests.items())), encoding="ascii")
    return manifest


def verify_uploaded(release, files, commit, tag, notes, complete=False):
    require(release["draft"] and release["prerelease"], "Existing release is not a draft pre-release")
    require(release["target_commitish"] == commit and release["tag_name"] == tag
            and release["body"].strip() == notes.strip(), "Existing draft belongs to different source or notes")
    assets = release["assets"]
    names = [asset["name"] for asset in assets]
    require(len(names) == len(set(names)) and set(names) <= set(files), "Unexpected/duplicate release assets")
    for asset in assets:
        path = files[asset["name"]]
        require(asset["state"] == "uploaded" and asset["size"] == path.stat().st_size
                and asset.get("digest") == f"sha256:{sha256(path)}", "Uploaded asset integrity mismatch")
    if complete:
        require(set(names) == set(files), "Release is incomplete")
    return set(names)


def check_tag(tag, commit, required=False):
    refs = api(f"git/matching-refs/tags/{tag}")
    exact = [ref for ref in refs if ref["ref"] == f"refs/tags/{tag}"]
    if not exact:
        require(not required, "Published tag not found")
        return
    obj = exact[0]["object"]
    for _ in range(10):
        if obj["type"] != "tag":
            break
        obj = api(f"git/tags/{obj['sha']}")["object"]
    require(obj["type"] == "commit" and obj["sha"] == commit, "Existing tag targets a different commit")


def find_release(tag):
    pages = json.loads(command("gh", "api", f"repos/{REPO}/releases?per_page=100", "--paginate", "--slurp"))
    return next((release for page in pages for release in page if release["tag_name"] == tag), None)


def create_draft(tag, version, commit, notes, payload_path):
    payload_path.write_text(json.dumps({
        "tag_name": tag, "target_commitish": commit,
        "name": f"NIPAT CLI {version} — Windows con " +
                ("WSL2 e Docker Desktop" if requires_desktop_bundle(version) else "WSL2"), "body": notes,
        "draft": True, "prerelease": True, "make_latest": "false",
    }), encoding="utf-8")
    # The list endpoint may lag behind a successful creation. Retain the exact
    # resource returned by POST rather than rediscovering it through that list.
    return json.loads(command("gh", "api", f"repos/{REPO}/releases", "--method", "POST",
                              "--input", str(payload_path)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--draft-release-id", default="")
    args = parser.parse_args()
    require(re.fullmatch(r"[1-9][0-9]*", args.run_id), "Invalid run ID")
    require(re.fullmatch(r"[0-9a-f]{40}", args.source_commit), "Full source SHA is required")
    require(not args.draft_release_id or re.fullmatch(r"[1-9][0-9]*", args.draft_release_id), "Invalid draft ID")
    commit = args.source_commit
    subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], check=True)
    run = api(f"actions/runs/{args.run_id}")
    validate_run(run, commit, int(args.run_id))
    jobs = api(f"actions/runs/{args.run_id}/jobs?per_page=100")["jobs"]
    for name in ("linux-runtime", "windows-installer"):
        matches = [job for job in jobs if job["name"] == name]
        require(len(matches) == 1 and matches[0]["conclusion"] == "success", f"Missing successful job: {name}")
    with tempfile.TemporaryDirectory(prefix="nipat-release-") as temporary:
        root = Path(temporary)
        command("gh", "run", "download", args.run_id, "--repo", REPO,
                "--name", "nipat-windows-setup", "--name", "nipat-runtime-assets", "--dir", str(root / "artifacts"))
        build_manifest = json.loads((root / "artifacts/nipat-runtime-assets" / MANIFEST).read_text(encoding="utf-8"))
        desktop = None
        if requires_desktop_bundle(build_manifest["version"]):
            desktop = root / "artifacts/nipat-docker-desktop"
            command("gh", "run", "download", args.run_id, "--repo", REPO,
                    "--name", "nipat-docker-desktop", "--dir", str(desktop))
        output = root / "release"
        manifest = prepare_assets(root / "artifacts/nipat-windows-setup", root / "artifacts/nipat-runtime-assets",
                                  output, commit, desktop=desktop)
        tag = manifest["release_tag"]
        notes = source_bytes(commit, f"docs/RELEASE_{manifest['version']}.md").decode("utf-8").strip()
        notes = re.sub(r"\]\(([^)\s]+)\)", lambda m: "](" + urljoin(
            f"https://github.com/{REPO}/blob/{tag}/docs/", m[1]) + ")", notes)
        notes += (f"\n\n## Build distribuita\n\nCommit: `{commit}`.\n\n"
                  f"[Build verificata]({run['html_url']}): test Linux e Windows, regressioni scientifiche, "
                  "caricamento/esecuzione/ricaricamento nel motore distribuito e compilazione EXE superati.\n")
        if requires_desktop_bundle(manifest["version"]):
            notes += ("\nPer l'installazione WSL scaricare soltanto **NIPAT-Setup.exe**: include "
                      "i componenti NIPAT e i due archivi runtime. Dopo l'installazione, avviare NIPAT "
                      "dal collegamento creato. Non occorre scaricare o disporre manualmente gli archivi "
                      "in una cartella assets. Windows puo' richiedere Internet o un riavvio per WSL.\n\n")
            if requires_desktop_installer(manifest["version"]):
                notes += ("Per Docker Desktop scaricare soltanto **NIPAT-DockerDesktop-Setup.exe**, "
                          "con Docker Desktop gia' installato e avviato in modalita' Linux. Dopo il setup "
                          "aprire il collegamento **NIPAT (Docker Desktop)**. Il pacchetto include Python, "
                          "l'applicazione e il runtime scientifico; non richiede di estrarre ZIP. ")
            else:
                notes += "Lo ZIP Docker Desktop e' una distribuzione alternativa per chi dispone gia' di Docker Desktop. "
            notes += "Gli archivi runtime separati sono conservati come asset di recupero e verifica.\n"
        notes = notes.strip()
        files = {path.name: path for path in output.iterdir()}
        check_tag(tag, commit)
        release = api(f"releases/{args.draft_release_id}") if args.draft_release_id else find_release(tag)
        if release is None:
            release = create_draft(tag, manifest["version"], commit, notes, root / "create-release.json")
        require(release is not None, "Draft release not found")
        present = verify_uploaded(release, files, commit, tag, notes)
        missing = [str(files[name]) for name in sorted(set(files) - present)]
        if missing:
            command("gh", "release", "upload", tag, *missing, "--repo", REPO)
        release = api(f"releases/{release['id']}")
        verify_uploaded(release, files, commit, tag, notes, complete=True)
        check_tag(tag, commit)
        command("gh", "release", "edit", tag, "--repo", REPO, "--draft=false", "--prerelease", "--latest=false")
        published = api(f"releases/{release['id']}")
        require(not published["draft"] and published["prerelease"], "Publication was not confirmed")
        check_tag(tag, commit, required=True)
        print(published["html_url"])
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write(f"Published [{tag}]({published['html_url']}) from `{commit}`.\n\n")
                stream.write(f"All {len(files)} release assets were checked against their SHA-256 digests before publication.\n")


if __name__ == "__main__":
    main()
