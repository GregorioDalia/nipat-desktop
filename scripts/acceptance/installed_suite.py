"""Run the pinned synthetic acceptance suite against an installed Windows client.

This driver is external evidence tooling. It never installs, upgrades or edits
NIPAT and never selects user biological input files.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import time
import traceback
import uuid
import zipfile

BASE_COMMIT = "b54ef493ba7f0539a8786b97874fe946b2d26393"
HARNESS = Path(__file__).resolve().parent
CASE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,89}\Z")
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}\Z")
INFRASTRUCTURE_ERROR = re.compile(
    r"Traceback|ModuleNotFoundError|No module named|FileNotFoundError|"
    r"not recognized as|non . riconosciuto|Runtime WSL.*non disponibile|"
    r"Docker.*(?:not running|non disponibile)|Installazione.*da completare|"
    r"out of memory|OOMKilled|memoria insufficiente|cannot allocate memory", re.I)


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_value(value):
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Report value is not JSON serializable: {type(value).__name__}")


def save_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                   allow_nan=False, default=json_value) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def log_text(path, limit=4 * 1024 * 1024):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit)
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def snapshot(paths):
    return {str(path): digest(path) if path.is_file() else None for path in paths}


def input_snapshot(root):
    files = sorted(root.rglob("*"))
    if any(path.is_symlink() for path in files):
        raise ValueError("Gli input del collaudo non possono contenere collegamenti.")
    return snapshot(path for path in files if path.is_file())


def extract_fixtures(source, destination):
    document = read_json(source)
    if document.get("schema_version") != 1 or document.get("source_commit") != BASE_COMMIT:
        raise ValueError("Identita delle fixture non riconosciuta.")
    files = document.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Fixture mancanti.")
    destination.mkdir(parents=True, exist_ok=False)
    for name, entry in files.items():
        relative = PurePosixPath(name)
        if (relative.is_absolute() or "\\" in name or ":" in name
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or relative.parts[0] not in {"five_modules", "dnp_engine", "snp_engine", "workflow_cpi"}):
            raise ValueError(f"Percorso fixture non valido: {name}")
        content = entry["content"].encode("utf-8")
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise ValueError(f"Checksum fixture non valido: {name}")
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {name: entry["sha256"] for name, entry in files.items()}


def scientific_tables(run):
    result = {}
    for path in sorted((run / "output").rglob("*")):
        relative = path.relative_to(run)
        if (path.is_file() and path.suffix.lower() in {".csv", ".tsv", ".txt"}
                and not {"work", "logs", "presentation"}.intersection(relative.parts)
                and path.name not in {"resources.tsv", "execution.log"}):
            result[relative.as_posix()] = digest(path)
    if not result:
        raise ValueError("Nessuna tabella scientifica disponibile per il confronto.")
    return result


def verify_run(run, image):
    record = read_json(run / "run.json")
    if (record.get("status") != "succeeded" or record.get("engine_verification") != "verified"
            or record.get("runtime", {}).get("image_id") != image
            or not record.get("commands")
            or any(command.get("status") != "succeeded" for command in record["commands"])):
        raise ValueError("Il run non documenta successo e uso dell'immagine installata verificata.")
    return {"run_id": record.get("run_id"), "runtime_image": record["runtime"]["image_id"],
            "workflow": record.get("workflow"), "engine_verification": record["engine_verification"]}


def verify_expected_failure(result, pattern, run, image=None):
    text = log_text(result["stdout"]) + "\n" + log_text(result["stderr"])
    for path in sorted(run.rglob("*.log")):
        if path.is_file() and not path.is_symlink():
            text += "\n" + log_text(path, limit=1024 * 1024)
            if len(text) > 16 * 1024 * 1024:
                raise ValueError("Diagnostica eccessiva: rifiuto atteso non verificabile.")
    if (result.get("timed_out") or result["returncode"] not in {1, 2}
            or not re.search(pattern, text, re.I) or INFRASTRUCTURE_ERROR.search(text)):
        raise ValueError("Il comando non ha rifiutato l'input per il motivo atteso; consultare i log.")
    if (run / "run.json").exists():
        record = read_json(run / "run.json")
        observed_image = record.get("runtime", {}).get("image_id")
        if record.get("status") != "failed" or (image and observed_image and observed_image != image):
            raise ValueError("Il run non documenta un fallimento sull'immagine prevista.")


class SuiteStopped(RuntimeError):
    pass


class Suite:
    def __init__(self, app, session, commit):
        self.app, self.session, self.commit = app.resolve(), session.resolve(), commit
        if self.session.is_relative_to(self.app) or self.app.is_relative_to(self.session):
            raise ValueError("La sessione deve trovarsi fuori dalla cartella dell'applicazione.")
        self.inputs, self.runs, self.logs = (self.session / part for part in ("inputs", "runs", "logs"))
        self.fixtures, self.generated = self.inputs / "fixtures", self.inputs / "generated"
        self.powershell = str(Path(os.environ.get("WINDIR", "C:/Windows")) /
                              "System32/WindowsPowerShell/v1.0/powershell.exe")
        self.environment = {key: value for key, value in os.environ.items()
                            if not key.upper().startswith("NIPAT_") and key.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
        self.report = {"schema_version": 1, "suite": "NIPAT installed synthetic acceptance 0.8.50",
                       "started_utc": utc(), "harness_source_commit": commit,
                       "status": "RUNNING", "app_dir": str(self.app), "session": str(self.session),
                       "scope": "Cinque moduli, oracoli analitici indipendenti e workflow sintetici sul client installato.",
                       "limits": ["Le fixture non sono campioni biologici reali.",
                                  "La parita fra modi verifica la riproducibilita; gli oracoli numerici sono controlli separati.",
                                  "Il collaudo non certifica ogni possibile input o una validazione clinica."],
                       "checks": [], "cases": [], "comparisons": [], "archive_omissions": []}
        self.identity_paths, self.identity_before, self.inputs_before = [], None, None
        self.harness_before = None
        self.image, self.transport, self.current_run = None, None, None
        self.preparation_number = 0
        self.cases = []
        for path in (self.inputs, self.runs, self.logs):
            path.mkdir(parents=True, exist_ok=False)
        self.defaults = self.session / "scientific-defaults.json"
        save_json(self.defaults, {})

    def checkpoint(self):
        save_json(self.session / "report.json", self.report)

    def check(self, name, function, *, fatal=False):
        started = time.monotonic()
        entry = {"id": name, "started_utc": utc(), "status": "PASS"}
        print(f"[CONTROLLO] {name}", flush=True)
        try:
            entry["details"] = function()
        except Exception as exc:
            entry.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
            if fatal:
                raise
        finally:
            entry["seconds"] = round(time.monotonic() - started, 3)
            self.report["checks"].append(entry)
            self.checkpoint()
        return entry["status"] == "PASS"

    def process(self, name, command, *, timeout=900, environment=None):
        stdout, stderr = self.logs / (name + ".stdout.log"), self.logs / (name + ".stderr.log")
        started = time.monotonic()
        result = {"argv": list(map(str, command)), "stdout": str(stdout), "stderr": str(stderr),
                  "started_utc": utc(), "returncode": None, "timed_out": False}
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        with stdout.open("wb") as output, stderr.open("wb") as error:
            process = subprocess.Popen(result["argv"], cwd=self.session, env=environment or self.environment,
                                       stdin=subprocess.DEVNULL, stdout=output, stderr=error, **options)
            try:
                result["returncode"] = process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                result["timed_out"] = isinstance(exc, subprocess.TimeoutExpired)
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
                    process.wait(timeout=20)
                except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                result["returncode"] = process.returncode
                result["seconds"] = round(time.monotonic() - started, 3)
                save_json(self.logs / (name + ".process.json"), result)
                raise SuiteStopped("Tempo massimo superato" if result["timed_out"] else "Collaudo interrotto dall'utente") from exc
        result["seconds"] = round(time.monotonic() - started, 3)
        save_json(self.logs / (name + ".process.json"), result)
        return result

    def command(self, arguments, mode=None):
        flags = ["--data-dir", self.inputs, "--runs-dir", self.runs,
                 "--scientific-config", self.defaults]
        if mode:
            flags += ["--input-hashes", "full",
                      "--execution-mode", "serial" if mode == "serial" else "auto"]
            if mode == "cap2":
                flags += ["--max-workers", "2"]
        return [self.powershell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                self.app / "scripts/windows/run.ps1", *flags, *arguments]

    def probe(self, name, arguments):
        result = self.process(name, self.command(arguments), timeout=240)
        if result["returncode"]:
            diagnostic = (log_text(result["stderr"]).strip() or log_text(result["stdout"]).strip())[-2000:]
            raise ValueError(f"Controllo {name} fallito (codice {result['returncode']}): "
                             f"{diagnostic or 'nessun messaggio restituito'}. Log: {result['stderr']}")
        return result

    def preflight(self):
        if sys.platform != "win32":
            raise ValueError("Questo collaudo va eseguito sul PC Windows con NIPAT installato.")
        if not re.fullmatch(r"[a-f0-9]{40}", self.commit):
            raise ValueError("Commit del collaudo non valido.")
        state = read_json(self.app / ".runtime/installer/state.json")
        manifest = read_json(self.app / ".distribution/installer-manifest.json")
        backend = read_json(self.app / ".runtime/backend.json")
        if (manifest.get("version") != "0.8.50" or manifest.get("source_commit") != BASE_COMMIT
                or state.get("source_commit") != BASE_COMMIT or state.get("phase") != "ready"
                or state.get("installation_channel") != "desktop" or backend.get("backend") != "wsl"
                or backend.get("source_commit") != BASE_COMMIT
                or backend.get("runtime_image") != state.get("resolved_runtime_image")
                or not IMAGE_ID.fullmatch(backend.get("runtime_image", ""))):
            raise ValueError("Attesa installazione ufficiale 0.8.50 pronta, con runtime WSL coerente.")
        self.image = backend["runtime_image"]
        self.report["installation"] = {"version": manifest["version"], "source_commit": BASE_COMMIT,
                                       "build_image": manifest["runtime_image"], "resolved_image": self.image,
                                       "wsl_distro": backend["wsl_distro"], "rootfs_sha256": state.get("rootfs_sha256")}
        self.identity_paths = [self.app / relative for relative in (
            ".distribution/installer-manifest.json", ".distribution/application-files.json",
            ".runtime/installer/state.json", ".runtime/backend.json", ".runtime/install-layout.json",
            "scripts/verify_cpin_update.py", "scripts/windows/run.ps1", "scripts/windows/common.ps1",
            "release.json")]
        self.identity_paths.append(Path(os.environ["LOCALAPPDATA"]) / "NIPAT-Desktop/preferences.json")
        self.identity_before = snapshot(self.identity_paths)
        self.report["installation_file_sha256"] = self.identity_before
        self.report["host"] = {"platform": sys.platform, "python": sys.version,
                               "processor_count": os.cpu_count()}
        self.report["harness_sha256"] = {name: digest(HARNESS / name) for name in
                                         ("installed_suite.py", "installed_models.py", "installed_workflows.py", "fixtures.json")}
        self.harness_before = snapshot([HARNESS / name for name in self.report["harness_sha256"]] + [self.defaults])
        self.environment.update(NIPAT_PROJECT_DIR=str(self.app), NIPAT_BACKEND="wsl",
                                NIPAT_WSL_DISTRO=backend["wsl_distro"], NIPAT_RUNTIME_IMAGE=self.image,
                                NIPAT_DATA_DIR=str(self.inputs), NIPAT_RUNS_DIR=str(self.runs),
                                NIPAT_WORKSPACE_DIR=str(self.session))
        return self.report["installation"]

    def samtools(self, arguments):
        self.preparation_number += 1
        print(f"[PREPARAZIONE {self.preparation_number}] samtools {arguments[0]}", flush=True)
        mapped = []
        for value in map(str, arguments):
            path = Path(value)
            if path.is_absolute():
                resolved = path.resolve()
                if not resolved.is_relative_to(self.inputs):
                    raise ValueError("La preparazione samtools puo accedere solo agli input sintetici della sessione.")
                value = "/inputs/" + resolved.relative_to(self.inputs).as_posix()
            mapped.append(value)
        mount = io.StringIO()
        csv.writer(mount, lineterminator="").writerow(
            ["type=bind", "src=" + self.transport.host_path(self.inputs), "dst=/inputs"])
        name = "nipat-acceptance-" + uuid.uuid4().hex
        command = ["docker", "run", "--rm", "--pull=never", "--name", name, "--network=none", "--read-only",
                   "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m", "--mount", mount.getvalue(),
                   "--entrypoint", "samtools", self.image, *mapped]
        try:
            result = self.process(f"prepare-{self.preparation_number:03d}",
                                  self.transport.command(command, self.environment), timeout=180)
            if result["returncode"]:
                raise ValueError(f"Preparazione samtools fallita; vedere {result['stderr']}")
            return result
        except SuiteStopped:
            cleanup = self.transport.command(["docker", "rm", "--force", name], self.environment)
            self.process(f"prepare-{self.preparation_number:03d}-cleanup", cleanup, timeout=30)
            raise

    def execute_case(self, specification, number, total):
        name = specification["id"]
        entry = {"id": name, "category": specification["category"], "mode": specification.get("mode", "serial"),
                 "status": "FAIL", "started_utc": utc(), "run_dir": str(self.runs / name),
                 "expected_failure": bool(specification.get("expect_failure"))}
        run = self.runs / name
        self.current_run = run
        print(f"[{number}/{total}] {name} ({entry['mode']})", flush=True)
        try:
            result = self.process(name, self.command([*specification["args"], "--run-name", name], entry["mode"]))
            entry["process"] = result
            if specification.get("expect_failure"):
                verify_expected_failure(result, specification["expect_failure"], run, self.image)
                entry["details"] = {"rejection": "motivo atteso, nessun run dichiarato riuscito"}
            else:
                if result["returncode"]:
                    raise ValueError(f"NIPAT ha restituito il codice {result['returncode']}; consultare stdout/stderr.")
                entry["execution"] = verify_run(run, self.image)
                entry["details"] = specification["validate"](run)
                if specification.get("compare_group"):
                    entry["compare_group"] = specification["compare_group"]
                    entry["scientific_tables"] = scientific_tables(run)
            entry["status"] = "PASS"
        except SuiteStopped as exc:
            entry.update(status="INTERRUPTED", error=str(exc))
            raise
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            (self.logs / (name + ".validation.log")).write_text(traceback.format_exc(), encoding="utf-8")
        finally:
            self.report["cases"].append(entry)
            self.checkpoint()
            print(f"  {entry['status']}: {entry.get('error', name)}", flush=True)
        self.current_run = None

    def compare(self):
        for group in sorted({case["compare_group"] for case in self.cases if case.get("compare_group")}):
            requested = {case["id"] for case in self.cases if case.get("compare_group") == group}
            observed = [case for case in self.report["cases"] if case["id"] in requested]
            entry = {"id": group, "cases": sorted(requested), "status": "BLOCKED"}
            if len(observed) == len(requested) and len(observed) > 1 and all(case["status"] == "PASS" for case in observed):
                baseline = observed[0]["scientific_tables"]
                entry["status"] = "PASS" if all(case["scientific_tables"] == baseline for case in observed[1:]) else "FAIL"
                entry["tables"] = len(baseline)
                if entry["status"] == "FAIL":
                    entry["error"] = "Le tabelle scientifiche differiscono fra modalita di esecuzione."
            self.report["comparisons"].append(entry)

    def integrity(self):
        if self.inputs_before is not None:
            self.check("input-originali-invariati", lambda: self.require_snapshot(self.inputs_before, input_snapshot(self.inputs)))
        if self.identity_before is not None:
            self.check("installazione-e-preferenze-invariate", lambda: self.require_snapshot(self.identity_before, snapshot(self.identity_paths)))
        if self.harness_before is not None:
            self.check("codice-collaudo-invariato", lambda: self.require_snapshot(self.harness_before, snapshot(map(Path, self.harness_before))))

    @staticmethod
    def require_snapshot(before, after):
        changes = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
        if changes:
            raise ValueError("File modificati, aggiunti o rimossi: " + "; ".join(changes[:20]))
        return {"verified_files": len(before)}

    def finish(self):
        self.compare()
        self.integrity()
        observed = self.report["checks"] + self.report["cases"] + self.report["comparisons"]
        counts = {status: sum(item["status"] == status for item in observed)
                  for status in ("PASS", "FAIL", "BLOCKED", "INTERRUPTED")}
        self.report.update(finished_utc=utc(), summary=counts,
                           status="PASS" if self.report["cases"] and all(item["status"] == "PASS" for item in observed) else "FAIL")
        self.checkpoint()
        self.write_html()
        self.archive()
        print(f"\nESITO: {self.report['status']} — PASS {counts['PASS']}, FAIL {counts['FAIL']}, "
              f"BLOCCATI {counts['BLOCKED']}, INTERROTTI {counts['INTERRUPTED']}", flush=True)
        print(f"Rapporto: {self.session / 'report.html'}\nZIP da condividere: {self.session / 'report.zip'}", flush=True)

    def write_html(self):
        escape = lambda value: html.escape(str(value))
        rows = []
        for kind, entries in (("Controllo", self.report["checks"]), ("Analisi", self.report["cases"]),
                              ("Riproducibilita", self.report["comparisons"])):
            for entry in entries:
                rows.append("<tr><td>" + escape(kind) + "</td><td>" + escape(entry["id"]) +
                            "</td><td class='" + escape(entry["status"]) + "'>" + escape(entry["status"]) +
                            "</td><td>" + escape(entry.get("error", entry.get("mode", ""))) + "</td></tr>")
        document = """<!doctype html><html lang="it"><meta charset="utf-8"><title>Collaudo NIPAT 0.8.50</title>
