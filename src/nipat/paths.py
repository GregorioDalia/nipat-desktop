from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from nipat.errors import ValidationError
from nipat.storage import resolve_storage_path, validate_managed_directories


_SAFE_RUN_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ProjectLayout:
    project_dir: Path
    workspace_dir: Path
    data_dir: Path
    runs_dir: Path
    compose_file: Path

    @classmethod
    def discover(
        cls, *, data_dir: Path | str | None = None, runs_dir: Path | str | None = None
    ) -> "ProjectLayout":
        project_dir = Path(
            os.environ.get("NIPAT_PROJECT_DIR", Path(__file__).resolve().parents[2])
        ).expanduser().resolve()
        workspace_dir = Path(
            os.environ.get("NIPAT_WORKSPACE_DIR", project_dir.parent)
        ).expanduser().resolve()
        layout = cls(
            project_dir=project_dir,
            workspace_dir=workspace_dir,
            data_dir=resolve_storage_path(
                data_dir if data_dir is not None else os.environ.get("NIPAT_DATA_DIR", workspace_dir / "data")
            ),
            runs_dir=resolve_storage_path(
                runs_dir if runs_dir is not None else os.environ.get("NIPAT_RUNS_DIR", workspace_dir / "runs")
            ),
            compose_file=project_dir / "compose.yaml",
        )
        layout.validate_storage_roots()
        return layout

    def validate_storage_roots(self) -> None:
        roots = {
            "progetto": self.project_dir.resolve(),
            "dati": resolve_storage_path(self.data_dir),
            "risultati": resolve_storage_path(self.runs_dir),
        }
        for label, path in roots.items():
            if path == Path(path.anchor):
                raise ValidationError(f"La cartella {label} non può essere la radice di un disco: {path}")
            if path.exists() and not path.is_dir():
                raise ValidationError(f"Il percorso {label} non è una cartella: {path}")
        items = list(roots.items())
        for index, (label, path) in enumerate(items):
            for other_label, other in items[index + 1:]:
                if path.is_relative_to(other) or other.is_relative_to(path):
                    raise ValidationError(
                        f"Le cartelle {label} e {other_label} devono essere separate, "
                        f"senza sovrapporsi: {path}; {other}"
                    )
        validate_managed_directories(self)

    def ensure_storage_dirs(self) -> None:
        self.validate_storage_roots()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def container_path(self, host_path: Path) -> PurePosixPath:
        resolved = host_path.expanduser().resolve()
        mounts = (
            (self.project_dir, PurePosixPath("/workspace/nipat-desktop")),
            (self.data_dir, PurePosixPath("/workspace/data")),
            (self.runs_dir, PurePosixPath("/workspace/runs")),
        )
        for host_root, container_root in mounts:
            try:
                relative = resolved.relative_to(host_root.resolve())
            except ValueError:
                continue
            return container_root.joinpath(*relative.parts)
        raise ValidationError(
            "Percorso interno non presente nel progetto o nelle cartelle data/runs "
            f"configurate: {resolved}. Dati: {self.data_dir}; risultati: {self.runs_dir}."
        )

    def new_run_dir(self, workflow: str, requested_name: str | None = None) -> Path:
        self.ensure_storage_dirs()
        if requested_name:
            clean_name = _SAFE_RUN_NAME.sub("-", requested_name.strip()).strip("-.")
            if not clean_name:
                raise ValidationError("Il nome dell'esecuzione non contiene caratteri validi.")
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            clean_name = f"{workflow}-{stamp}"

        run_dir = self.runs_dir / clean_name
        try:
            run_dir.mkdir()
        except FileExistsError as exc:
            raise ValidationError(f"La cartella dell'esecuzione esiste già: {run_dir}") from exc
        (run_dir / "work").mkdir()
        (run_dir / "output").mkdir()
        return run_dir
