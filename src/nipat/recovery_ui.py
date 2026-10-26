"""Read-only run inspection and explicitly confirmed container recovery."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from nipat.errors import Cancelled
from nipat.i18n import translate


def recovery_lines(report: dict[str, Any], *, language: str = "it") -> list[str]:
    def word(value: object) -> str:
        return translate("yes" if value is True else "no", language)

    lines = [
        translate("run_name", language, name=report.get("run_name", report.get("run_dir", ""))),
        translate("recorded_status", language, status=report.get("recorded_status", "unknown")),
        translate("backend_match", language, matches=word(report.get("backend_matches"))),
    ]
    if report.get("error"):
        lines.append(translate("recovery_error", language, error=report["error"]))
    containers = report.get("containers", [])
    if not containers:
        lines.append(translate("no_containers", language))
    for item in containers:
        lines.append(translate("container_status", language,
                               name=item.get("container_name", ""),
                               state=item.get("state", "unknown"), owned=word(item.get("owned"))))
        if item.get("error"):
            lines.append(translate("recovery_error", language, error=item["error"]))
        if item.get("cleanup"):
            # Preserve the runtime's diagnostic keys rather than reinterpreting
            # an unconfirmed stop as success in the presentation layer.
            lines.append(str(item["cleanup"]))
    return lines


def show_incomplete_runs(ui, runner, *, dry_run: bool = False) -> None:
    ui.heading(translate("recovery_title"))
    ui.message(translate("recovery_help"), kind="muted")
    if dry_run:
        ui.message("In modalita' dry-run non viene interrogato o arrestato il runtime.", kind="muted")
        return
    while True:
        reports = runner.incomplete_runs()
        if not reports:
            ui.message(translate("no_incomplete_runs"))
            return
        choices = [(str(index + 1), report.get("run_name", "Esecuzione"),
                    str(report.get("recorded_status", "unknown")))
                   for index, report in enumerate(reports)]
        action = ui.menu("Selezionare un'esecuzione da controllare", choices + [
            ("0", "Torna alla guida", ""),
        ], default="0").strip().casefold()
        if action in {"0", ":indietro"}:
            return
        if action == ":annulla":
            raise Cancelled
        selected = {str(index + 1): report for index, report in enumerate(reports)}.get(action)
        if selected is None:
            continue
        for line in recovery_lines(selected):
            ui.message(line)
        stoppable = selected.get("backend_matches") is True and any(
            item.get("owned") is True and item.get("state") in {"running", "restarting", "paused"}
            for item in selected.get("containers", [])
        )
        if not stoppable:
            ui.message("Nessun container attivo con proprieta' verificata da arrestare.", kind="muted")
            continue
        stop = ui.menu("Arrestare questa esecuzione?", [
            ("1", "Arresta i container verificati", "Conserva risultati e log; non riprende il calcolo"),
            ("0", "Indietro", "Non invia richieste di arresto"),
        ], default="0").strip().casefold()
        if stop == ":annulla":
            raise Cancelled
        if stop == "1":
            result = runner.reconcile_run(Path(selected["run_dir"]), stop=True)
            for line in recovery_lines(result):
                ui.message(line)
            ui.message(translate("stop_requested"))
