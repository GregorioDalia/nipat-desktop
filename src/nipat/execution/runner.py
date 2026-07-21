from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.paths import ProjectLayout
from nipat.validation.integrity import verify_sha256_manifest


class DockerComposeRunner:
    def __init__(self, layout: ProjectLayout, dry_run: bool = False) -> None:
        self.layout = layout
        self.dry_run = dry_run

    def _base_command(self) -> list[str]:
        return ["docker", "compose", "-f", str(self.layout.compose_file)]

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["NIPAT_WORKSPACE_DIR"] = str(self.layout.workspace_dir)
        environment["NIPAT_PROJECT_DIR"] = str(self.layout.project_dir)
        environment["NIPAT_DATA_DIR"] = str(self.layout.data_dir)
        environment["NIPAT_RUNS_DIR"] = str(self.layout.runs_dir)
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            environment["NIPAT_UID"] = str(os.getuid())
            environment["NIPAT_GID"] = str(os.getgid())
        return environment

    def run(
        self,
        command: Iterable[str | PurePosixPath],
        *,
        working_dir: PurePosixPath | None = None,
    ) -> None:
        docker_command = self._base_command() + ["run", "--rm"]
        if working_dir is not None:
            docker_command.extend(["--workdir", str(working_dir)])
        docker_command.append("scientific")
        docker_command.extend(str(part) for part in command)
        print("$", subprocess.list2cmdline(docker_command), flush=True)
        if self.dry_run:
            return
        try:
            subprocess.run(
                docker_command,
                cwd=self.layout.project_dir,
                env=self._environment(),
                check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeExecutionError(
                "Docker non è disponibile. Avvia Docker Desktop e riprova."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeExecutionError(
                f"Il runtime scientifico è terminato con codice {exc.returncode}."
            ) from exc

    def build(self) -> None:
        command = self._base_command() + ["build", "scientific"]
        print("$", subprocess.list2cmdline(command), flush=True)
        if self.dry_run:
            return
        try:
            subprocess.run(
                command,
                cwd=self.layout.project_dir,
                env=self._environment(),
                check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeExecutionError("Docker non è disponibile.") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeExecutionError(
                f"Build del runtime fallita con codice {exc.returncode}."
            ) from exc

    def doctor(self, check_runtime: bool) -> None:
        if shutil.which("docker") is None:
            raise ValidationError("Comando 'docker' non trovato nel PATH.")
        if not self.layout.compose_file.is_file():
            raise ValidationError(f"compose.yaml non trovato: {self.layout.compose_file}")
        verify_sha256_manifest(self.layout.project_dir / "scientific" / "SHA256SUMS")
        for required_dir in (
            self.layout.data_dir / "reference",
            self.layout.data_dir / "samples",
            self.layout.data_dir / "panels",
            self.layout.runs_dir,
        ):
            if not required_dir.is_dir():
                raise ValidationError(f"Cartella di workspace non trovata: {required_dir}")
        try:
            subprocess.run(["docker", "compose", "version"], check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeExecutionError("Docker Compose non è disponibile.") from exc
        if check_runtime:
            self.run(
                [
                    "bash",
                    "-lc",
                    "R --version | head -n 1; samtools --version | head -n 1; python3 --version",
                ]
            )
