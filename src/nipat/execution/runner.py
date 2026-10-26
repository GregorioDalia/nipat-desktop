from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, TextIO

from nipat import __version__
from nipat.errors import RuntimeExecutionError, ValidationError
from nipat.execution.mounts import InputMounts
from nipat.execution.tracking import RunRecord, file_evidence, project_evidence, utc_now
from nipat.execution.transport import DockerTransport
from nipat.paths import ProjectLayout
from nipat.validation.integrity import verify_sha256_manifest


BUNDLED_WORKFLOW_INTERFACES = {
    "dnp-call": "dnp-call-v1",
    "contamination": "contamination-v1",
    "snp-call": "snp-call-v1",
    "cpi": "cpi-v1",
}
BUNDLED_WORKFLOW_LABELS = {
    "contamination": "Contamination", "dnp-call": "DNPcall", "snp-call": "SNPcall", "cpi": "CPI",
    "workflow-plan": "Workflow automatico",
    "workflow-plan-cpi": "Workflow automatico con CPI",
}
PLAN_EXECUTION_INTERFACE = "workflow-plan-execution-v1"
PLAN_WORKFLOWS = {
    "workflow-plan": ("dnp-call", "contamination"),
    "workflow-plan-cpi": ("dnp-call", "contamination", "cpi"),
}


