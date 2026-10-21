"""Editable, side-effect-free input forms for the guided CLI."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from nipat.adapters.panels import read_dnp_list, read_position_panel, read_snp_positions
from nipat.errors import ValidationError
from nipat.paths import ProjectLayout, _SAFE_RUN_NAME
from nipat.validation.files import (
    require_columns, require_contamination_input, require_directory, require_file,
    require_sidecar, require_snp_pileup,
)


class Cancelled(Exception):
    """Return to the main menu before starting an analysis."""


class Back(Exception):
    """Return to the preceding field, retaining the collected values."""


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"
    default: str = ""
    required: bool = True
    options: tuple[tuple[str, str, str], ...] = ()
    check: Callable[[Any], Any] | None = None


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def navigation(value: str) -> str:
    value = value.strip()
    if value.casefold() == ":annulla":
        raise Cancelled
    if value.casefold() == ":indietro":
        raise Back
    return value


def check_reference(path: Path) -> None:
    require_sidecar(path, ".fai", "Indice FASTA")
    if path.suffix.lower() in {".gz", ".bgz", ".bgzf"}:
        require_sidecar(path, ".gzi", "Indice FASTA BGZF")


def check_bamlist(path: Path) -> None:
    selected = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        entry = Path(unquote(line.strip())).expanduser()
        selected.append(require_file(entry if entry.is_absolute() else path.parent / entry, "BAM"))
    if not selected:
        raise ValidationError("La lista BAM e' vuota.")
    if len(set(selected)) != len(selected):
        raise ValidationError("Lo stesso BAM compare piu' volte nella lista.")


def check_name(value: str) -> None:
    if any(c in value for c in "/\\") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValidationError("Usare un identificativo senza separatori di cartella o caratteri di controllo.")


def check_pairs(value: str) -> None:
    pairs = []
    for pair in value.split(","):
        ids = [part.strip() for part in pair.split(":")]
        if len(ids) != 2 or not all(ids):
            raise ValidationError("Coppie: usare madre:padre, per esempio A1:A1,A2:A2.")
        for identifier in ids:
            check_name(identifier)
        pairs.append(":".join(ids))
    if len(set(pairs)) != len(pairs):
        raise ValidationError("Coppia CPI duplicata.")


def check_popfreq(path: Path) -> None:
    require_columns(path, {"chr", "pos1", "pos2", "Ref_f.pop", "Alt_f.pop"},
                    "Frequenze di popolazione non compatibili")


class WorkflowForm:
    """Retain values in memory; no run is created until the caller executes it."""

    TITLES = {"1": "DNPcall", "2": "SNPcall", "3": "Contamination", "4": "CPI"}

    def __init__(self, choice: str, ui: Any, layout: ProjectLayout, err_const: float):
        self.choice, self.ui, self.layout, self.err_const = choice, ui, layout, err_const
        self.values: dict[str, Any] = {}

    @property
    def title(self) -> str:
        return self.TITLES[self.choice]

    def fields(self) -> list[Field]:
        values = self.values
        if self.choice == "1":
            result = [Field("mode", "Input DNPcall", "choice", "1", options=(
                ("1", "Uno o piu' BAM", "Un percorso per riga"),
                ("2", "File bamlist", "Percorsi relativi alla cartella della lista"),
            ))]
            result += ([Field("bamlist", "File bamlist", "file", check=check_bamlist)]
                       if values.get("mode") == "2" else [Field("bams", "BAM", "files")])
            result += [Field("reference", "FASTA indicizzato (.fai; .gzi se BGZF)", "file", check=check_reference),
                       Field("panel", "Pannello DNP", "file", check=read_dnp_list),
                       Field("parallel", "Modalita' di esecuzione", "choice", "1", options=(
                           ("1", "Seriale", "Impostazione predefinita"),
                           ("2", "Parallela", "Piu' campioni contemporaneamente")))]
        elif self.choice == "2":
            result = [Field("mode", "Input SNPcall", "choice", "1", options=(
                ("1", "BAM e riferimento", "Preparazione automatica del pileup"),
                ("2", "Pileup esistente", "Con QNAME nella settima colonna"),
            ))]
            if values.get("mode") == "2":
                result += [Field("pileup", "Pileup SNP", "file", check=require_snp_pileup)]
            else:
                result += [Field("bam", "BAM", "file"),
                           Field("reference", "FASTA indicizzato (.fai; .gzi se BGZF)", "file", check=check_reference)]
            result += [Field("panel", "Lista SNP (pos, ref, alt)", "file",
                             check=lambda path: read_snp_positions(path, for_bed=values.get("mode") != "2"))]
        elif self.choice == "3":
            result = [Field("mode", "Input Contamination", "choice", "1", options=(
                ("1", "Tabelle singole", "Selezione esplicita dei file"),
                ("2", "Cartella", "TXT/TSV anche nelle sottocartelle"),
            ))]
            result += ([Field("input_dir", "Cartella di input", "directory")]
                       if values.get("mode") == "2" else
                       [Field("inputs", "Tabella campione", "files", check=require_contamination_input)])
            result += [Field("panel", "Pannello DNP", "file", check=read_position_panel)]
        else:
            result = [Field("input_dir", "Cartella cfDNA materno e presunto padre", "directory"),
                      Field("pairs", "Coppie (esempio A1:A1,A2:A2)", check=check_pairs),
                      Field("mother_prefix", "Prefisso file cfDNA materno", default="Mother", required=False, check=check_name),
                      Field("father_prefix", "Prefisso file presunto padre", default="Father", required=False, check=check_name),
                      Field("popfreq", "Frequenze di popolazione", "file", check=check_popfreq),
                      Field("cutoff_mode", "Selezione dei siti CPI", "choice", "0", options=(
                          ("0", "Tutti i siti", "Modalita' ALL"),
                          ("1", "Pannello singolo", "Coordinate DNP"),
                          ("2", "Etichette e file", "Uno o piu' cutoff"),
                          ("3", "Mappa nativa", "etichetta=file,etichetta2=file2")))]
            cutoff_mode = values.get("cutoff_mode", "0")
            if cutoff_mode == "1":
                result.append(Field("panel", "Pannello di coordinate DNP", "file", check=read_position_panel))
            elif cutoff_mode == "2":
                result.append(Field("cutoffs", "Cutoff con etichetta", "cutoffs"))
            elif cutoff_mode == "3":
                result.append(Field("cutoff_map", "Mappa cutoff (etichetta=file,etichetta2=file2)"))
            result.append(Field("err_const", "Costante di errore", "number", str(self.err_const)))
        return result + [Field("run_name", "Nome nuova esecuzione (vuoto = automatico)", "run", required=False)]

    def _text(self, field: Field, default: str) -> str:
        answer = navigation(self.ui.prompt(field.label, default=default,
                                           path=field.kind in {"file", "directory"}))
        if answer.casefold() == ":vuoto":
            answer = ""
        elif not answer:
            answer = default
        if not answer and field.required:
            raise ValidationError("Il valore e' obbligatorio.")
        return answer

    def _file(self, field: Field, value: str) -> Path:
        path = require_file(Path(unquote(value)), field.label)
        if field.check:
            field.check(path)
        return path

    def _collection(self, field: Field) -> list:
        current = list(self.values.get(field.key, []))
        if current:
            self.ui.message(self.format_value(current))
            while True:
                action = navigation(self.ui.menu("Elenco gia' inserito", [
                    ("1", "Mantieni", ""), ("2", "Sostituisci", ""),
                    ("3", "Aggiungi", ""), ("0", "Indietro", ""),
                ], default="1"))
                if action == "0":
                    raise Back
                if action == "1":
                    return current
                if action in {"2", "3"}:
                    current = [] if action == "2" else current
                    break
                self.ui.message("Scegliere una delle opzioni indicate.", kind="error")
        self.ui.message("Un elemento per volta; Invio termina la lista. :indietro conserva l'elenco.")
        while True:
            try:
                if field.kind == "cutoffs":
                    label = navigation(self.ui.prompt("Etichetta cutoff (Invio termina)"))
                    if not label and current:
                        return current
                    if not label or any(c in label for c in ",=") or any(ord(c) < 32 for c in label):
                        raise ValidationError("Etichetta cutoff non valida: evitare virgole e '='.")
                    if label in {item[0] for item in current}:
                        raise ValidationError("Etichetta cutoff duplicata.")
                    source = self._read(Field("cutoff_file", "File cutoff", "file", check=read_position_panel))
                    item = (label, source)
                else:
                    raw = navigation(self.ui.prompt(field.label + " (Invio termina)", path=True))
                    if not raw and current:
                        return current
                    if not raw:
                        raise ValidationError("Inserire almeno un file.")
                    item = self._file(field, raw)
                    if item in current:
                        raise ValidationError("Il file e' gia' presente nella lista.")
                current.append(item)
                self.values[field.key] = list(current)
                self.ui.message(f"Aggiunto ({len(current)}): {self.format_value(item)}", kind="success")
            except (ValidationError, OSError, ValueError, csv.Error) as exc:
                self.ui.message(str(exc), kind="error")

    def _read(self, field: Field) -> Any:
        if field.kind in {"files", "cutoffs"}:
            return self._collection(field)
        existing = self.values.get(field.key, field.default)
        default = "" if existing is None else str(existing)
        while True:
            try:
                if field.kind == "choice":
                    answer = navigation(self.ui.menu(field.label, list(field.options), default=default))
                    if answer not in {item[0] for item in field.options}:
                        raise ValidationError("Scegliere una delle opzioni indicate.")
                    return answer
                answer = self._text(field, default)
                if field.kind == "file":
                    return self._file(field, answer)
                if field.kind == "directory":
                    return require_directory(Path(unquote(answer)), field.label)
                if field.kind == "number":
                    try:
                        number = float(answer)
                    except ValueError:
                        number = float("nan")
                    if not math.isfinite(number) or number < 0:
                        raise ValidationError("Inserire un numero finito maggiore o uguale a zero, usando il punto decimale.")
                    return number
                if field.kind == "run":
                    if not answer:
                        return None
                    name = _SAFE_RUN_NAME.sub("-", answer.strip()).strip("-.")
                    if not name:
                        raise ValidationError("Il nome dell'esecuzione non contiene caratteri validi.")
                    if (self.layout.runs_dir / name).exists():
                        raise ValidationError(f"Esecuzione gia' presente: {name}. Scegliere un nuovo nome.")
                    if name != answer:
                        self.ui.message(f"Nome normalizzato: {name}")
                    return name
                if field.check:
                    field.check(answer)
                return answer
            except (ValidationError, OSError, ValueError, csv.Error) as exc:
                self.ui.message(str(exc), kind="error")

    def collect(self, start: int = 0, *, single: bool = False) -> None:
        index = start
        while index < len(self.fields()):
            fields = self.fields()
            field = fields[index]
            self.ui.heading(f"{self.title} / {index + 1} di {len(fields)} / {field.label}")
            try:
                self.values[field.key] = self._read(field)
            except Back:
                if index == 0:
                    raise Cancelled
                index -= 1
                continue
            if single:
                # A changed input mode may reveal fields that were not collected.
                for missing in self.fields():
                    if missing.key not in self.values:
                        self.ui.heading(f"{self.title} / {missing.label}")
                        try:
                            self.values[missing.key] = self._read(missing)
                        except Back:
                            return self.collect(self.fields().index(missing) - 1, single=True)
                return
            index += 1

    @staticmethod
    def format_value(value: Any) -> str:
        if value is None or value == "":
            return "(automatico o vuoto)"
        if isinstance(value, list):
            return "\n".join(WorkflowForm.format_value(item) for item in value)
        if isinstance(value, tuple):
            return f"{value[0]} = {value[1]}"
        return str(value)

    def review(self, *, dry_run: bool = False) -> bool:
        while True:
            self.ui.heading(f"{self.title} / Riepilogo prima dell'avvio")
            fields = self.fields()
            for field in fields:
                value = self.values[field.key]
                if field.options:
                    rendered = next(label for key, label, _ in field.options if key == value)
                elif value is None and field.key == "run_name":
                    rendered = "Automatico"
                elif value == "":
                    rendered = "(vuoto)"
                else:
                    rendered = self.format_value(value)
                self.ui.message(f"{field.label}: {rendered}")
            destination = self.layout.runs_dir / (self.values.get("run_name") or "<nome automatico>")
            self.ui.message(f"Destinazione: {destination}")
            choice = self.ui.menu("Come procedere?", [
                ("1", "Prepara dry-run" if dry_run else "Avvia analisi", "Con i valori mostrati"),
                ("2", "Modifica un campo", "Gli altri valori vengono conservati"),
                ("0", "Annulla", "Torna al menu senza avviare"),
            ], default="1")
            if choice in {"0", ":annulla", ":indietro"}:
                return False
            if choice == "1":
                return True
            if choice != "2":
                self.ui.message("Scegliere una delle opzioni indicate.", kind="error")
                continue
            selected = self.ui.menu("Campo da modificare", [
                (str(index + 1), field.label, "") for index, field in enumerate(fields)
            ] + [("0", "Torna al riepilogo", "")])
            if selected in {"0", ":indietro"}:
                continue
            if selected == ":annulla":
                return False
            field_numbers = {str(index + 1): index for index in range(len(fields))}
            if selected not in field_numbers:
                self.ui.message("Campo non valido.", kind="error")
                continue
            self.collect(field_numbers[selected], single=True)

    def arguments(self) -> dict[str, Any]:
        v = self.values
        common = {"run_name": v["run_name"]}
        if self.choice == "1":
            return {**common, "bams": v["bams"] if v["mode"] == "1" else None,
                    "bamlist": v["bamlist"] if v["mode"] == "2" else None,
                    "reference": v["reference"], "panel": v["panel"], "parallel": v["parallel"] == "2"}
        if self.choice == "2":
            bam_mode = v["mode"] == "1"
            return {**common, "bam": v["bam"] if bam_mode else None,
                    "pileup": None if bam_mode else v["pileup"],
                    "reference": v["reference"] if bam_mode else None, "panel": v["panel"]}
        if self.choice == "3":
            return {**common, "inputs": v["inputs"] if v["mode"] == "1" else None,
                    "input_dir": v["input_dir"] if v["mode"] == "2" else None, "panel": v["panel"]}
        return {**common, **{key: v[key] for key in (
            "input_dir", "pairs", "mother_prefix", "father_prefix", "popfreq", "err_const")},
            "panel": v["panel"] if v["cutoff_mode"] == "1" else None,
            "cutoffs": v["cutoffs"] if v["cutoff_mode"] == "2" else None,
            "cutoff_map": v["cutoff_map"] if v["cutoff_mode"] == "3" else None}
