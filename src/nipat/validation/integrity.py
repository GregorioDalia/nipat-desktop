from __future__ import annotations

import hashlib
from pathlib import Path

from nipat.errors import ValidationError


def verify_sha256_manifest(manifest: Path) -> None:
    if not manifest.is_file():
        raise ValidationError(f"Manifest scientifico non trovato: {manifest}")
    base_dir = manifest.parent
    for line_number, line in enumerate(
        manifest.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            expected, relative_name = line.split(maxsplit=1)
        except ValueError as exc:
            raise ValidationError(
                f"Manifest SHA-256 non valido alla riga {line_number}."
            ) from exc
        target = (base_dir / relative_name).resolve()
        try:
            target.relative_to(base_dir.resolve())
        except ValueError as exc:
            raise ValidationError(
                f"Percorso non valido nel manifest alla riga {line_number}."
            ) from exc
        if not target.is_file():
            raise ValidationError(f"Sorgente scientifica non trovata: {target}")
        with target.open("rb") as handle:
            current = hashlib.file_digest(handle, "sha256").hexdigest()
        if current != expected.lower():
            raise ValidationError(
                f"La sorgente scientifica è stata modificata: {relative_name}"
            )
