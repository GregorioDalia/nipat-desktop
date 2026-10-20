"""Exact, read-only input file mounts with safe container-side aliases."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from nipat.errors import ValidationError
from nipat.paths import ProjectLayout


INPUT_ROOT = PurePosixPath("/workspace/inputs")
def _safe_basename(name: str) -> str:
    original = PurePosixPath(name)
    ascii_stem = unicodedata.normalize("NFKD", original.stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_stem).strip("._-") or "input"
    suffix = re.sub(r"[^A-Za-z0-9.]+", "_", original.suffix)
    safe = stem + suffix
    if len(safe) > 100:
        suffix = PurePosixPath(safe).suffix[:16]
        safe = safe[:100 - len(suffix)] + suffix
    return safe


class InputMounts:
    """Map selected files only; never expose an input directory or whole drive."""

    def __init__(self, layout: ProjectLayout):
        self.layout = layout
        self._files: dict[PurePosixPath, Path] = {}
        self._frozen = False

    @property
    def mappings(self) -> list[dict[str, Any]]:
        return [
            {"host_path": str(source), "container_path": str(target), "read_only": True}
            for target, source in self._files.items()
        ]

    def bind_file(
        self, path: Path, *, target: str | PurePosixPath | None = None
    ) -> PurePosixPath:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValidationError(f"File di input non trovato: {source}")
        if target is None:
            for existing_target, existing_source in self._files.items():
                if source == existing_source:
                    return existing_target
            number = len(self._files) + 1
            target = INPUT_ROOT / f"input-{number:03d}" / _safe_basename(source.name)
            while any(target.is_relative_to(old) or old.is_relative_to(target) for old in self._files):
                number += 1
                target = INPUT_ROOT / f"input-{number:03d}" / _safe_basename(source.name)
        else:
            text = str(target)
            # Check the original components before PurePosixPath normalizes them.
            if (
                "\\" in text or any(unicodedata.category(char) == "Cc" for char in text)
                or any(part in ("", ".", "..") for part in text[1:].split("/"))
            ):
                raise ValidationError(f"Alias di input non valido: {text}")
            target = PurePosixPath(text)
            if not target.is_absolute() or not target.is_relative_to(INPUT_ROOT) or target == INPUT_ROOT:
                raise ValidationError(f"L'alias deve essere un file sotto {INPUT_ROOT}: {text}")
        if target in self._files and self._files[target] == source:
            return target
        if self._frozen:
            raise ValidationError("I mount di input sono già stati registrati per questa esecuzione.")
        for existing in self._files:
            if target.is_relative_to(existing) or existing.is_relative_to(target):
                raise ValidationError(f"Alias di input duplicato o sovrapposto: {target}")
        self._files[target] = source
        return target

    def compose_override(self, *, source_path: Callable[[Path], str] = str) -> dict[str, Any]:
        volumes = []
        for target, source in self._files.items():
            # A disappeared source must not become an empty directory in Docker.
            if not source.is_file():
                raise ValidationError(f"File di input non più disponibile: {source}")
            volumes.append({
                "type": "bind",
                "source": source_path(source).replace("$", "$$"),
                "target": str(target).replace("$", "$$"),
                "read_only": True,
                "bind": {"create_host_path": False},
            })
        return {"services": {"scientific": {"volumes": volumes}}}

    def write_override(
        self, destination: Path, *, source_path: Callable[[Path], str] = str,
    ) -> None:
        document = self.compose_override(source_path=source_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # An immutable run must not replace evidence from a prior invocation.
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        self._frozen = True
