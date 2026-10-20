from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, TextIO

from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.mounts import InputMounts
from nipat.execution.tracking import RunRecord, file_evidence, project_evidence, utc_now
from nipat.execution.transport import DockerTransport
from nipat.paths import ProjectLayout
from nipat.validation.integrity import verify_sha256_manifest


class DockerComposeRunner:
    def __init__(self, layout: ProjectLayout, dry_run: bool = False) -> None:
        self.layout = layout
        self.dry_run = dry_run
        self._record: RunRecord | None = None
        self._log: TextIO | None = None
        self._image_id: str | None = None
        self._input_mounts_file: Path | None = None
        self._transport = DockerTransport.from_environment(dry_run=dry_run)
        self._backend_ready = False

    def _base_command(self) -> list[str]:
        command = ["docker", "compose", "-f", self._transport.host_path(self.layout.compose_file)]
        if self._input_mounts_file is not None:
            command.extend(["-f", self._transport.host_path(self._input_mounts_file)])
        return command

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["NIPAT_WORKSPACE_DIR"] = str(self.layout.workspace_dir)
        environment["NIPAT_PROJECT_DIR"] = str(self.layout.project_dir)
        environment["NIPAT_DATA_DIR"] = str(self.layout.data_dir)
        environment["NIPAT_RUNS_DIR"] = str(self.layout.runs_dir)
        if self._image_id:
            environment["NIPAT_RUNTIME_IMAGE"] = self._image_id
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            environment["NIPAT_UID"] = str(os.getuid())
            environment["NIPAT_GID"] = str(os.getgid())
        return environment

    def _write(self, text: str, *, terminal: bool = True) -> None:
        if self._log is not None:
            self._log.write(text)
            self._log.flush()
        if not terminal:
            return
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except UnicodeEncodeError:
            safe = text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
                sys.stdout.encoding or "utf-8"
            )
            sys.stdout.write(safe)
            sys.stdout.flush()

    def _capture(self, command: list[str], *, container_name: str | None = None) -> str:
        self._ensure_backend()
        return self._capture_process(
            self._transport.command(command, self._environment()), container_name=container_name,
        )

    def _ensure_backend(self) -> None:
        if self.dry_run or self._backend_ready:
            return
        command = self._transport.ensure_command()
        if command is not None:
            # The helper bounds both its startup lock and the daemon readiness wait.
            self._capture_process(command, timeout=240)
        self._backend_ready = True

    def _capture_process(
        self, command: list[str], *, container_name: str | None = None, timeout: int = 90,
    ) -> str:
        check = {"argv": command, "started_at": utc_now(), "returncode": None}
        if self._record:
            self._record.data["checks"].append(check)
            self._record.save()
        self._write("$ " + subprocess.list2cmdline(command) + "\n", terminal=False)
        try:
            result = subprocess.run(
                command, cwd=self.layout.project_dir, env=self._environment(),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, check=False,
            )
            check["returncode"] = result.returncode
            self._write(result.stdout, terminal=result.returncode != 0)
            self._write(result.stderr, terminal=result.returncode != 0)
            if result.returncode:
                raise RuntimeExecutionError(
                    f"Controllo del runtime fallito (codice {result.returncode}). "
                    + self._transport.unavailable_message
                )
            return result.stdout.strip()
        except FileNotFoundError as exc:
            raise RuntimeExecutionError(self._transport.unavailable_message) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeExecutionError(
                f"Il controllo del runtime ha superato {timeout} secondi. "
                + self._transport.unavailable_message
            ) from exc
        finally:
            if container_name is not None and check["returncode"] != 0:
                check["container_cleanup"] = self._stop_container(container_name)
            check["finished_at"] = utc_now()
            if self._record:
                self._record.save()

    def _prepare_runtime(self) -> None:
        os_type = self._capture(["docker", "info", "--format", "{{.OSType}}"])
        if os_type != "linux":
            raise RuntimeExecutionError("Il runtime NIPAT richiede Docker con container Linux.")
        config = json.loads(self._capture(self._base_command() + ["config", "--format", "json"]))
        image_name = config["services"]["scientific"]["image"]
        inspected = json.loads(self._capture([
            "docker", "image", "inspect", image_name,
            "--format", '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}}}',
        ]))
        image_id, image_os, architecture = (
            inspected["id"], inspected["os"], inspected["architecture"]
        )
        if image_os != "linux":
            raise RuntimeExecutionError("L'immagine scientifica deve essere Linux.")
        self._image_id = image_id
        if self._record:
            self._record.data["runtime"] = {
                **self._transport.metadata,
                "requested_image": image_name, "image_id": image_id,
                "os": image_os, "architecture": architecture,
            }
            self._record.save()
        # Pin execution to this image ID; later changes to its tag cannot change this run.
        probe_name = "nipat-probe-" + uuid.uuid4().hex
        versions = self._capture([
            "docker", "run", "--rm", "--pull=never", "--name", probe_name, image_id, "sh", "-c",
            "set -e; Rscript -e 'cat(R.version.string, \"\\n\"); "
            "p <- c(\"argparse\",\"ComplexUpset\",\"dplyr\",\"ggplot2\",\"openxlsx\","
            "\"optparse\",\"patchwork\",\"purrr\",\"readr\",\"readxl\",\"stringr\","
            "\"tidyr\",\"tidyverse\"); "
            "for (x in p) cat(x, as.character(packageVersion(x)), \"\\n\")'; "
            "samtools --version",
        ], container_name=probe_name)
        if self._record:
            self._record.data["runtime"]["versions_output"] = versions
            self._record.save()
            self._write("Runtime scientifico pronto.\n")
        else:
            self._write(f"Runtime: {image_id} ({architecture})\n{versions}\n")

    @contextmanager
    def record_run(
        self, run_dir: Path, *, workflow: str, inputs: list[Path], parameters: dict[str, Any],
        mounts: InputMounts | None = None,
    ) -> Iterator[RunRecord]:
        if self._record is not None:
            raise RuntimeExecutionError("Questo runner sta già registrando un'esecuzione.")
        record = RunRecord(run_dir, workflow, parameters)
        self._record = record
        # A wizard can reuse this runner after WSL has stopped between analyses.
        self._backend_ready = False
        record.data["transport"] = self._transport.metadata
        try:
            with record.log_path.open("x", encoding="utf-8", newline="\n") as log:
                self._log = log
                try:
                    self._write(f"NIPAT {workflow}: {run_dir}\n")
                    self.layout.ensure_storage_dirs()
                    record.data["inputs"] = [file_evidence(path) for path in inputs]
                    record.data["source"] = project_evidence(self.layout.project_dir)
                    record.data["input_mounts"] = []
                    if mounts is not None:
                        if mounts.layout != self.layout:
                            raise ValidationError("I mount appartengono a un altro workspace.")
                        mount_file = run_dir / "work" / "input-mounts.json"
                        mounts.write_override(mount_file, source_path=self._transport.host_path)
                        self._input_mounts_file = mount_file
                        record.data["input_mounts"] = mounts.mappings
                        record.data["compose_override"] = "work/input-mounts.json"
                    record.save()
                    verify_sha256_manifest(self.layout.project_dir / "scientific" / "SHA256SUMS")
                    if not self.dry_run:
                        self._prepare_runtime()
                    record.data["status"] = "planned" if self.dry_run else "running"
                    record.save()
                    yield record
                except BaseException as exc:
                    record.data["status"] = (
                        "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
                    )
                    record.data["error"] = {"type": type(exc).__name__, "message": str(exc)}
                    self._write(f"{record.data['status']}: {type(exc).__name__}: {exc}\n")
                    raise
                else:
                    record.data["status"] = "planned" if self.dry_run else "succeeded"
                    self._write(f"{record.data['status']}: {workflow}\n")
                finally:
                    record.data["finished_at"] = utc_now()
                    record.save()
        finally:
            self._log = None
            self._record = None
            self._image_id = None
            self._input_mounts_file = None
            self._backend_ready = False

    def run(
        self, command: Iterable[str | PurePosixPath], *, working_dir: PurePosixPath | None = None
    ) -> None:
        if self._record is None:
            self._backend_ready = False
        if not self.dry_run:
            self._ensure_backend()
        container_name = "nipat-run-" + uuid.uuid4().hex
        docker_command = self._base_command() + [
            "run", "--rm", "-T", "--pull", "never", "--name", container_name,
        ]
        if working_dir is not None:
            docker_command.extend(["--workdir", str(working_dir)])
        docker_command.append("scientific")
        docker_command.extend(str(part) for part in command)
        docker_command = self._transport.command(docker_command, self._environment())
        stage: dict[str, Any] = {
            "argv": docker_command, "working_dir": str(working_dir) if working_dir else None,
            "container_name": container_name, "started_at": utc_now(),
            "finished_at": None, "returncode": None,
            "status": "planned" if self.dry_run else "running",
        }
        if self._record:
            self._record.data["commands"].append(stage)
            self._record.save()
        self._write("$ " + subprocess.list2cmdline(docker_command) + "\n")
        if self.dry_run:
            stage["finished_at"] = utc_now()
            if self._record:
                self._record.save()
            return
        process = None
        try:
            process = subprocess.Popen(
                docker_command, cwd=self.layout.project_dir, env=self._environment(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
            assert process.stdout is not None
            with process.stdout:
                for line in process.stdout:
                    self._write(line)
            stage["returncode"] = process.wait()
            if stage["returncode"]:
                stage["status"] = "failed"
                raise RuntimeExecutionError(
                    f"Il runtime scientifico è terminato con codice {stage['returncode']}."
                )
            stage["status"] = "succeeded"
        except FileNotFoundError as exc:
            stage["status"] = "failed"
            raise RuntimeExecutionError(self._transport.unavailable_message) from exc
        except BaseException as exc:
            interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
            if interrupted or (process is not None and process.poll() is None):
                # Stopping the client alone can leave its container running in the engine.
                stage["container_cleanup"] = self._stop_container(container_name)
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            stage["status"] = (
                "interrupted" if interrupted else "failed"
            )
            if process is not None:
                stage["returncode"] = process.poll()
            raise
        finally:
            stage["finished_at"] = utc_now()
            if self._record:
                self._record.save()

    def _stop_container(self, container_name: str) -> dict[str, Any]:
        command = None
        try:
            command = self._transport.command(
                ["docker", "rm", "--force", container_name], self._environment(),
            )
            result = subprocess.run(
                command, env=self._environment(),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=15, check=False,
            )
            cleanup = {
                "status": "removed" if result.returncode == 0 else "not_confirmed",
                "returncode": result.returncode, "message": result.stderr.strip(),
            }
        except (OSError, subprocess.SubprocessError, RuntimeExecutionError, ValidationError) as exc:
            cleanup = {"status": "not_confirmed", "returncode": None, "message": str(exc)}
        cleanup["argv"] = command
        if cleanup["status"] == "not_confirmed":
            self._write(
                f"Arresto del container {container_name} non confermato; "
                "verificarne lo stato nel runtime NIPAT.\n"
            )
        return cleanup

    def build(self) -> None:
        self._backend_ready = False
        if not self.dry_run:
            self._ensure_backend()
        command = self._base_command() + ["build", "scientific"]
        command = self._transport.command(command, self._environment())
        self._write("$ " + subprocess.list2cmdline(command) + "\n")
        if self.dry_run:
            return
        try:
            subprocess.run(
                command, cwd=self.layout.project_dir, env=self._environment(), check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeExecutionError(self._transport.unavailable_message) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeExecutionError(f"Build del runtime fallita con codice {exc.returncode}.") from exc

    def doctor(self, check_runtime: bool) -> None:
        self._backend_ready = False
        if shutil.which(self._transport.executable) is None:
            raise ValidationError(
                f"Comando '{self._transport.executable}' non trovato nel PATH. "
                + self._transport.unavailable_message
            )
        if not self.layout.compose_file.is_file():
            raise ValidationError(f"compose.yaml non trovato: {self.layout.compose_file}")
        verify_sha256_manifest(self.layout.project_dir / "scientific" / "SHA256SUMS")
        self.layout.ensure_storage_dirs()
        self._capture(["docker", "compose", "version"])
        if check_runtime:
            try:
                self._prepare_runtime()
            finally:
                self._image_id = None
