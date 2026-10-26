"""Editable forms for automatic scientific plans, without executing analyses."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from typing import Any

from nipat.adapters.panels import read_position_panel
from nipat.errors import ValidationError
from nipat.validation.files import require_file
from nipat.wizard_forms import (
    Back, Field, WorkflowForm, check_popfreq, navigation, unquote,
)


class DnpContaminationForm(WorkflowForm):
    """Review one automatic chain without duplicating scientific orchestration."""

    @property
    def title(self) -> str:
        return "Workflow automatico / DNPcall -> Contamination"

    def fields(self) -> list[Field]:
        fields = super().fields()
        panel_fields = [Field(
            "contamination_panel_mode", "Pannello per Contamination", "choice", "1",
            options=(("1", "Stesso pannello DNP", "Usa le coordinate del pannello gia' selezionato"),
                     ("2", "Pannello diverso", "Seleziona un altro insieme di coordinate DNP")),
        )]
        if self.values.get("contamination_panel_mode") == "2":
            panel_fields.append(Field(
                "contamination_panel", "Pannello di coordinate per Contamination", "file",
                check=read_position_panel,
            ))
        return fields[:-1] + panel_fields + fields[-1:]

    def _guide(self, field: Field, default: str = "") -> None:
        if field.key not in {"contamination_panel_mode", "contamination_panel"}:
            super()._guide(field, default)
            return
        if field.key == "contamination_panel_mode":
            self.ui.message(
                "Contamination riceve automaticamente tutte le tabelle prodotte da DNPcall. "
                "Scegliere quali coordinate usare per questa seconda fase; non occorre selezionare i file intermedi.",
                kind="muted",
            )
            self.ui.message("Invio conferma il pannello proposto; scegliere 2 per indicarne uno diverso.", kind="muted")
        else:
            self.ui.message(
                "Scegliere le coordinate DNP per la stima della contaminazione: colonne chr, pos1, pos2, "
                "con o senza intestazione. E' accettato anche un pannello DNP a cinque colonne. "
                "Il pannello deve riferirsi alla stessa assembly e ai siti analizzati da DNPcall.",
                kind="muted",
            )
            self.ui.message(
                "Incollare un percorso completo o relativo alla cartella corrente, anche tra virgolette.",
                kind="muted",
            )
            self.ui.message(
                "Invio mantiene il valore proposto." if default else
                "Inserire il percorso richiesto e premere Invio; il campo non puo' essere lasciato vuoto.",
                kind="muted",
            )
        self.ui.message(":indietro torna al campo precedente; :annulla torna al menu.", kind="muted")

    def _selected(self, field: Field, answer: str) -> None:
        if field.key != "contamination_panel_mode":
            super()._selected(field, answer)
            return
        self.ui.message(
            "Selezione: stesso pannello DNP. Contamination usera' le coordinate del pannello selezionato per DNPcall."
            if answer == "1" else
            "Selezione: pannello diverso. Indicare ora il file di coordinate per Contamination.",
            kind="muted",
        )

    def review(self, *, dry_run: bool = False) -> bool:
        self.ui.message(
            "Sequenza: 1. DNPcall su tutti i BAM selezionati; 2. Contamination sulle tabelle prodotte. "
            "Le due fasi sono automatiche e conservano risultati e stato separati.", kind="muted",
        )
        self.ui.message(
            "In caso di errore il workflow si arresta. Contamination parte solo dopo il completamento "
            "di DNPcall e la verifica delle sue tabelle; non sono richieste altre conferme fra le fasi.",
            kind="muted",
        )
        return super().review(dry_run=dry_run)

    def arguments(self) -> dict:
        return {
            **super().arguments(),
            "contamination_panel": self.values["contamination_panel"]
            if self.values["contamination_panel_mode"] == "2" else None,
        }


class DnpCpiForm(DnpContaminationForm):
    """Collect explicit biological roles and retain them while editing a plan."""

    def __init__(self, ui, layout, err_const: float, *, include_contamination: bool,
                 defaults: dict | None = None, cpi_defaults: dict | None = None):
        super().__init__("1", ui, layout, err_const, defaults=defaults)
        self.include_contamination = include_contamination
        for key, value in (cpi_defaults or {}).items():
            if key in {"popfreq", "cutoff_mode", "cutoffs", "cutoff_map", "err_const"}:
                self.values[key] = value
            elif key == "panel":
                self.values["cpi_panel"] = value

    @property
    def title(self) -> str:
        return "Workflow automatico / " + (
            "DNPcall -> Contamination e CPI" if self.include_contamination else "DNPcall -> CPI"
        )

    def fields(self) -> list[Field]:
        # Selection is represented by explicit pairs, rather than a filename
        # convention or a second independent list of BAM files.
        dnp_fields = {field.key: field for field in WorkflowForm.fields(self)}
        result = [Field("pairs", "Coppie cfDNA materno / campione paterno", "pairs")]
        result += [dnp_fields[key] for key in ("reference", "panel", "parallel")]
        if self.include_contamination:
            result.extend(field for field in super().fields()
                          if field.key in {"contamination_panel_mode", "contamination_panel"})
        result += [Field("popfreq", "Frequenze di popolazione", "file", check=check_popfreq),
                   Field("cutoff_mode", "Selezione dei siti CPI", "choice", "0", options=(
                       ("0", "Tutti i siti", "Modalita' ALL"),
                       ("1", "Pannello singolo", "Coordinate DNP"),
                       ("2", "Etichette e file", "Uno o piu' cutoff"),
                       ("3", "Mappa nativa", "etichetta=file,etichetta2=file2")))]
        mode = self.values.get("cutoff_mode", "0")
        if mode == "1":
            result.append(Field("cpi_panel", "Pannello di coordinate CPI", "file", check=read_position_panel))
        elif mode == "2":
            result.append(Field("cutoffs", "Cutoff con etichetta", "cutoffs"))
        elif mode == "3":
            result.append(Field("cutoff_map", "Mappa cutoff (etichetta=file,etichetta2=file2)"))
        result += [Field("err_const", "Costante di errore", "number", str(self.err_const)),
                   dnp_fields["run_name"]]
        return result

    def _cpi_form(self) -> WorkflowForm:
        form = WorkflowForm("4", self.ui, self.layout, self.err_const)
        form.values = self.values
        return form

    def _guide(self, field: Field, default: str = "") -> None:
        if field.key in {"popfreq", "cutoff_mode", "cpi_panel", "cutoffs", "cutoff_file", "cutoff_map", "err_const"}:
            self._cpi_form()._guide(replace(field, key="panel") if field.key == "cpi_panel" else field, default)
        else:
            super()._guide(field, default)

    def _selected(self, field: Field, answer: str) -> None:
        if field.key == "cutoff_mode":
            self._cpi_form()._selected(field, answer)
        else:
            super()._selected(field, answer)

    @staticmethod
    def format_value(value: Any) -> str:
        if isinstance(value, list) and value and isinstance(value[0], tuple) and len(value[0]) == 3:
            return "\n".join(DnpCpiForm.format_value(pair) for pair in value)
        if isinstance(value, tuple) and len(value) == 3:
            return f"Coppia {value[0]}\n  cfDNA materno: {value[1]}\n  Campione paterno: {value[2]}"
        return WorkflowForm.format_value(value)

    @staticmethod
    def _validate_pairs(pairs: list[tuple[str, Path, Path]]) -> None:
        ids = set()
        roles: list[tuple[Path, str]] = []
        seen_pairs: list[tuple[Path, Path]] = []
        for identifier, mother, father in pairs:
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", identifier) is None:
                raise ValidationError("ID coppia: iniziare con una lettera e usare al massimo 64 lettere ASCII, numeri, '_' o '-'.")
            if identifier.casefold() in ids:
                raise ValidationError(f"ID coppia duplicato: {identifier}.")
            ids.add(identifier.casefold())
            for path, role in ((mother, "cfDNA materno"), (father, "campione paterno")):
                require_file(path, f"BAM {role}")
                for previous, old_role in roles:
                    if path.samefile(previous) and role != old_role:
                        raise ValidationError(
                            "Lo stesso BAM non puo' rappresentare sia cfDNA materno sia campione paterno. "
                            "Usare :indietro per correggere il ruolo o il file."
                        )
                roles.append((path, role))
            if any(mother.samefile(old_mother) and father.samefile(old_father)
                   for old_mother, old_father in seen_pairs):
                raise ValidationError("La stessa coppia di BAM e' gia' presente nell'elenco.")
            seen_pairs.append((mother, father))

    def _pair_entry(self, others: list, existing: tuple | None = None) -> tuple | None:
        values = list(existing or ("", None, None))
        index = 0
        while index < 3:
            label = ("ID coppia", "BAM cfDNA materno", "BAM campione paterno")[index]
            if index == 0:
                self.ui.message(
                    "Assegnare un ID alla coppia: iniziare con una lettera; sono ammessi lettere ASCII, numeri, '_' e '-' (massimo 64 caratteri).",
                    kind="muted",
                )
                if others and existing is None:
                    self.ui.message("Invio senza ID conclude l'elenco delle coppie.", kind="muted")
            else:
                self.ui.message(
                    "Selezionare il BAM del cfDNA materno (campione di plasma). Il ruolo non viene dedotto dal nome del file."
                    if index == 1 else
                    "Selezionare il BAM del campione paterno per questa coppia. Il ruolo non viene dedotto dal nome del file.",
                    kind="muted",
                )
                self.ui.message("Incollare il percorso completo o relativo, anche tra virgolette. Lo stesso BAM puo' essere riutilizzato in piu' coppie nello stesso ruolo.", kind="muted")
            self.ui.message(":indietro torna al campo precedente della coppia; :annulla torna al menu.", kind="muted")
            default = str(values[index]) if values[index] is not None else ""
            try:
                answer = navigation(self.ui.prompt(label, default=default, path=index > 0))
                if not answer:
                    answer = default
                if not answer:
                    if index == 0 and others and existing is None:
                        return None
                    self.ui.message("Inserire il valore richiesto oppure usare :indietro o :annulla.", kind="muted")
                    continue
                if index == 0:
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", answer) is None:
                        raise ValidationError("ID coppia non valido: iniziare con una lettera e usare al massimo 64 lettere ASCII, numeri, '_' o '-'.")
                    if answer.casefold() in {pair[0].casefold() for pair in others}:
                        raise ValidationError(f"ID coppia duplicato: {answer}.")
                    values[index] = answer
                else:
                    candidate = require_file(Path(unquote(answer)), label)
                    if index == 2:
                        self._validate_pairs([*others, (values[0], values[1], candidate)])
                    values[index] = candidate
                index += 1
            except Back:
                if index == 0:
                    raise
                index -= 1
            except (ValidationError, OSError, ValueError) as exc:
                self.ui.message(str(exc), kind="error")
        return tuple(values)

    def _pairs(self) -> list:
        current = list(self.values.get("pairs", []))
        self.ui.message(
            "Per ogni coppia indicare esplicitamente ID, BAM cfDNA materno e BAM del campione paterno. "
            "I BAM condivisi vengono elaborati una sola volta; le associazioni rimangono distinte.", kind="muted",
        )
        self.ui.message("Nomi e prefissi dei file CPI sono preparati automaticamente da NIPAT; non occorre rinominare i BAM.", kind="muted")
        manage = bool(current)
        while True:
            if manage:
                self.ui.message(self.format_value(current))
                action = navigation(self.ui.menu("Coppie inserite", [
                    ("1", "Mantieni e continua", "Conserva ID, file e ruoli"),
                    ("2", "Modifica una coppia", "ID, cfDNA materno e campione paterno"),
                    ("3", "Aggiungi coppie", "Riutilizzo dei campioni nello stesso ruolo consentito"),
                    ("4", "Rimuovi una coppia", "Richiesta almeno una coppia"),
                    ("0", "Indietro", "Torna al campo precedente"),
                ], default="1"))
                if action == "0":
                    raise Back
                if action == "1":
                    try:
                        self._validate_pairs(current)
                        return current
                    except (ValidationError, OSError, ValueError) as exc:
                        self.ui.message(str(exc), kind="error")
                        continue
                if action in {"2", "4"}:
                    selected = navigation(self.ui.menu("Selezionare una coppia", [
                        (str(number), pair[0], "cfDNA materno / campione paterno")
                        for number, pair in enumerate(current, 1)
                    ] + [("0", "Torna all'elenco", "")], default="0"))
                    if selected == "0":
                        continue
                    numbers = {str(number): number - 1 for number in range(1, len(current) + 1)}
                    if selected not in numbers:
                        self.ui.message("Selezionare una coppia dell'elenco.", kind="muted")
                        continue
                    index = numbers[selected]
                    if action == "4":
                        if len(current) == 1:
                            self.ui.message("Mantenere almeno una coppia; modificarla oppure annullare il workflow.", kind="muted")
                            continue
                        current.pop(index)
                    else:
                        try:
                            current[index] = self._pair_entry(current[:index] + current[index + 1:], current[index])
                        except Back:
                            self.ui.message("Modifica annullata: la coppia conserva i file e i ruoli precedenti.", kind="muted")
                    self.values["pairs"] = list(current)
                    continue
                if action != "3":
                    self.ui.message("Scegliere una delle opzioni indicate.", kind="muted")
                    continue
            try:
                pair = self._pair_entry(current)
            except Back:
                if not current:
                    raise
                self.ui.message("Coppia non aggiunta: le coppie gia' inserite sono conservate.", kind="muted")
                manage = True
                continue
            if pair is None:
                return current
            current.append(pair)
            self.values["pairs"] = list(current)
            self.ui.message(f"Aggiunta: {self.format_value(pair)}", kind="success")
            manage = False

    def _read(self, field: Field) -> Any:
        return self._pairs() if field.kind == "pairs" else super()._read(field)

    def review(self, *, dry_run: bool = False) -> bool:
        self.ui.message(
            "Sequenza: DNPcall sui BAM distinti, poi Contamination e CPI sulle rispettive tabelle DNPcall."
            if self.include_contamination else
            "Sequenza: DNPcall sui BAM distinti, poi CPI sulle tabelle cfDNA materno e paterno associate a ciascuna coppia.",
            kind="muted",
        )
        if self.include_contamination:
            self.ui.message("Contamination non filtra o modifica gli input CPI. Le fasi vengono eseguite in sequenza; un errore arresta il workflow.", kind="muted")
        self.ui.message("Controllare esplicitamente ID, file e ruoli di tutte le coppie. Una sola conferma avvia l'intero workflow; risultati e stato di ogni fase rimangono separati.", kind="muted")
        self.ui.message("NIPAT assegna automaticamente i nomi e i prefissi dei file CPI mantenendo le associazioni mostrate.", kind="muted")
        return WorkflowForm.review(self, dry_run=dry_run)

    def arguments(self) -> dict:
        values = self.values
        mode = values["cutoff_mode"]
        return {
            "pairs": list(values["pairs"]), "reference": values["reference"], "panel": values["panel"],
            "parallel": values["parallel"] == "2", "popfreq": values["popfreq"],
            "err_const": values["err_const"], "cpi_panel": values["cpi_panel"] if mode == "1" else None,
            "cutoffs": values["cutoffs"] if mode == "2" else None,
            "cutoff_map": values["cutoff_map"] if mode == "3" else None,
            "include_contamination": self.include_contamination,
            "contamination_panel": values["contamination_panel"]
            if self.include_contamination and values["contamination_panel_mode"] == "2" else None,
            "run_name": values["run_name"],
        }


