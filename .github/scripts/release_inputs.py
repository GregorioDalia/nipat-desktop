"""Fetch immutable-by-digest build/scan inputs from the official public release."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

REPOSITORY = "GregorioDalia/nipat-desktop"
MAX_BYTES = 2 * 1024**3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def allowed_url(url):
    parsed = urllib.parse.urlsplit(url)
    return (parsed.scheme == "https" and not parsed.username and not parsed.password
            and parsed.port in (None, 443) and parsed.hostname in {
                "api.github.com", "github.com", "release-assets.githubusercontent.com",
                "objects.githubusercontent.com", "github-releases.githubusercontent.com",
                "github-production-release-asset-2e65be.s3.amazonaws.com",
            })


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        require(allowed_url(newurl), "Release download redirected to an unapproved host")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_json(url):
    require(allowed_url(url), "Invalid release metadata URL")
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                 "User-Agent": "nipat-ci-evidence"})
    with urllib.request.build_opener(RestrictedRedirect()).open(request, timeout=60) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    require(len(data) <= 4 * 1024 * 1024, "Release metadata is too large")
    return json.loads(data)


def checked_download(url, destination, expected_hash, expected_size, *, maximum=MAX_BYTES):
    require(allowed_url(url) and re.fullmatch(r"[0-9a-f]{64}", expected_hash) is not None,
            "Invalid download identity")
    require(type(expected_size) is int and 0 < expected_size <= maximum, "Invalid download size")
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(not destination.is_symlink(), "Download destination is a symlink")
    temporary = destination.with_name(destination.name + ".partial")
    require(not temporary.exists() and not temporary.is_symlink(), "Partial destination already exists")
    try:
        digest = hashlib.sha256()
        total = 0
        with urllib.request.build_opener(RestrictedRedirect()).open(url, timeout=120) as response:
            with temporary.open("xb") as handle:
                while block := response.read(1024 * 1024):
                    total += len(block)
                    require(total <= expected_size, "Download exceeds declared size")
                    digest.update(block)
                    handle.write(block)
        require(total == expected_size and digest.hexdigest() == expected_hash, "Release asset checksum mismatch")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def release_inputs(tag, kinds, output):
    require(tag == "latest" or re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", tag),
            "Invalid release tag")
    suffix = "latest" if tag == "latest" else "tags/" + tag
    release = fetch_json(f"https://api.github.com/repos/{REPOSITORY}/releases/{suffix}")
    require(not release.get("draft") and isinstance(release.get("assets"), list), "Published release required")
    resolved_tag = release["tag_name"]
    require(isinstance(resolved_tag, str) and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", resolved_tag),
            "Invalid published release tag")
    require(tag == "latest" or tag == resolved_tag, "Release tag mismatch")
    assets = {entry["name"]: entry for entry in release["assets"]}
    require(len(assets) == len(release["assets"]), "Ambiguous release assets")

    def download(name, expected=None):
        require(name in assets and Path(name).name == name and "\\" not in name, "Missing or invalid release asset")
        record = assets[name]
        api_digest = record.get("digest", "")
        require(isinstance(api_digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", api_digest),
                "GitHub did not provide the exact asset digest")
        url = f"https://github.com/{REPOSITORY}/releases/download/{resolved_tag}/{name}"
        require(record["browser_download_url"] == url, "Release asset URL mismatch")
        if expected is not None:
            require(expected["sha256"] == api_digest[7:] and expected["size"] == record["size"],
                    "Manifest and GitHub asset identities differ")
        return checked_download(url, output / name, api_digest[7:], record["size"])

    manifest_path = download("installer-manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest["version"] == resolved_tag.removeprefix("v")
            and manifest.get("release_tag") == resolved_tag
            and re.fullmatch(r"[0-9a-f]{40}", manifest["source_commit"]), "Release source identity mismatch")
    downloaded = {}
    for kind in kinds:
        if kind == "deb":
            names = [name for name in assets if name.startswith("nipat-desktop_") and name.endswith("_amd64.deb")]
            require(len(names) == 1, "Expected one released Ubuntu package")
            downloaded[kind] = download(names[0])
        else:
            require(kind in {"rootfs", "scientific_image"}, "Unknown release input kind")
            record = manifest["assets"][kind]
            downloaded[kind] = download(record["file"], record)
    (output / "release-inputs.json").write_text(json.dumps({
        "schema_version": 1, "repository": REPOSITORY, "tag": resolved_tag,
        "release_id": release["id"], "source_commit": manifest["source_commit"],
        "files": {kind: {"file": path.name, "sha256": assets[path.name]["digest"][7:],
                         "size": assets[path.name]["size"]} for kind, path in downloaded.items()},
    }, indent=2) + "\n", encoding="utf-8")
    return downloaded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="latest")
    parser.add_argument("--kind", action="append", choices=("rootfs", "scientific_image", "deb"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    for name, path in release_inputs(args.tag, args.kind, args.output_dir).items():
        print(f"Verified {name}: {path.name}")


if __name__ == "__main__":
    main()
