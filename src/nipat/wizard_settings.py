"""Persistent, reviewed defaults for the guided interface."""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path
from typing import Any

from nipat.adapters.panels import read_position_panel
from nipat.errors import NipatError, ValidationError
from nipat.paths import ProjectLayout
from nipat.preferences import Preferences, PreferencesStore
from nipat.terminal import Terminal
from nipat.validation.files import require_file
from nipat.wizard_forms import Back, Cancelled, Field, WorkflowForm, navigation, unquote


_DEFAULT_KEYS = {
    "1": {"mode", "reference", "panel", "parallel"},
    "2": {"mode", "reference", "panel"},
    "3": {"mode", "panel"},
    "4": {"mother_prefix", "father_prefix", "popfreq", "cutoff_mode", "panel",
          "cutoffs", "cutoff_map", "err_const"},
}


def _native_cutoffs(value: str) -> str:
    """Validate and anchor saved cutoff paths to their selection directory."""
    if not value:
        return ""
    entries, labels = [], set()
    for item in value.split(","):
        if "=" not in item:
            raise ValidationError("Usare etichetta=percorso per ogni cutoff predefinito.")
        label, filename = (part.strip() for part in item.split("=", 1))
        if (not label or label in labels or any(c in label for c in ",=")
                or any(ord(c) < 32 for c in label)):
            raise ValidationError("Ogni cutoff richiede un'etichetta valida e distinta.")
        labels.add(label)
        path = require_file(Path(unquote(filename)), "Pannello cutoff")
        read_position_panel(path)
        if "," in str(path):
            raise ValidationError("Per percorsi con virgole usare 'Etichette e file'.")
        entries.append(f"{label}={path}")
    return ",".join(entries)


def _menu(ui: Terminal, title: str, choices: list[tuple[str, str, str]],
          *, default: str) -> str:
    """Keep local back navigation separate from cancellation to the main menu."""
    selected = ui.menu(title, choices, default=default).strip().casefold()
    if selected == ":annulla":
        raise Cancelled
    return selected


class DefaultsForm(WorkflowForm):
    """Reuse workflow labels, choices and validation without collecting samples."""

    def fields(self) -> list[Field]:
        result = []
        for field in super().fields():
            if field.key not in _DEFAULT_KEYS[self.choice]:
                continue
            if field.kind in {"file", "cutoffs"} or field.key == "cutoff_map":
                field = replace(field, required=False)
            result.append(field)
        return result

    def read_default(self, field: Field) -> Any:
        if not field.required:
            self.ui.message("Questo valore e' facoltativo nella configurazione. :vuoto lo rimuove; gli input richiesti saranno chiesti durante l'analisi.", kind="muted")
        if field.key == "cutoff_map":
            while True:
                value = self._read(field)
                try:
                    return _native_cutoffs(value)
                except (ValidationError, OSError, csv.Error) as exc:
                    self.ui.message(str(exc), kind="error")
        return self._read(field)

    def display_value(self, field: Field) -> str:
        value = self.values.get(field.key, field.default)
        if field.options:
            return next((label for key, label, _ in field.options if key == value), str(value))
        if value in (None, "") and field.kind in {"file", "cutoffs"}:
            return "Da selezionare durante l'analisi"
        if value == "":
            return "(vuoto)"
        return self.format_value(value)


