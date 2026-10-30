#!/usr/bin/env python3
"""Opt-in acceptance evidence on a real, dedicated macOS runner.

Run after installing the same-build .pkg. Keeps the owned VM and all results;
does not edit, stop, or delete user-managed Docker/Lima installations.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time


def snapshot(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    files = [path] if path.is_file() else sorted(path.rglob("*"))
    result = {}
    for item in files:
        # User Lima VM disks may be large/running: only inventory ordinary config,
        # not large runtime files. This also avoids reading arbitrary symlinks.
        if item.is_symlink() or not item.is_file() or item.stat().st_size > 1024 * 1024:
            continue
        result[str(item)] = hashlib.sha256(item.read_bytes()).hexdigest()
    return result


def verify(app: Path, output: Path) -> dict:
    if sys.platform != "darwin":
        raise ValueError("This verification requires a real macOS host with Virtualization.framework.")
    app = app.expanduser().resolve()
    launcher = app / "Contents/Resources/NIPAT.command"
    manifest_path = app / "Contents/Resources/app/.distribution/macos-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not launcher.is_file() or manifest.get("channel") != "experimental08":
        raise ValueError("An installed experimental08 package is required.")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    log_root = output.parent / (output.stem + "-logs")
    log_root.mkdir(exist_ok=True)
    workspace = Path.home() / "Library/Application Support/NIPAT-Experimental08"
    run_root = workspace / "runs" / ("acceptance-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"-{time.time_ns()}")
    records = []
    report = {
        "schema_version": 1, "evidence": "real-macos-runtime", "channel": "experimental08",
        "version": manifest.get("version"), "source_commit": manifest.get("source_commit"),
        "host_architecture": platform.machine(), "macos_version": platform.mac_ver()[0],
        "package_architecture": manifest.get("architecture"), "runtime_image": None,
        "runs_dir": str(run_root), "checks": records, "passed": False,
    }
    protected = [Path.home() / ".docker/config.json", Path.home() / ".lima/_config"]
    before = {str(path): snapshot(path) for path in protected}

    def execute(name: str, arguments: list[str], timeout: int) -> None:
        log = log_root / (name + ".log")
        started = time.monotonic()
        with log.open("w", encoding="utf-8") as stream:
            try:
                result = subprocess.run([str(launcher), *arguments], stdout=stream, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, check=False, timeout=timeout)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
        records.append({"name": name, "passed": code == 0, "exit_code": code,
                        "seconds": round(time.monotonic() - started, 2), "log": str(log)})
        if code:
            raise RuntimeError(f"{name} failed (exit {code}); see {log}")

    try:
        execute("prepare", ["--runtime", "prepare"], 3600)
        execute("prepare-again", ["--runtime", "prepare"], 600)
        state_path = workspace / ".runtime/macos/runtime.json"
        first_state = json.loads(state_path.read_text())
        execute("doctor", ["doctor", "--runtime"], 600)
        execute("numerical-self-tests", ["--runs-dir", str(run_root), "self-test"], 3600)
        execute("cold-stop", ["--runtime", "stop"], 240)
        execute("cold-start", ["--runtime", "ensure"], 240)
        execute("doctor-after-restart", ["doctor", "--runtime"], 600)
        second_state = json.loads(state_path.read_text())
        stable = first_state["runtime_image"] == second_state["runtime_image"]
        report["runtime_image"] = second_state["runtime_image"]
        records.append({"name": "image-identity-after-restart", "passed": stable})
        unchanged = all(snapshot(path) == before[str(path)] for path in protected)
        records.append({"name": "external-docker-lima-config-unchanged", "passed": unchanged})
        report["passed"] = all(item["passed"] for item in records)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        report["error"] = str(exc)
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = verify(args.app, args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
