"""Report-only SBOM and vulnerability monitoring of the exact published runtime archives."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import uuid

_SPEC = importlib.util.spec_from_file_location("nipat_security_release", Path(__file__).with_name("release_inputs.py"))
release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(release)
TOOLS = {
    "syft": {"version": "1.55.0",
             "url": "https://github.com/anchore/syft/releases/download/v1.55.0/syft_1.55.0_linux_amd64.tar.gz",
             "sha256": "bb65249542db5fedeeb4d3f9b018b75e7264dbfbbb10486f044581a92f90490d"},
    "grype": {"version": "0.121.0",
              "url": "https://github.com/anchore/grype/releases/download/v0.121.0/grype_0.121.0_linux_amd64.tar.gz",
              "sha256": "64e07133d3486115de647a66581461dccf5c732748a0a3119077395565f15519"},
}
MAX_SCAN_TAR_BYTES = 8 * 1024**3
MIN_FREE_BYTES = 512 * 1024**2


def install_tool(name, directory):
    record = TOOLS[name]
    # The committed digest remains the trust anchor even if upstream metadata changes.
    api = release.fetch_json(f"https://api.github.com/repos/anchore/{name}/releases/tags/v{record['version']}")
    matching = [asset for asset in api["assets"] if asset["browser_download_url"] == record["url"]]
    release.require(len(matching) == 1 and matching[0].get("digest") == "sha256:" + record["sha256"],
                    "Pinned scanner metadata mismatch")
    archive = directory / (name + ".tar.gz")
    release.checked_download(record["url"], archive, record["sha256"], matching[0]["size"], maximum=256 * 1024 * 1024)
    with tarfile.open(archive, "r:gz") as handle:
        members = [member for member in handle.getmembers() if member.name == name]
        release.require(len(members) == 1 and members[0].isfile() and members[0].size < 256 * 1024 * 1024,
                        "Pinned scanner archive has an invalid binary")
        with handle.extractfile(members[0]) as source:
            binary = directory / name
            binary.write_bytes(source.read())
            binary.chmod(0o700)
    return binary


def run_to_file(command, output):
    with output.open("wb") as handle:
        subprocess.run(command, stdout=handle, check=True, timeout=1800)


@contextmanager
def scientific_scan_tar(archive, directory, *, maximum=MAX_SCAN_TAR_BYTES,
                        minimum_free=MIN_FREE_BYTES):
    """Unwrap verified gzip bytes for Syft's plain Docker-tar reader, never extract members."""
    release.require(type(maximum) is int and maximum > 0
                    and type(minimum_free) is int and minimum_free >= 0,
                    "Invalid scientific scan resource bounds")
    with tempfile.TemporaryDirectory(prefix="scan-input-", dir=directory) as temporary:
        target = Path(temporary) / "scientific-image.tar"
        total = 0
        with gzip.open(archive, "rb") as source, target.open("xb") as destination:
            while block := source.read(1024 * 1024):
                total += len(block)
                release.require(total <= maximum, "Scientific scan tar exceeds its expanded-size bound")
                release.require(shutil.disk_usage(temporary).free >= len(block) + minimum_free,
                                "Insufficient free space for the temporary scientific scan tar")
                destination.write(block)
        # Reading to EOF also verifies gzip CRC and truncation. The caller keeps
        # the published compressed digest as its identity; no archive is changed.
        release.require(total > 0, "Scientific scan tar is empty")
        yield target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="latest")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tools_dir = output / "tools"
    tools_dir.mkdir()
    summary = {"schema_version": 1, "checked_utc": datetime.now(timezone.utc).isoformat(),
               "status": "failed", "report_only": True, "tools": TOOLS, "archives": {},
               "scope": "Component-vulnerability associations, not exploitability or scientific validation; unsupported ecosystems may be absent."}
    imported = None
    try:
        downloads = release.release_inputs(args.tag, ["rootfs", "scientific_image"], output / "inputs")
        summary["release"] = json.loads((output / "inputs/release-inputs.json").read_text())
        syft = install_tool("syft", tools_dir)
        grype = install_tool("grype", tools_dir)
        imported = "nipat-security-rootfs:" + uuid.uuid4().hex
        subprocess.run(["docker", "image", "import", str(downloads["rootfs"]), imported], check=True)
        with scientific_scan_tar(downloads["scientific_image"], output) as scientific_tar:
            for name, source in (("scientific", "docker-archive:" + str(scientific_tar)),
                                 ("wsl", "docker:" + imported)):
                sbom = output / (name + ".syft.json")
                vulnerabilities = output / (name + ".grype.json")
                run_to_file([str(syft), source, "-o", "syft-json"], sbom)
                run_to_file([str(grype), "sbom:" + str(sbom), "-o", "json"], vulnerabilities)
                report = json.loads(vulnerabilities.read_text())
                summary["archives"][name] = {
                    "sbom_sha256": hashlib.sha256(sbom.read_bytes()).hexdigest(),
                    "vulnerability_report_sha256": hashlib.sha256(vulnerabilities.read_bytes()).hexdigest(),
                    "candidate_associations": len(report.get("matches", [])),
                    "database": report.get("descriptor", {}).get("db", {}),
                }
        summary["status"] = "completed"
    except Exception as exc:
        summary["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if imported:
            subprocess.run(["docker", "image", "rm", imported], check=False)
        (output / "security-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
