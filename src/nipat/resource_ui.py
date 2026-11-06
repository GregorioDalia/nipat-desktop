"""Explain host, virtual-machine and container resources in the guided client."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from nipat.errors import NipatError
from nipat.execution.options import ExecutionOptions
from nipat.wizard_forms import Back, Cancelled, navigation


def memory_label(value: object) -> str:
    if type(value) not in (int, float):
        return "Non rilevata"
    gib = f"{value / 1024:.2f}".rstrip("0").rstrip(".")
    return f"{gib} GiB ({value:g} MiB)"


def _configured_label(value: object, *, memory: bool) -> str:
    if type(value) not in (int, float) or value <= 0:
        return "nessun valore esplicito rilevato"
    return memory_label(value) if memory else str(value)


def resource_lines(snapshot: dict) -> list[str]:
    host = snapshot.get("host", {})
    runtime = snapshot.get("runtime", {})
    configured = runtime.get("configured", {})
    effective = runtime.get("effective", {})
    container = snapshot.get("container", {})
    backend = snapshot.get("backend")
    name = {"lima": "Ambiente NIPAT (Lima)", "wsl": "Ambiente Windows WSL2",
            "native": "Linux nativo"}.get(backend, "Ambiente di calcolo")
    lines = [f"Computer: RAM {memory_label(host.get('memory_mib'))}; CPU {host.get('cpus') or 'non rilevate'}."]
    if backend != "native":
        lines.append(f"{name}, configurazione salvata: RAM {_configured_label(configured.get('memory_mib'), memory=True)}; "
                     f"CPU {_configured_label(configured.get('cpus'), memory=False)}.")
    lines.append(f"{name}, risorse effettive attuali: RAM {memory_label(effective.get('memory_mib'))}; "
                 f"CPU {effective.get('cpus') or 'non rilevate'}.")
    memory = container.get("memory_mib")
    cpus = container.get("cpus")
    lines.append("Limite per l'analisi NIPAT: RAM " +
                 (memory_label(memory) if memory is not None else "nessun limite aggiuntivo") +
                 f"; quota CPU {cpus if cpus is not None else 'nessun limite aggiuntivo'}.")
    lines.append("Il limite dell'analisi non aumenta le risorse della macchina virtuale o del computer.")
    if backend == "wsl":
        lines.append("RAM e CPU di WSL2 sono condivise fra tutte le distribuzioni dell'utente, anche quelle usate fuori da NIPAT.")
    elif backend == "native":
        lines.append("Ubuntu nativo usa direttamente le risorse del computer; NIPAT configura soltanto i limiti delle proprie analisi.")
    if runtime.get("running") is False:
        lines.append("L'ambiente è fermo: le risorse effettive saranno verificabili quando sarà avviato.")
    for warning in snapshot.get("warnings", []):
        if backend == "wsl" and warning == "RAM e CPU della VM WSL sono condivise da tutte le distribuzioni WSL2 dell'utente.":
            continue  # Already explained above, including non-NIPAT distributions.
        lines.append(str(warning))
    return lines


def _menu(ui, title, choices, *, default="0") -> str:
    answer = ui.menu(title, choices, default=default).strip().casefold()
    if answer == ":annulla":
        raise Cancelled
    return answer


def _number(ui, label: str, current: int | None, suggested: int | None, *,
            memory: bool, allow_unchanged: bool = True) -> int | None:
    default = (format(Decimal(current) / 1024, "f") if memory else str(current)) if current else (
        "mantieni" if allow_unchanged else "")
    while True:
        answer = navigation(ui.prompt(label, default=default)).strip()
        if allow_unchanged and answer.casefold() in {"", "mantieni", ":mantieni"}:
            return current
        if answer.casefold() == ":suggerito":
            if suggested is not None:
                return suggested
            ui.message("Suggerimento non disponibile: inserire un valore esplicito oppure tornare indietro.", kind="error")
            continue
        try:
            value = Decimal(answer)
            converted = value * 1024 if memory else value
            if not converted.is_finite() or converted != converted.to_integral_value() or converted <= 0:
                raise ValueError
            return int(converted)
        except (InvalidOperation, ValueError, OverflowError):
            ui.message("Inserire un numero positivo" + (" di GiB (esempio: 8)." if memory else " intero di CPU (esempio: 4)."), kind="error")


def configure_resources(ui, layout, options: ExecutionOptions, *, manager=None) -> None:
    """Read-only until the user approves the exact preview and any restart."""
    if manager is None:
        from nipat.resources import ResourceManager
        manager = ResourceManager.from_environment(layout)
    while True:
        snapshot = manager.snapshot(options)
        ui.heading("Configura / Risorse dell'ambiente di calcolo")
        for line in resource_lines(snapshot):
            ui.message(line)
        choices = [("1", "Aggiorna le informazioni", "Non avvia né arresta analisi")]
        if snapshot.get("backend") in {"lima", "wsl"}:
            choices.append(("2", "Modifica RAM e CPU dell'ambiente", "Anteprima e conferma prima di applicare"))
        choices.append(("0", "Indietro", "Torna ai limiti delle analisi"))
        action = _menu(ui, "Risorse", choices)
        if action in {"0", ":indietro"}:
            return
        if action == "1":
            continue
        if action != "2" or snapshot.get("backend") not in {"lima", "wsl"}:
            continue
        configured = snapshot.get("runtime", {}).get("configured", {})
        suggested = snapshot.get("suggested", {})
        ui.message("Invio mantiene la configurazione attuale del campo, anche quando è automatica. Le risorse effettive misurate non vengono trasformate automaticamente in limiti fissi.", kind="muted")
        ui.message("Suggerimento facoltativo: RAM " + memory_label(suggested.get("memory_mib")) +
                   f"; CPU {suggested.get('cpus') or 'non disponibili'}. Non è il valore attuale né una stima del fabbisogno dell'analisi.", kind="muted")
        ui.message("Inserire un nuovo valore oppure :suggerito per usare il suggerimento del campo. :indietro torna al riepilogo; :annulla torna al menu principale.", kind="muted")
        try:
            memory, cpu = configured.get("memory_mib"), configured.get("cpus")
            memory_mib = _number(ui, "Nuova RAM dell'ambiente (GiB)", memory,
                                 suggested.get("memory_mib"), memory=True)
            cpus = _number(ui, "Nuovo numero di CPU dell'ambiente", cpu,
                           suggested.get("cpus"), memory=False)
            if memory_mib == memory and cpus == cpu:
                ui.message("Configurazione invariata: nessun limite salvato e nessun riavvio eseguito.")
                continue
            if memory_mib is None or cpus is None:
                ui.message("Per salvare nuovi limiti occorre indicare sia RAM sia CPU. Il campo senza un valore esplicito non viene ricavato dalle risorse effettive.", kind="muted")
                if memory_mib is None:
                    memory_mib = _number(ui, "Nuova RAM dell'ambiente (GiB)", None,
                                         suggested.get("memory_mib"), memory=True, allow_unchanged=False)
                if cpus is None:
                    cpus = _number(ui, "Nuovo numero di CPU dell'ambiente", None,
                                   suggested.get("cpus"), memory=False, allow_unchanged=False)
            change = manager.preview(memory_mib=memory_mib, cpus=cpus)
            proposal = change.as_dict()
            ui.heading("Anteprima della modifica")
            before, after = proposal.get("before", {}), proposal["after"]
            ui.message(f"RAM configurata: {_configured_label(before.get('memory_mib'), memory=True)} → {memory_label(after['memory_mib'])}")
            ui.message(f"CPU configurate: {_configured_label(before.get('cpus'), memory=False)} → {after['cpus']}")
            ui.message(f"Configurazione: {proposal['config_path']}")
            for warning in proposal.get("warnings", []):
                ui.message(str(warning), kind="warning")
            affected = proposal.get("affected_running", [])
            if affected:
                ui.message("Ambienti attualmente attivi: " + ", ".join(str(item) for item in affected))
            ui.message("La configurazione precedente viene conservata in un backup. Le impostazioni estranee a RAM e CPU vengono preservate.", kind="muted")
            approved = _menu(ui, "Applicare questa configurazione?", [
                ("1", "Conferma la modifica", "Conserva un backup della configurazione precedente"),
                ("0", "Annulla", "Nessuna modifica"),
            ])
            if approved != "1":
                continue
            backend = proposal["backend"]
            restart = False
            if affected:
                ui.message("Il riavvio interrompe gli ambienti indicati: terminare prima gli altri lavori aperti.", kind="warning")
                restart = _menu(ui, "Riavviare ora " + ("tutto WSL2?" if backend == "wsl" else "l'ambiente NIPAT?"), [
                    ("1", "Conferma il riavvio", "Applica i nuovi limiti all'ambiente"),
                    ("0", "Rimanda" if backend == "wsl" else "Annulla la modifica",
                     "Salva soltanto; i limiti attivi restano quelli attuali" if backend == "wsl" else
                     "L'ambiente Lima attivo deve essere arrestato per modificarlo"),
                ]) == "1"
                if backend == "lima" and not restart:
                    ui.message("Modifica annullata: l'ambiente e la configurazione restano invariati.")
                    continue
            result = manager.apply(change, confirmed=True, restart_confirmed=restart)
            ui.message("Configurazione delle risorse salvata.", kind="success")
            if result.get("backup_path") or result.get("backup"):
                ui.message("Backup: " + str(result.get("backup_path") or result["backup"]))
            if result.get("status") == "saved-restart-required":
                ui.message("Riavvio da completare: i nuovi limiti non sono ancora attivi. Le risorse effettive nel riepilogo descrivono l'ambiente attuale.", kind="warning")
            elif result.get("status") == "verification-required":
                ui.message("La configurazione e' salvata, ma il riavvio o la verifica non sono completati. Consultare gli avvisi e aggiornare il riepilogo prima di avviare un'analisi.", kind="warning")
            for warning in result.get("warnings", []):
                ui.message(str(warning), kind="warning")
        except Back:
            continue
        except (NipatError, OSError, ValueError) as exc:
            ui.message(f"Impossibile applicare la modifica: {exc}", kind="error")
