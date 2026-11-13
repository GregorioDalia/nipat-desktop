"""Preserve a bounded, synthetic-only qualification bundle for a reviewed release."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

ARCHIVE = "qualification-evidence.zip"
DESCRIPTOR = "qualification-evidence.json"
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
# The five-module qualification retains over 3,500 textual evidence files.
# Leave bounded room for platform reports without raising byte/file limits.
MAX_ENTRIES = 5000
ALLOWED = {".json", ".jsonl", ".log", ".txt", ".tsv", ".csv", ".md"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(installer_set):
    result = {
        "schema_version": 1, "version": installer_set["version"],
        "source_commit": installer_set["source_commit"],
        "installer_manifest_sha256": installer_set["installer_manifest_sha256"],
        "windows_installer_sha256": installer_set["windows"]["sha256"],
        "linux_installer_sha256": installer_set["linux"]["sha256"],
        "synthetic_only": True,
    }
    if tuple(int(n) for n in installer_set["version"].split(".")[:2]) >= (0, 8):
        for architecture in ("arm64", "x86_64"):
            result[f"macos_{architecture}_installer_sha256"] = installer_set[f"macos_{architecture}"]["sha256"]
    return result


def safe_name(name):
    path = PurePosixPath(name)
    return (isinstance(name, str) and bool(name) and not path.is_absolute()
            and ".." not in path.parts and "\\" not in name and ":" not in name
            and not any(ord(char) < 32 for char in name)
            and path.as_posix() == name)


def sanitize(data, replacements):
    text = data.decode("utf-8-sig")
    for old, new in sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True):
        if old:
            text = text.replace(old, new).replace(old.replace("/", "\\"), new)
    # Runtime workspaces contain only synthetic inputs, but host account names
    # and ephemeral runner directories have no scientific value in public logs.
    text = re.sub(r"/home/runner/work/[^\s\"'<>]+", "${CI_WORKSPACE}", text)
    text = re.sub(r"C:\\\\Users\\\\runneradmin", "${CI_USER}", text, flags=re.I)
    return text.encode("utf-8")


def evidence_entries(sources, replacements=None):
    """Read and bound CI-created synthetic evidence, without asserting release identity."""
    seen = set()
    total = 0
    for label, root in sources.items():
        require(re.fullmatch(r"[a-z0-9-]+", label) is not None, "Invalid evidence source label")
        require(root.is_dir() and not root.is_symlink(), f"Missing synthetic evidence directory: {label}")
        for path in sorted(root.rglob("*")):
            require(not path.is_symlink(), "Symlinks are not qualification evidence")
            if not path.is_file() or path.suffix.lower() not in ALLOWED:
                continue
            # Installed/package directories can contain large archives;
            # only explicitly allowed textual evidence is collected.
            require(path.stat().st_size <= MAX_FILE, f"Qualification text exceeds its bound: {path.name}")
            data = sanitize(path.read_bytes(), replacements or {})
            require(len(data) <= MAX_FILE, f"Qualification text exceeds its bound: {path.name}")
            name = label + "/" + path.relative_to(root).as_posix()
            require(safe_name(name), "Unsafe evidence path")
            require(name.casefold() not in seen, "Invalid or duplicate qualification entry")
            total += len(data)
            require(total <= MAX_TOTAL,
                    f"Qualification expanded bytes {total} exceed limit {MAX_TOTAL} at {name}")
            require(len(seen) < MAX_ENTRIES,
                    f"Qualification entry count {len(seen) + 1} exceeds limit {MAX_ENTRIES} at {name}")
            seen.add(name.casefold())
            yield name, data
    require(seen, "No qualification evidence was collected")


def preflight(sources, replacements=None):
    """Check available evidence before packaging; final installer binding is still required."""
    count = total = 0
    for _, data in evidence_entries(sources, replacements):
        count += 1
        total += len(data)
    return {"entries": count, "expanded_bytes": total}


def build(output, installer_set, sources, replacements=None):
    """Sources must be CI-created synthetic-check/report directories, never user runs."""
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ARCHIVE
    require(not archive.exists() and not (output / DESCRIPTOR).exists(), "Qualification evidence already exists")
    entries = []
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for name, data in evidence_entries(sources, replacements):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                handle.writestr(info, data)
                entries.append({"path": name, "size": len(data), "sha256": digest(data)})
        descriptor = {**identity(installer_set), "archive": {
            "file": ARCHIVE, "size": archive.stat().st_size, "sha256": digest(archive.read_bytes()),
        }, "entries": entries}
        (output / DESCRIPTOR).write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")
        verify(output, installer_set)
        return descriptor
    except BaseException:
        archive.unlink(missing_ok=True)
        (output / DESCRIPTOR).unlink(missing_ok=True)
        raise


def verify(directory, installer_set):
    descriptor_path = directory / DESCRIPTOR
    archive = directory / ARCHIVE
    require(descriptor_path.is_file() and not descriptor_path.is_symlink()
            and descriptor_path.stat().st_size <= 2 * 1024 * 1024, "Missing or oversized qualification descriptor")
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    expected = identity(installer_set)
    require(isinstance(descriptor, dict) and set(descriptor) == set(expected) | {"archive", "entries"}
            and all(type(descriptor.get(key)) is type(value) and descriptor.get(key) == value
                    for key, value in expected.items()), "Qualification identity mismatch")
    record = descriptor["archive"]
    require(isinstance(record, dict) and set(record) == {"file", "size", "sha256"}
            and record["file"] == ARCHIVE and type(record["size"]) is int
            and 0 < record["size"] <= MAX_TOTAL and isinstance(record["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", record["sha256"]), "Invalid qualification archive record")
    require(archive.is_file() and not archive.is_symlink()
            and archive.stat().st_size == record["size"]
            and digest(archive.read_bytes()) == record["sha256"], "Qualification archive bytes mismatch")
    entries = descriptor["entries"]
    require(isinstance(entries, list) and 0 < len(entries) <= MAX_ENTRIES, "Invalid qualification entries")
    seen = set()
    total = 0
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) == {"path", "size", "sha256"}
                and isinstance(entry["path"], str) and safe_name(entry["path"])
                and type(entry["size"]) is int and 0 <= entry["size"] <= MAX_FILE
                and isinstance(entry["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                and entry["path"].casefold() not in seen, "Invalid or duplicate qualification entry")
        seen.add(entry["path"].casefold())
        total += entry["size"]
    require(total <= MAX_TOTAL, "Qualification expanded size exceeds its bound")
    with zipfile.ZipFile(archive) as handle:
        infos = handle.infolist()
        require(len(infos) == len(entries) and {info.filename for info in infos} == {e["path"] for e in entries},
                "Qualification archive entries differ from the descriptor")
        records = {entry["path"]: entry for entry in entries}
        for info in infos:
            expected_entry = records[info.filename]
            require(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16)
                    and info.file_size == expected_entry["size"], "Invalid qualification archive member")
            require(digest(handle.read(info)) == expected_entry["sha256"], "Qualification entry bytes mismatch")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--installer-set", type=Path)
    mode.add_argument("--preflight", action="store_true",
                      help="check available evidence without creating a release bundle")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--source", action="append", nargs=2, metavar=("LABEL", "CI_DIRECTORY"), default=[])
    parser.add_argument("--redact-root", action="append", default=[])
    args = parser.parse_args()
    if (args.preflight and args.output_dir is not None) or (not args.preflight and args.output_dir is None):
        parser.error("--output-dir is required only with --installer-set")
    require(len({label for label, _ in args.source}) == len(args.source), "Duplicate evidence source label")
    sources = {label: Path(path) for label, path in args.source}
    replacements = {path: "${CI_WORKSPACE}" for path in args.redact_root}
    if args.preflight:
        result = preflight(sources, replacements)
        print(f"PASS: available synthetic evidence fits bounds: {result['entries']} entries, "
              f"{result['expanded_bytes']} expanded bytes. Final installer-bound verification remains required.")
        return
    value = json.loads(args.installer_set.read_text(encoding="utf-8"))
    build(args.output_dir, value, sources, replacements)
    print("PASS: bounded synthetic qualification evidence archived and independently verified.")


if __name__ == "__main__":
    main()
