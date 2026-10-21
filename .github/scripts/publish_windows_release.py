"""Publish one already-successful installer build, without rebuilding its assets."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urljoin

REPO = "GregorioDalia/nipat-desktop"
MANIFEST = "installer-manifest.json"


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


def prepare_assets(setup, runtime, output, commit, read_source=source_bytes):
    manifest_bytes = (setup / MANIFEST).read_bytes()
    require(manifest_bytes == (runtime / MANIFEST).read_bytes(), "Installer/runtime manifests differ")
    manifest = json.loads(manifest_bytes)
    version = manifest["version"]
    require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:a|b|rc)[0-9]+", version),
            "Only explicitly versioned pre-releases are supported")
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
        require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size < 2 * 1024**3,
                f"Invalid runtime asset: {name}")
        require(path.stat().st_size == asset["size"] and sha256(path) == asset["sha256"],
                f"Runtime asset hash/size mismatch: {name}")
        files[name] = path
    for path in files.values():
        require(path.is_file() and not path.is_symlink() and path.stat().st_size > 0,
                f"Missing or invalid file: {path.name}")
    digests = {name: sha256(path) for name, path in files.items()}
    require(checksums(setup / "SHA256SUMS") == {"NIPAT-Setup.exe": digests["NIPAT-Setup.exe"]},
            "Installer checksum mismatch")
    require(checksums(runtime / "SHA256SUMS") == {n: h for n, h in digests.items() if n != "NIPAT-Setup.exe"},
            "Runtime/manifest checksum mismatch")
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
        "name": f"NIPAT CLI {version} — Windows con WSL2", "body": notes,
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
        output = root / "release"
        manifest = prepare_assets(root / "artifacts/nipat-windows-setup", root / "artifacts/nipat-runtime-assets",
                                  output, commit)
        tag = manifest["release_tag"]
        notes = source_bytes(commit, f"docs/RELEASE_{manifest['version']}.md").decode("utf-8").strip()
        notes = re.sub(r"\]\(([^)\s]+)\)", lambda m: "](" + urljoin(
            f"https://github.com/{REPO}/blob/{tag}/docs/", m[1]) + ")", notes)
        notes += (f"\n\n## Build distribuita\n\nCommit: `{commit}`.\n\n"
                  f"[Build verificata]({run['html_url']}): test Linux e Windows, regressioni scientifiche, "
                  "caricamento/esecuzione/ricaricamento nel motore distribuito e compilazione EXE superati.\n")
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
                stream.write("All five release assets were checked against their SHA-256 digests before publication.\n")


if __name__ == "__main__":
    main()
