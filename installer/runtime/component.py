"""Content identity of the dedicated WSL component, independent of the client."""

import hashlib
import json
from pathlib import Path


SOURCE_FILES = ("Dockerfile", "component.py", "nipat-engine", "write-provenance.py", "wsl.conf")


def source_inventory(directory: Path) -> dict[str, str]:
    inventory = {}
    for name in SOURCE_FILES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Runtime source missing or linked: {name}")
        inventory[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return inventory


def component_identity(provenance: dict) -> str:
    """Hash resolved software inputs, excluding the exported image's own ID."""
    identity = {key: value for key, value in provenance.items()
                if key not in {"component_sha256", "rootfs_image_id"}}
    if (identity.get("schema_version") != 2 or identity.get("vendor") != "nipat-desktop"
            or identity.get("purpose") != "dedicated-wsl-runtime"
            or set(identity.get("source_sha256", {})) != set(SOURCE_FILES)
            or not identity.get("apt_packages")
            or not identity.get("base_image") or not identity.get("docker_engine_version")
            or not identity.get("compose_version")):
        raise ValueError("Incomplete WSL component identity")
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode("ascii")).hexdigest()