class GuidedSettings:
    """Own saved defaults and the effective layout, leaving runtime bindings intact."""

    def __init__(self, layout: ProjectLayout, store: PreferencesStore | None = None,
                 directory_overrides: dict[str, Path] | None = None):
        self.base_layout = self.layout = layout
        self.store = store
        self.directory_overrides = directory_overrides or {}
        self.preferences = Preferences()
        self.load_error: str | None = None
        self.layout_error: str | None = None
        if store is not None:
            try:
                self.preferences = store.load()
            except (NipatError, OSError, ValueError) as exc:
                self.load_error = str(exc)
        self.refresh_layout()

    @property
    def error(self) -> str | None:
        return self.load_error or self.layout_error

    def refresh_layout(self) -> None:
        try:
            self.layout = self.preferences.effective_layout(self.base_layout, self.directory_overrides)
            self.layout_error = None
        except (NipatError, OSError, ValueError) as exc:
            self.layout = self.base_layout
            self.layout_error = str(exc)

    def explain(self, ui: Terminal) -> None:
        if self.error:
            ui.message(f"Impostazioni da correggere: {self.error}", kind="warning")
            ui.message("Aprire Configura prima di avviare un'analisi. Il file delle impostazioni non e' stato modificato.", kind="muted")
        if self.directory_overrides:
            names = ", ".join("dati" if key == "data_dir" else "risultati"
                              for key in self.directory_overrides)
            ui.message(f"Cartelle {names}: in questa sessione prevalgono le opzioni esplicite di avvio. Le preferenze salvate saranno utilizzate alla riapertura senza tali opzioni.", kind="muted")

    def _save(self, preferences: Preferences) -> None:
        if self.load_error:
            raise ValidationError("Il file delle impostazioni non e' leggibile. Usare Ripristina impostazioni per sostituirlo esplicitamente.")
        # Validate the saved layout even when a command-line override masks it.
        preferences.effective_layout(self.base_layout)
        effective = preferences.effective_layout(self.base_layout, self.directory_overrides)
        effective.ensure_storage_dirs()
        if self.store is not None:
            self.store.save(preferences)
        self.preferences, self.layout = preferences, effective
        self.layout_error = None

    def _saved_message(self, ui: Terminal) -> None:
        ui.message("Impostazioni salvate: saranno proposte anche ai prossimi avvii." if self.store else
                   "Impostazioni applicate a questa sessione guidata.", kind="success")
        self.explain(ui)

    def _directories(self, ui: Terminal) -> None:
        values = {"data_dir": self.preferences.data_dir or self.base_layout.data_dir,
                  "runs_dir": self.preferences.runs_dir or self.base_layout.runs_dir}
        while True:
            ui.message("Le cartelle impostate vengono utilizzate dalle prossime analisi guidate. I file esistenti non vengono spostati o eliminati.", kind="muted")
            ui.message("La cartella dati e' una destinazione di lavoro indicata da NIPAT; i file di input possono essere scelti anche altrove. I percorsi relativi partono dalla cartella corrente.", kind="muted")
            ui.message("Selezionare un campo da modificare, poi 9 per salvare. 0 torna a Configura senza salvare; :annulla o Ctrl+C tornano al menu principale senza salvare le modifiche di questa schermata.", kind="muted")
            action = _menu(ui, "Configura / Cartelle dati e risultati", [
                ("1", "Cartella dati", str(values["data_dir"])),
                ("2", "Cartella risultati", str(values["runs_dir"])),
                ("9", "Salva modifiche", "Per i prossimi avvii della CLI guidata"),
                ("0", "Annulla modifiche", "Torna a Configura"),
            ], default="0")
            if action in {"0", ":indietro"}:
                return
            if action == "9":
                try:
                    self._save(self.preferences.with_directories(**values))
                except (NipatError, OSError, ValueError) as exc:
                    ui.message(str(exc), kind="error")
                    continue
                self._saved_message(ui)
                return
            if action not in {"1", "2"}:
                ui.message("Scegliere 1 o 2 per modificare, 9 per salvare oppure 0 per annullare.", kind="muted")
                continue
            key = "data_dir" if action == "1" else "runs_dir"
            ui.message("Incollare il percorso, anche tra virgolette. Invio mantiene il valore; :indietro torna a questa schermata; :annulla o Ctrl+C tornano al menu principale.", kind="muted")
            try:
                answer = navigation(ui.prompt("Cartella dati" if action == "1" else "Cartella risultati",
                                              default=str(values[key]), path=True))
                candidate = Path(unquote(answer or str(values[key]))).expanduser()
                values[key] = candidate
            except Back:
                continue
            except (OSError, ValueError) as exc:
                ui.message(str(exc), kind="error")

    def _workflow(self, ui: Terminal, choice: str, err_const: float) -> None:
        form = DefaultsForm(choice, ui, self.layout, err_const,
                            defaults=self.preferences.workflow_defaults(choice))
        while True:
            ui.message("Questi valori saranno proposti all'apertura dell'analisi e potranno essere modificati nel suo riepilogo.", kind="muted")
            ui.message("Campioni, coppie CPI e nome dell'esecuzione vengono scelti per ogni analisi. Le costanti interne degli script R non sono modificate.", kind="muted")
            ui.message("Selezionare un campo da modificare, poi 9 per salvare. 0 torna a Configura senza salvare; :annulla o Ctrl+C tornano al menu principale senza salvare le modifiche di questa schermata.", kind="muted")
            fields = form.fields()
            action = _menu(ui, f"Configura / {form.title}", [
                (str(index + 1), field.label, form.display_value(field))
                for index, field in enumerate(fields)
            ] + [("9", "Salva modifiche", "Per i prossimi avvii della CLI guidata"),
                 ("0", "Annulla modifiche", "Torna a Configura")], default="0")
            if action in {"0", ":indietro"}:
                return
            if action == "9":
                try:
                    values = {key: value for key, value in form.values.items()
                              if value is not None and not (key in {"cutoffs", "cutoff_map"} and not value)}
                    self._save(self.preferences.with_workflow(choice, values))
                except (NipatError, OSError, ValueError) as exc:
                    ui.message(str(exc), kind="error")
                    continue
                self._saved_message(ui)
                return
            numbers = {str(index + 1): field for index, field in enumerate(fields)}
            if action not in numbers:
                ui.message("Scegliere uno dei campi indicati, 9 per salvare oppure 0 per annullare.", kind="muted")
                continue
            field = numbers[action]
            try:
                form.values[field.key] = form.read_default(field)
            except Back:
                continue

    def _summary(self, ui: Terminal, err_const: float) -> None:
        ui.heading("Configura / Riepilogo impostazioni")
        ui.message(f"Cartella dati in uso: {self.layout.data_dir}")
        ui.message(f"Cartella risultati in uso: {self.layout.runs_dir}")
        ui.message("Canale aggiornamenti: " + ("Testing" if self.preferences.update_channel == "testing" else "Stabile"))
        ui.message("Verifica aggiornamenti all'avvio: " + ("attivata" if self.preferences.check_updates_on_startup else "disattivata"))
        if self.store:
            ui.message(f"File delle preferenze: {self.store.path}", kind="muted")
        for choice in ("1", "2", "3", "4"):
            form = DefaultsForm(choice, ui, self.layout, err_const,
                                defaults=self.preferences.workflow_defaults(choice))
            ui.heading(form.title)
            for field in form.fields():
                ui.message(f"{field.label}: {form.display_value(field)}")
        self.explain(ui)
        ui.message("Cartella dell'applicazione, runtime e cache di installazione: per cambiarle eseguire nuovamente il programma di installazione. Configura non sposta questi componenti.", kind="muted")

    def _updates(self, ui: Terminal) -> None:
        channel = self.preferences.update_channel
        startup = self.preferences.check_updates_on_startup
        while True:
            ui.message("La verifica consulta le release pubblicate su GitHub. Download e installazione richiedono sempre una scelta esplicita. :annulla o Ctrl+C tornano al menu principale senza salvare le modifiche di questa schermata.", kind="muted")
            ui.message("La verifica all'avvio mostra soltanto un avviso e non avvia download. Si puo' verificare in qualsiasi momento dal punto 9 del menu principale.", kind="muted")
            action = _menu(ui, "Configura / Aggiornamenti", [
                ("1", "Canale", "Testing" if channel == "testing" else "Stabile"),
                ("2", "Verifica all'avvio", "Attivata" if startup else "Disattivata"),
                ("9", "Salva modifiche", "Per i prossimi avvii della CLI guidata"),
                ("0", "Annulla modifiche", "Torna a Configura"),
            ], default="0")
            if action in {"0", ":indietro"}:
                return
            if action == "9":
                self._save(replace(self.preferences, update_channel=channel,
                                   check_updates_on_startup=startup))
                self._saved_message(ui)
                return
            if action == "1":
                selected = _menu(ui, "Canale degli aggiornamenti", [
                    ("1", "Testing", "Release di test e release stabili"),
                    ("2", "Stabile", "Solo release pubblicate come stabili"),
                    ("0", "Indietro", "Mantiene la scelta attuale"),
                ], default="1" if channel == "testing" else "2")
                if selected in {"1", "2"}:
                    channel = "testing" if selected == "1" else "stable"
            elif action == "2":
                selected = _menu(ui, "Verificare gli aggiornamenti all'avvio?", [
                    ("1", "Attiva", "Solo avviso; richiede una connessione a GitHub"),
                    ("2", "Disattiva", "Verifica manuale dal menu principale"),
                    ("0", "Indietro", "Mantiene la scelta attuale"),
                ], default="1" if startup else "2")
                if selected in {"1", "2"}:
                    startup = selected == "1"
            else:
                ui.message("Scegliere 1 o 2 per modificare, 9 per salvare oppure 0 per annullare.", kind="muted")

    def _reset(self, ui: Terminal) -> None:
        ui.message("Il ripristino elimina solo le preferenze della CLI guidata. Dati, risultati e installazione restano disponibili; nessun file di analisi viene spostato o cancellato.", kind="muted")
        action = _menu(ui, "Ripristinare le impostazioni iniziali?", [
            ("1", "Ripristina impostazioni", "Cartelle di installazione e parametri iniziali"),
            ("0", "Annulla", "Conserva le preferenze attuali"),
        ], default="0")
        if action != "1":
            return
        if self.store:
            self.store.reset()
        self.preferences = Preferences()
        self.load_error = None
        self.refresh_layout()
        ui.message("Impostazioni ripristinate. Dati e risultati non sono stati modificati.", kind="success")
        self.explain(ui)

    def configure(self, ui: Terminal, *, err_const: float) -> ProjectLayout:
        while True:
            ui.message("Impostare cartelle e valori predefiniti della CLI guidata. Ogni analisi permette ancora di modificare gli input e i parametri prima dell'avvio.", kind="muted")
            ui.message("I comandi diretti conservano le proprie opzioni e i propri valori predefiniti; queste preferenze riguardano il menu guidato. :annulla o Ctrl+C tornano al menu principale.", kind="muted")
            self.explain(ui)
            action = _menu(ui, "Configura", [
                ("1", "Cartelle dati e risultati", "Destinazioni delle analisi guidate"),
                ("2", "DNPcall", "Input, riferimento, pannello ed esecuzione"),
                ("3", "SNPcall", "Input, riferimento e pannello"),
                ("4", "Contamination", "Input e pannello"),
                ("5", "CPI", "Prefissi, frequenze, siti e costante di errore"),
                ("6", "Riepilogo impostazioni", "Valori in uso e file delle preferenze"),
                ("7", "Ripristina impostazioni", "Conferma richiesta; dati conservati"),
                ("8", "Aggiornamenti", "Canale e verifica all'avvio"),
                ("0", "Torna al menu", ""),
            ], default="0")
            if action in {"0", ":indietro"}:
                return self.layout
            try:
                if action == "6":
                    self._summary(ui, err_const)
                elif action == "7":
                    self._reset(ui)
                elif self.load_error:
                    ui.message("Impostazioni non leggibili: consultare il riepilogo o scegliere Ripristina impostazioni per correggerle.", kind="warning")
                elif action == "8":
                    self._updates(ui)
                elif action == "1":
                    self._directories(ui)
                elif action in {"2", "3", "4", "5"}:
                    self._workflow(ui, str(int(action) - 1), err_const)
                else:
                    ui.message("Scegliere una delle opzioni indicate (0-8).", kind="muted")
            except (NipatError, OSError, ValueError) as exc:
                ui.message(str(exc), kind="error")
