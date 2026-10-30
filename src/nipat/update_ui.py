"""Explicit update discovery, verified download and installer handoff for the CLI."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable

from nipat import __version__
from nipat.distribution import EXPERIMENT_URL, is_experimental_version
from nipat.errors import NipatError
from nipat.paths import ProjectLayout
from nipat.preferences import Preferences
from nipat.terminal import Terminal
from nipat.updates import UpdateClient, detect_platform
from nipat.update_handoff import HANDOFF_EXIT_CODE


def _size(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MiB"


class DownloadProgress:
    """Throttle progress output in both ordinary and interactive terminals."""

    def __init__(self, ui: Terminal, *, clock: Callable[[], float] = time.monotonic):
        self.ui = ui
        self.clock = clock
        self.last_time: float | None = None
        self.last_received = -1

    def __call__(self, received: int, total: int) -> None:
        now = self.clock()
        if received == self.last_received:
            return
        if (self.last_time is not None and received < total
                and now - self.last_time < 1.0):
            return
        self.last_time, self.last_received = now, received
        percent = min(100, int(received * 100 / total)) if total else 0
        self.ui.message(f"Download: {percent}%  ({_size(received)} / {_size(total)})", kind="muted")


def _confirm(ui: Terminal, title: str, label: str, description: str) -> bool:
    while True:
        action = ui.menu(title, [
            ("1", label, description),
            ("0", "Piu' tardi", "Torna al menu principale"),
        ], default="0")
        if action in {"0", ":indietro", ":annulla"}:
            return False
        if action == "1":
            return True
        ui.message("Scegliere 1 per procedere oppure 0 per tornare al menu. Invio mantiene Piu' tardi.", kind="muted")


def run_updates(
    ui: Terminal,
    layout: ProjectLayout,
    preferences: Preferences,
    *,
    dry_run: bool = False,
    startup: bool = False,
    client: Any = None,
    platform: str | None = None,
    download_directory: Path | None = None,
    handoff: Callable[[Any, Path, Path], Any] | None = None,
    current_version: str = __version__,
) -> bool:
    """Return True only when a confirmed installer handoff requires the CLI to close.

    Startup checks never prompt, download or launch an installer. Update failures
    are local to this feature: the installed application's analyses remain usable.
    Dependencies can be supplied by tests without network or process side effects.
    """
    if dry_run:
        if not startup:
            ui.heading("Verifica aggiornamenti")
            ui.message("Modalita' simulazione (--dry-run): nessuna connessione, download o installazione viene eseguita.", kind="muted")
        return False
    if is_experimental_version(current_version):
        if not startup:
            ui.heading("Aggiornamenti dell'esperimento 0.8")
            ui.message(f"Versione installata: NIPAT {current_version}")
            ui.message("Questa installazione sperimentale e' separata dalla versione stabile. "
                       "Gli aggiornamenti automatici sono disabilitati per evitare il cambio di distribuzione.")
            ui.message("I nuovi installer sperimentali saranno disponibili su GitHub: " + EXPERIMENT_URL,
                       kind="muted")
        return False
    handoff_started = False
    try:
        if startup:
            ui.message("Verifica aggiornamenti all'avvio in corso...", kind="muted")
        else:
            ui.heading("Verifica aggiornamenti")
            ui.message(f"Versione installata: NIPAT {current_version}")
            ui.message("Canale selezionato: " + ("Testing" if preferences.update_channel == "testing" else "Stabile"))
            ui.message("Consultazione delle release pubblicate su GitHub in corso...", kind="muted")
        selected_platform = platform or detect_platform()
        update_client = client if client is not None else UpdateClient()
        result = update_client.check(current_version, preferences.update_channel, selected_platform)
        if result.status != "available" or result.offer is None:
            if not startup or result.status not in {"up_to_date", "no_eligible_release"}:
                ui.message(result.message, kind="warning" if result.status in {
                    "offline", "rate_limited", "invalid_metadata", "unsupported_updater", "incomplete"
                } else "info")
            if not startup and result.status not in {"up_to_date", "no_eligible_release"}:
                ui.message("E' possibile continuare a usare la versione installata e riprovare la verifica in seguito.", kind="muted")
            return False
        offer = result.offer
        ui.message(f"Disponibile NIPAT {offer.version}.", kind="success")
        ui.message("Tipo di release: " + ("stabile" if offer.channel == "stable" else "testing"), kind="muted")
        ui.message(f"Note della release: {offer.release_notes_url}", kind="muted")
        if startup:
            ui.message("Per scaricare e installare scegliere 9 - Verifica aggiornamenti. Nessun download e' stato avviato.", kind="muted")
            return False
        ui.message(f"File: {offer.asset.name}  |  Dimensione: {_size(offer.asset.size)}")
        ui.message("Il download viene verificato prima di proporre l'installazione. L'applicazione non cambia durante questa fase.", kind="muted")
        if not _confirm(ui, "Scaricare l'aggiornamento?", "Scarica aggiornamento", "Verifica dimensione e SHA-256 del file"):
            return False
        if download_directory is None:
            from nipat.update_handoff import update_cache_directory
            download_directory = update_cache_directory(layout.project_dir)
        ui.message("Download in corso. Ctrl+C interrompe il download e torna al menu.", kind="muted")
        downloaded = update_client.download(
            offer, download_directory / offer.version, progress=DownloadProgress(ui),
        )
        ui.message(f"Download verificato: {downloaded}", kind="success")
        ui.message("Per installare, NIPAT chiudera' questa sessione e avviera' il programma di aggiornamento.", kind="muted")
        if selected_platform.startswith("linux"):
            ui.message("Il gestore dei pacchetti di Ubuntu puo' richiedere l'autorizzazione di amministrazione.", kind="muted")
        if not _confirm(ui, "Installare l'aggiornamento?", "Installa l'aggiornamento", "Chiude questa sessione e apre il programma di installazione"):
            ui.message("Il file verificato resta disponibile nella cache; la versione installata non e' stata modificata.", kind="muted")
            return False
        if handoff is None:
            from nipat.update_handoff import begin_update
            handoff = begin_update
        if not handoff(offer, downloaded, layout.project_dir):
            ui.message("Installazione non avviata. Il file verificato resta nella cache; la sessione NIPAT rimane aperta.", kind="warning")
            return False
        handoff_started = True
        ui.message("Aggiornamento affidato al programma di installazione. Chiusura della sessione NIPAT in corso.", kind="success")
        return True
    except (KeyboardInterrupt, EOFError):
        if handoff_started:
            # Installation has been explicitly confirmed and its helper is armed.
            # Closing the CLI is mandatory even if its final output is interrupted.
            return True
        ui.message("Operazione di aggiornamento annullata. La versione installata resta disponibile.", kind="muted")
        return False
    except (NipatError, OSError, ValueError) as exc:
        if handoff_started:
            return True
        ui.message(f"Aggiornamento non completato: {exc}", kind="warning")
        ui.message("La sessione resta aperta. E' possibile continuare le analisi o riprovare la verifica in seguito.", kind="muted")
        return False
