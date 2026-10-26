"""Explicit installed-runtime maintenance, separate from scientific analyses."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from nipat.activity import _safe_parent
from nipat.errors import NipatError

MAX_INVENTORY_BYTES = 2 * 1024 * 1024


def _command(project: Path, operation: str) -> list[str]:
    if sys.platform != "win32":
        raise NipatError("La manutenzione dell'ambiente dedicato e' disponibile nell'installazione Windows.")
    project = project.absolute()
    _safe_parent(project)
    worker = project / "installer" / "windows" / "maintenance.ps1"
    _safe_parent(worker)
    if not worker.is_file():
        raise NipatError("Componente di manutenzione mancante. Reinstallare il pacchetto NIPAT verificato.")
    powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return [str(powershell), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(worker), "-Project", str(project), "-Operation", operation]


def installation_inventory(project: Path) -> dict:
    if sys.platform != "win32":
        return {"schema_version": 1, "platform": "linux", "runtimes": [], "cache": [],
                "backups": [], "recovery": {"id": "current-installation", "recoverable": False,
                "reason": "L'applicazione Ubuntu e' gestita da APT. Questa schermata non rimuove immagini o risorse Docker."},
                "warnings": []}
    try:
        result = subprocess.run(_command(project, "inventory"), capture_output=True,
                                check=False, timeout=180)
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise NipatError("Inventario di installazione non disponibile: " + detail[:2000])
        if len(result.stdout) > MAX_INVENTORY_BYTES:
            raise NipatError("Inventario troppo grande: consultare i log di installazione.")
        value = json.loads(result.stdout.decode("utf-8-sig"))
        if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
                or value["schema_version"] != 1 or value.get("platform") != "windows"
                or any(not isinstance(value.get(key), list) for key in ("runtimes", "cache", "backups", "warnings"))
                or not isinstance(value.get("recovery"), dict)):
            raise ValueError("formato non valido")
        for group in ("runtimes", "cache"):
            for item in value[group]:
                if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                        or not item["id"] or type(item.get("removable")) is not bool
                        or not isinstance(item.get("name"), str)
                        or not isinstance(item.get("path"), str)
                        or type(item.get("size_bytes")) is not int or item["size_bytes"] < 0):
                    raise ValueError("elemento dell'inventario non valido")
        return value
    except (OSError, subprocess.SubprocessError, ValueError, RecursionError) as exc:
        raise NipatError(f"Impossibile leggere l'inventario di installazione: {exc}") from exc


def maintenance_selection(inventory: dict, operation: str, target: str) -> dict:
    if operation == "recover":
        record = inventory.get("recovery", {})
        if target == "current-installation" and record.get("id") == target and record.get("recoverable") is True:
            return record
    elif operation == "cleanup":
        matches = [item for group in ("runtimes", "cache") for item in inventory.get(group, [])
                   if item.get("id") == target]
        if len(matches) == 1 and matches[0].get("removable") is True:
            return matches[0]
    raise NipatError("Operazione non disponibile per l'elemento selezionato. Nessun componente e' stato modificato.")


def start_maintenance(project: Path, operation: str, target: str) -> Path:
    """Recheck a selected operation, acknowledge its worker, then let the CLI exit.

    The worker waits for this process and the installation lease before changing
    anything. Its final result is recorded separately; acknowledgement is not a
    successful cleanup or repair.
    """
    command = _command(project, operation)
    maintenance_selection(installation_inventory(project), operation, target)
    directory = project / ".runtime" / "maintenance" / uuid.uuid4().hex
    _safe_parent(directory)
    directory.mkdir(parents=True, exist_ok=False)
    _safe_parent(directory)
    ready = directory / "ready.json"
    command.extend(["-TargetId", target, "-WaitForProcessId", str(os.getpid()),
                    "-ReadyFile", str(ready)])
    process = None
    acknowledged = False
    try:
        process = subprocess.Popen(command, shell=False, cwd=str(project), close_fds=True,
                                   creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise NipatError("Il componente di manutenzione si e' chiuso prima del passaggio. NIPAT resta aperto.")
            if ready.is_file():
                _safe_parent(ready)
                with ready.open("rb") as stream:
                    content = stream.read(16385)
                if len(content) > 16384:
                    raise NipatError("Conferma di manutenzione non valida.")
                value = json.loads(content.decode("utf-8-sig"))
                if value != {"schema_version": 1, "status": "waiting-for-client",
                             "operation": operation, "target_id": target}:
                    raise NipatError("Conferma di manutenzione non valida.")
                acknowledged = True
                return directory / "result.json"
            time.sleep(0.05)
        raise NipatError("Il componente di manutenzione non ha confermato l'avvio. NIPAT resta aperto.")
    except (OSError, ValueError, RecursionError) as exc:
        raise NipatError(f"Passaggio alla manutenzione non riuscito: {exc}") from exc
    finally:
        if process is not None and not acknowledged and process.poll() is None:
            # The worker is still waiting for this live client. Cancel that
            # waiting worker before returning to the menu.
            marker = directory / "cancelled.json"
            marker_written = False
            try:
                marker.write_text('{"cancelled":true}\n', encoding="utf-8")
                marker_written = True
            except OSError:
                # Disk errors must not skip terminating the waiting worker.
                pass
            try:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            except (OSError, subprocess.SubprocessError) as exc:
                detail = ("Il componente ha ricevuto il segnale di annullamento."
                          if marker_written else "Non e' stato possibile registrare l'annullamento.")
                raise NipatError("Arresto della finestra di manutenzione non confermato; "
                                 "chiuderla prima di uscire da NIPAT. " + detail) from exc


def inventory_lines(inventory: dict) -> list[str]:
    lines = ["Installazione e spazio"]
    if inventory.get("platform") != "windows":
        return lines + [str(inventory["recovery"]["reason"])]
    lines.append("L'ambiente attivo e il precedente piu' recente sono conservati. Dati, risultati e risorse estranee non vengono rimossi.")
    for group, title in (("runtimes", "Ambienti WSL"), ("cache", "Archivi in cache")):
        lines.append(title + ":")
        for item in inventory[group]:
            lines.append(f"  {item['name']}: {item['size_bytes'] / (1024 ** 3):.2f} GiB; {item.get('reason', '')}")
            lines.append(f"    ID: {item['id']}")
            lines.append(f"    {item['path']}")
    lines.append("Ripara/riprendi preparazione: " + str(inventory["recovery"].get("reason", "")))
    for warning in inventory.get("warnings", []):
        lines.append("Avviso: " + str(warning))
    return lines


def show_installation(ui, project: Path, *, dry_run: bool = False) -> bool:
    from nipat.errors import Cancelled

    ui.heading("Installazione e spazio")
    if dry_run:
        ui.message("In modalita' dry-run non vengono interrogati o modificati i componenti installati.", kind="muted")
        return False
    ui.message("Lettura e verifica dei componenti installati; gli archivi grandi possono richiedere tempo.", kind="muted")
    inventory = installation_inventory(project)
    for line in inventory_lines(inventory):
        ui.message(line)
    selectable = [("cleanup", item) for group in ("runtimes", "cache") for item in inventory[group]
                  if item.get("removable") is True]
    recovery = inventory.get("recovery", {})
    if recovery.get("recoverable") is True:
        selectable.append(("recover", recovery))
    if not selectable:
        return False
    while True:
        action = ui.menu("Manutenzione dell'installazione", [
            (str(index + 1), "Rimuovi " + item["name"] if operation == "cleanup" else "Ripara/riprendi preparazione",
             item.get("reason", "")) for index, (operation, item) in enumerate(selectable)
        ] + [("0", "Torna alla guida", "Nessuna modifica")], default="0").strip().casefold()
        if action == ":annulla":
            raise Cancelled
        if action in {"0", ":indietro"}:
            return False
        entry = {str(index + 1): value for index, value in enumerate(selectable)}.get(action)
        if entry is None:
            continue
        operation, selected = entry
        ui.message(selected.get("path", selected["id"]))
        ui.message("La sessione NIPAT sara' chiusa. La manutenzione parte in una finestra separata dopo la chiusura e ripete i controlli di proprieta'.", kind="warning")
        confirm = ui.menu("Confermare la manutenzione selezionata?", [
            ("1", "Conferma e chiudi NIPAT", "Attendere il resoconto nella finestra di manutenzione"),
            ("0", "Annulla", "NIPAT resta aperto"),
        ], default="0").strip().casefold()
        if confirm == ":annulla":
            raise Cancelled
        if confirm != "1":
            continue
        report = start_maintenance(project, operation, selected["id"])
        ui.message(f"Passaggio alla manutenzione confermato. Esito finale: {report}")
        return True