class DockerComposeRunner:
    def __init__(
        self, layout: ProjectLayout, dry_run: bool = False, *,
        transport: DockerTransport | None = None,
    ) -> None:
        self.layout = layout
        self.dry_run = dry_run
        self._record: RunRecord | None = None
        self._log: TextIO | None = None
        self._image_id: str | None = None
        self._input_mounts_file: Path | None = None
        self._engine_compose_file: Path | None = None
        self._bundled_workflow: str | None = None
        self._transport = transport if transport is not None else DockerTransport.from_environment(
            dry_run=dry_run,
        )
        self._backend_ready = False

    def _base_command(self) -> list[str]:
        if self._engine_compose_file is not None:
            return ["docker", "compose", "-f", self._transport.host_path(self._engine_compose_file)]
        command = ["docker", "compose", "-f", self._transport.host_path(self.layout.compose_file)]
        if self._input_mounts_file is not None:
            command.extend(["-f", self._transport.host_path(self._input_mounts_file)])
        return command

    def _write_engine_compose(self, image: str) -> None:
        """Create an independent service; Compose overrides retain legacy mounts."""
        if self._record is None:
            raise RuntimeExecutionError("Il motore incorporato richiede un'esecuzione registrata.")
        run_dir = self._record.run_dir
        volumes = []
        if self._input_mounts_file is not None:
            document = json.loads(self._input_mounts_file.read_text(encoding="utf-8"))
            volumes.extend(document["services"]["scientific"]["volumes"])
        volumes.append({
            "type": "bind", "source": self._transport.host_path(run_dir).replace("$", "$$"),
            "target": str(self.layout.container_path(run_dir)).replace("$", "$$"),
            "read_only": False, "bind": {"create_host_path": False},
        })
        service = {
            "image": image,
            "user": "${NIPAT_UID:-0}:${NIPAT_GID:-0}",
            "read_only": True, "network_mode": "none",
            "tmpfs": ["/tmp:rw,nosuid,nodev,size=128m"],
            "working_dir": str(self.layout.container_path(run_dir / "work")),
            "volumes": volumes,
            "environment": {"HOME": "/tmp", "TMPDIR": "/tmp", "LANG": "C.UTF-8",
                            "LC_ALL": "C.UTF-8", "TZ": "Europe/Rome"},
        }
        destination = run_dir / "work" / "engine-compose.json"
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump({"name": "nipat", "services": {"scientific": service}}, handle,
                      ensure_ascii=False, indent=2)
            handle.write("\n")
        self._engine_compose_file = destination
        self._record.data["engine_compose"] = "work/engine-compose.json"
        self._record.save()

    @staticmethod
    def _validate_engine_description(
        description: Any, workflow: str | None = None,
    ) -> dict[str, Any]:
        """Validate the negotiated contract, recording image-owned source hashes."""
        digest = re.compile(r"[0-9a-f]{64}\Z")
        required_workflows = {"dnp-call", "snp-call", "contamination", "cpi"}
        required_preparation = {
            "engine/main.py", "lib/nipat_scientific/__init__.py",
            "lib/nipat_scientific/errors.py", "lib/nipat_scientific/panels.py",
            "lib/nipat_scientific/files.py", "lib/nipat_scientific/contamination.py",
            "lib/nipat_scientific/snp.py", "lib/nipat_scientific/dnp.py",
            "lib/nipat_scientific/cpi.py",
        }

        def has_digest(value: Any) -> bool:
            return isinstance(value, str) and digest.fullmatch(value) is not None

        def relative_path(value: Any, prefix: str) -> bool:
            return (isinstance(value, str) and value.startswith(prefix) and "\\" not in value
                    and all(part not in ("", ".", "..") for part in value.split("/")))

        is_plan = workflow in PLAN_WORKFLOWS
        if is_plan:
            required_preparation.update({
                "lib/nipat_scientific/plan.py", "lib/nipat_scientific/executor.py",
            })
        expected_interfaces = (
            BUNDLED_WORKFLOW_INTERFACES if workflow is None else
            {name: BUNDLED_WORKFLOW_INTERFACES[name] for name in PLAN_WORKFLOWS[workflow]}
            if is_plan else
            {workflow: BUNDLED_WORKFLOW_INTERFACES.get(workflow)}
        )
        valid = isinstance(description, dict) and all(expected_interfaces.values())
        if valid:
            manifest = description.get("manifest")
            workflows = description.get("workflows")
            interfaces = description.get("workflow_interfaces")
            preparation = description.get("preparation")
            valid = (
                type(description.get("schema_version")) is int
                and description.get("schema_version") == 1
                and description.get("interface") == "native-r-v1"
                and isinstance(interfaces, dict)
                and all(interfaces.get(name) == expected
                        for name, expected in expected_interfaces.items())
                and isinstance(manifest, dict)
                and manifest.get("path") == "scientific/SHA256SUMS"
                and has_digest(manifest.get("sha256"))
                and isinstance(workflows, dict)
                and set(workflows) == required_workflows
                and all(isinstance(source, dict)
                        and relative_path(source.get("script"), "scientific/")
                        and has_digest(source.get("sha256")) for source in workflows.values())
                and isinstance(preparation, dict)
                and preparation.get("interface") == "workflow-preparation-v1"
                and isinstance(preparation.get("file_sha256"), dict)
            )
            if valid:
                files = preparation["file_sha256"]
                valid = required_preparation.issubset(files) and all(
                    (path == "engine/main.py" or relative_path(path, "lib/nipat_scientific/"))
                    and has_digest(value) for path, value in files.items()
                )
            if valid and is_plan:
                execution = description.get("plan_execution")
                valid = (
                    isinstance(execution, dict)
                    and execution.get("interface") == PLAN_EXECUTION_INTERFACE
                    and type(execution.get("schema_version")) is int
                    and execution["schema_version"] == 1
                    and isinstance(execution.get("workflows"), list)
                    and set(PLAN_WORKFLOWS[workflow]).issubset(
                        value for value in execution["workflows"] if isinstance(value, str)
                    )
                    and execution.get("scheduling") == "sequential"
                    and execution.get("resume") is False
                )
        if not valid:
            label = (BUNDLED_WORKFLOW_LABELS.get(workflow, workflow)
                     if workflow is not None else "dei quattro workflow")
            contracts = ", ".join(str(value) for value in expected_interfaces.values())
            if is_plan:
                contracts = PLAN_EXECUTION_INTERFACE + ", " + contracts
            raise RuntimeExecutionError(
                f"L'immagine non offre il contratto {label} "
                f"incorporato richiesto ({contracts}), con metadati scientifici completi. "
                "Usare un runtime costruito per questa versione di NIPAT."
            )
        return description

    def _describe_bundled_engine(self) -> dict[str, Any]:
        if self._image_id is None:
            raise RuntimeExecutionError("Il runtime incorporato non è stato preparato.")
        probe_name = "nipat-probe-" + uuid.uuid4().hex
        try:
            output = self._capture([
                "docker", "run", "--rm", "--pull=never", "--name", probe_name,
                "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m",
                "--env", "HOME=/tmp", "--env", "TMPDIR=/tmp", self._image_id,
                "python3", "/opt/nipat/engine/main.py", "describe", "--json",
            ], container_name=probe_name)
            description = json.loads(output)
        except (RuntimeExecutionError, ValueError) as exc:
            raise RuntimeExecutionError(
                "Verifica del motore scientifico incorporato fallita. "
                "Usare un runtime costruito per questa versione di NIPAT."
                + (" Consultare execution.log per i dettagli." if self._record else "")
            ) from exc
        verified = self._validate_engine_description(
            description, self._bundled_workflow,
        )
        if self._record:
            self._record.data["runtime"]["engine"] = verified
            self._record.save()
        return verified

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
                timeout=timeout, check=False, stdin=subprocess.DEVNULL,
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
        # Compose provides image selection only. Probes run without host mounts.
        base = ["docker", "compose", "-f", self._transport.host_path(self.layout.compose_file)]
        config = json.loads(self._capture(base + ["config", "--format", "json"]))
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
        if (
            not isinstance(image_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        ):
            raise RuntimeExecutionError("Identità immutabile dell'immagine non valida.")
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
        isolation = [
            "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m",
            "--env", "HOME=/tmp", "--env", "TMPDIR=/tmp",
        ]
        versions = self._capture([
            "docker", "run", "--rm", "--pull=never", "--name", probe_name,
            *isolation, image_id, "sh", "-c",
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
        bundled_workflow: str | None = None,
    ) -> Iterator[RunRecord]:
        if self._record is not None:
            raise RuntimeExecutionError("Questo runner sta già registrando un'esecuzione.")
        if (bundled_workflow is not None and bundled_workflow not in BUNDLED_WORKFLOW_INTERFACES
                and bundled_workflow not in PLAN_WORKFLOWS):
            raise ValidationError(f"Workflow incorporato non supportato: {bundled_workflow}")
        record = RunRecord(run_dir, workflow, parameters)
        self._record = record
        self._bundled_workflow = bundled_workflow
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
                    if bundled_workflow is not None:
                        record.data["source"]["role"] = "client"
                        record.data["bundled_workflow"] = bundled_workflow
                    record.data["input_mounts"] = []
                    if mounts is not None:
                        if mounts.layout != self.layout:
                            raise ValidationError("I mount appartengono a un altro workspace.")
                        mount_file = run_dir / "work" / "input-mounts.json"
                        mounts.write_override(mount_file, source_path=self._transport.host_path)
                        self._input_mounts_file = mount_file
                        record.data["input_mounts"] = mounts.mappings
                        key = "input_mount_manifest" if bundled_workflow else "compose_override"
                        record.data[key] = "work/input-mounts.json"
                    record.save()
                    if bundled_workflow is None:
                        verify_sha256_manifest(self.layout.project_dir / "scientific" / "SHA256SUMS")
                    if not self.dry_run:
                        self._prepare_runtime()
                    if bundled_workflow is not None:
                        if self.dry_run:
                            record.data["engine_verification"] = "not_run_dry_run"
                            image = f"${{NIPAT_RUNTIME_IMAGE:-nipat-scientific-runtime:{__version__}}}"
                        else:
                            self._describe_bundled_engine()
                            record.data["engine_verification"] = "verified"
                            image = self._image_id
                            if not isinstance(image, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None:
                                raise RuntimeExecutionError("Identità immutabile dell'immagine non valida.")
                        self._write_engine_compose(image)
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
            self._engine_compose_file = None
            self._bundled_workflow = None
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
        graceful = None
        if self._bundled_workflow in PLAN_WORKFLOWS:
            # The plan coordinator must receive SIGTERM before removal so it
            # can stop its child process group and persist cancelled/blocked
            # step states. Forced removal remains a bounded fallback.
            try:
                stop_command = self._transport.command(
                    ["docker", "stop", "--time", "10", container_name], self._environment(),
                )
                stopped = subprocess.run(
                    stop_command, env=self._environment(), capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=20, check=False,
                )
                graceful = {"returncode": stopped.returncode, "message": stopped.stderr.strip()}
            except (OSError, subprocess.SubprocessError, RuntimeExecutionError, ValidationError) as exc:
                graceful = {"returncode": None, "message": str(exc)}
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
                "status": ("removed" if result.returncode == 0 else
                           "stopped" if graceful and graceful["returncode"] == 0 else "not_confirmed"),
                "returncode": result.returncode, "message": result.stderr.strip(),
            }
        except (OSError, subprocess.SubprocessError, RuntimeExecutionError, ValidationError) as exc:
            cleanup = {"status": "stopped" if graceful and graceful["returncode"] == 0 else "not_confirmed",
                       "returncode": None, "message": str(exc)}
        cleanup["argv"] = command
        if graceful is not None:
            cleanup["graceful_stop"] = graceful
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
        if self.dry_run:
            raise ValidationError("doctor richiede controlli reali; rimuovere --dry-run.")
        self._backend_ready = False
        if shutil.which(self._transport.executable) is None:
            raise ValidationError(
                f"Comando '{self._transport.executable}' non trovato nel PATH. "
                + self._transport.unavailable_message
            )
        if not self.layout.compose_file.is_file():
            raise ValidationError(f"compose.yaml non trovato: {self.layout.compose_file}")
        self.layout.ensure_storage_dirs()
        self._capture(["docker", "compose", "version"])
        if check_runtime:
            try:
                self._prepare_runtime()
                self._describe_bundled_engine()
                self._write("Contratti scientifici verificati: DNPcall, SNPcall, Contamination, CPI.\n")
            finally:
                self._image_id = None