<style>body{font:16px system-ui,sans-serif;max-width:1200px;margin:40px auto;padding:0 24px;color:#24313b;background:#f7f8fa}h1{font-size:28px}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;text-align:left;border-bottom:1px solid #ddd;vertical-align:top;overflow-wrap:anywhere}.PASS{color:#187448}.FAIL,.INTERRUPTED{color:#b42318}.BLOCKED{color:#875700}code{overflow-wrap:anywhere}p{line-height:1.55}</style>
<h1>Collaudo NIPAT 0.8.50</h1>"""
        document += f"<p><strong>Esito: {escape(self.report['status'])}</strong> — {escape(self.report.get('summary', {}))}</p>"
        document += "<p>" + escape(self.report["scope"]) + "</p>"
        document += "<p>" + " ".join(escape(item) for item in self.report["limits"]) + "</p>"
        if self.report["archive_omissions"]:
            document += "<p><strong>File esclusi dallo ZIP per limiti di dimensione o collegamenti: " + str(len(self.report["archive_omissions"])) + ".</strong> Elenco in report.json; i risultati locali restano disponibili.</p>"
        document += "<p>Codice collaudo: <code>" + escape(self.commit) + "</code><br>Installazione: <code>" + escape(self.report.get("installation", {})) + "</code></p>"
        document += "<table><thead><tr><th>Tipo</th><th>Prova</th><th>Esito</th><th>Dettaglio</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        document += "<p>Comandi, durate, hash e log sono in report.json e nelle cartelle logs/runs. Lo ZIP contiene esclusivamente questa sessione sintetica.</p></html>"
        temporary = self.session / "report.html.tmp"
        temporary.write_text(document, encoding="utf-8")
        os.replace(temporary, self.session / "report.html")

    def archive(self):
        selected, omissions, total = [], [], 0
        for path in sorted(self.session.rglob("*")):
            if not path.is_file() or path.name in {"report.zip", "report.zip.tmp", "report.json", "report.html"} or path.suffix == ".tmp":
                continue
            relative = path.relative_to(self.session).as_posix()
            size = path.stat().st_size
            if path.is_symlink() or not path.resolve().is_relative_to(self.session) or size > 32 * 1024 * 1024 or total + size > 256 * 1024 * 1024:
                omissions.append({"path": relative, "bytes": size, "reason": "link_or_size_limit"})
                continue
            selected.append((path, relative))
            total += size
        self.report["archive_omissions"] = omissions
        self.checkpoint()
        self.write_html()
        temporary = self.session / "report.zip.tmp"
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, relative in selected:
                archive.write(path, relative)
            for name in ("report.json", "report.html"):
                archive.write(self.session / name, name)
        os.replace(temporary, self.session / "report.zip")

    def run(self):
        sys.path.insert(0, str(HARNESS))
        lease = contextlib.ExitStack()
        previous_environment = dict(os.environ)
        try:
            self.check("identita-installazione", self.preflight, fatal=True)
            sys.path.insert(0, str(self.app / "src"))
            import nipat
            from nipat.activity import activity_session
            from nipat.execution.transport import DockerTransport
            if not Path(nipat.__file__).resolve().is_relative_to(self.app / "src"):
                raise ValueError("Il client importato non appartiene all'installazione selezionata.")
            os.environ.clear()
            os.environ.update(self.environment)
            lease.enter_context(activity_session(project_dir=self.app))
            self.transport = DockerTransport.from_environment()
            self.check("ambiente-scientifico", lambda: self.probe("doctor", ["doctor", "--runtime"]), fatal=True)
            self.check("parametri-scientifici", lambda: self.probe("settings", ["settings", "--json"]), fatal=True)
            self.check("risorse-disponibili", lambda: self.probe("resources", ["resources", "inspect", "--json"]))
            self.report["fixture_sha256"] = extract_fixtures(HARNESS / "fixtures.json", self.fixtures)
            self.generated.mkdir()
            import installed_models
            import installed_workflows
            self.cases.extend(installed_models.build_cases(self.fixtures, self.generated))
            try:
                metadata = installed_workflows.prepare_inputs(self.fixtures, self.generated, self.samtools)
                self.cases.extend(installed_workflows.build_cases(self.fixtures, self.generated, metadata))
            except SuiteStopped:
                raise
            except Exception as exc:
                self.report["checks"].append({"id": "preparazione-workflow", "status": "BLOCKED", "error": str(exc)})
                (self.logs / "workflow-preparation.log").write_text(traceback.format_exc(), encoding="utf-8")
            names = [case["id"] for case in self.cases]
            if len(names) != len(set(names)) or any(not CASE_ID.fullmatch(name) for name in names):
                raise ValueError("Identificatori delle prove non validi o duplicati.")
            self.inputs_before = input_snapshot(self.inputs)
            self.report["input_sha256_before"] = self.inputs_before
            self.report["planned_cases"] = names
            for number, specification in enumerate(self.cases, 1):
                self.execute_case(specification, number, len(self.cases))
        except (Exception, KeyboardInterrupt) as exc:
            self.report["checks"].append({"id": "completamento-collaudo", "status": "INTERRUPTED" if isinstance(exc, (KeyboardInterrupt, SuiteStopped)) else "FAIL", "error": f"{type(exc).__name__}: {exc}"})
            (self.logs / "suite-error.log").write_text(traceback.format_exc(), encoding="utf-8")
            completed = {case["id"] for case in self.report["cases"]}
            for case in self.cases:
                if case["id"] not in completed:
                    self.report["cases"].append({"id": case["id"], "category": case["category"], "status": "BLOCKED", "error": "Prerequisito non disponibile o collaudo interrotto."})
            if self.current_run and (self.current_run / "run.json").exists():
                self.check("arresto-run-del-collaudo", lambda: self.probe("stop-owned-run", ["runs", "stop", "--run", self.current_run, "--yes", "--json"]))
        finally:
            try:
                self.finish()
            finally:
                lease.close()
                os.environ.clear()
                os.environ.update(previous_environment)
        return 0 if self.report["status"] == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--harness-source-commit", required=True)
    args = parser.parse_args(argv)
    return Suite(args.app_dir, args.session, args.harness_source_commit).run()


if __name__ == "__main__":
    raise SystemExit(main())
