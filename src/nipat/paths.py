from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from nipat.errors import ValidationError


_SAFE_RUN_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ProjectLayout:
    project_dir: Path
    workspace_dir: Path
    data_dir: Path
    runs_dir: Path
    compose_file: Path

    @classmethod
    def discover(cls) -> "ProjectLayout":
        project_dir = Path(
            os.environ.get("NIPAT_PROJECT_DIR", Path(__file__).resolve().parents[2])
        ).resolve()
        workspace_dir = Path(
            os.environ.get("NIPAT_WORKSPACE_DIR", project_dir.parent)
        ).resolve()
        return cls(
            project_dir=project_dir,
            workspace_dir=workspace_dir,
            data_dir=workspace_dir / "data",
            runs_dir=workspace_dir / "runs",
            compose_file=project_dir / "compose.yaml",
        )

    def container_path(self, host_path: Path) -> PurePosixPath:
        resolved = host_path.expanduser().resolve()
        mounts = (
            (self.project_dir, PurePosixPath("/workspace/nipat-desktop")),
            (self.data_dir, PurePosixPath("/workspace/data")),
            (self.runs_dir, PurePosixPath("/workspace/runs")),
        )
        for host_root, container_root in mounts:
            try:
                relative = resolved.relative_to(host_root)
            except ValueError:
                continue
            return container_root.joinpath(*relative.parts)
        raise ValidationError(
            "Il percorso deve trovarsi nel progetto oppure nelle cartelle data/runs "
            f"di {self.workspace_dir}: {resolved}"
        )

    def new_run_dir(self, workflow: str, requested_name: str | None = None) -> Path:
        if requested_name:
            clean_name = _SAFE_RUN_NAME.sub("-", requested_name.strip()).strip("-.")
            if not clean_name:
                raise ValidationError("Il nome dell'esecuzione non contiene caratteri validi.")
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            clean_name = f"{workflow}-{stamp}"

        run_dir = self.runs_dir / clean_name
        if run_dir.exists():
            raise ValidationError(f"La cartella dell'esecuzione esiste già: {run_dir}")
        (run_dir / "work").mkdir(parents=True)
        (run_dir / "output").mkdir()
        return run_dir
