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

    def __init__(self, choice: str, ui: Any, layout: ProjectLayout, err_const: float,
                 *, defaults: dict[str, Any] | None = None):
        self.choice, self.ui, self.layout, self.err_const = choice, ui, layout, err_const
        # Saved defaults are proposed and validated again when each field is read.
        self.values: dict[str, Any] = dict(defaults or {})

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

    def _guide(self, field: Field, default: str = "") -> None:
        """Keep instructions beside the input they describe, including retries."""
        guides = {
            "bams": "Selezionare uno o piu' file BAM: incollare un percorso per volta e premere Invio.",
            "bam": "Incollare il percorso di un singolo file BAM. NIPAT preparera' il pileup per SNPcall.",
            "bamlist": "Scegliere un file di testo con un percorso BAM per riga, senza intestazione. I percorsi nella lista sono relativi alla cartella della lista stessa, oppure completi.",
            "reference": "Usare il FASTA della stessa assembly del BAM e del pannello. Accanto al FASTA deve essere presente il suo indice .fai; per FASTA BGZF serve anche .gzi.",
            "pileup": "Scegliere un pileup separato da tabulazioni, senza intestazione, con i nomi delle letture (QNAME) nella settima colonna; e' il formato samtools --output-QNAME.",
            "inputs": "Scegliere le tabelle dei campioni, una per volta. Colonne richieste: chr, pos1, pos2, N_REF, N_ALT, N_Other; separatore: tabulazione. La colonna ratio e' facoltativa.",
            "pairs": "Indicare gli identificativi madre:padre, separando le coppie con una virgola. Esempio: A1:A1,A2:A2. Con i prefissi predefiniti, A1:A1 usa MotherA1.txt e FatherA1.txt.",
            "mother_prefix": "Il nome del file e' prefisso + identificativo materno + .txt. Esempio: Mother + A1 diventa MotherA1.txt. :vuoto elimina il prefisso.",
            "father_prefix": "Il nome del file e' prefisso + identificativo paterno + .txt. Esempio: Father + A1 diventa FatherA1.txt. :vuoto elimina il prefisso.",
            "popfreq": "Scegliere la tabella delle frequenze di popolazione, separata da tabulazioni, con intestazione chr, pos1, pos2, Ref_f.pop, Alt_f.pop.",
            "cutoffs": "Per ciascun gruppo di siti inserire prima un'etichetta, poi il percorso del file di coordinate. Esempio di etichetta: pannello_A. Non usare virgole o '=' nell'etichetta.",
            "cutoff_file": "Scegliere il file di coordinate per l'etichetta appena inserita: colonne chr, pos1, pos2, oppure un pannello DNP a cinque colonne.",
            "cutoff_map": "Inserire etichetta=percorso, separando i gruppi con una virgola. Esempio: pannello_A=panels/a.txt,pannello_B=panels/b.txt. I file devono contenere le coordinate DNP.",
            "err_const": "Parametro del modello CPI: mantenere il valore proposto, salvo una scelta motivata per l'analisi. Per modificarlo usare un numero maggiore o uguale a zero, con il punto decimale.",
            "run_name": "Il nome identifica una nuova cartella di esecuzione. Le cartelle gia' esistenti non vengono sovrascritte.",
            "parallel": "Seriale elabora un campione alla volta; parallela elabora piu' campioni contemporaneamente e puo' richiedere piu' memoria.",
            "cutoff_mode": "Scegliere se usare tutti i siti disponibili o limitare l'analisi a uno o piu' gruppi di coordinate. Ogni modalita' richiedera' solo i propri input.",
        }
        if field.key == "mode":
            text = {
                "1": "Scegliere come fornire i BAM: inserire i percorsi uno per volta oppure usare un file che li elenca. In seguito saranno richiesti FASTA e pannello DNP.",
                "2": "Scegliere BAM e riferimento per preparare il pileup, oppure un pileup gia' disponibile. In entrambe le modalita' serve una lista SNP.",
                "3": "Scegliere singole tabelle dei campioni oppure una cartella da esaminare. In seguito sara' richiesto il pannello DNP.",
            }[self.choice]
        elif field.key == "input_dir":
            text = ("Scegliere la cartella delle tabelle dei campioni: saranno cercati file TXT e TSV anche nelle sottocartelle. Sono richieste le colonne chr, pos1, pos2, N_REF, N_ALT, N_Other; ratio e' facoltativa."
                    if self.choice == "3" else
                    "Scegliere la cartella delle tabelle cfDNA materno e presunto padre. I file devono chiamarsi prefisso + identificativo + .txt, per esempio MotherA1.txt e FatherA1.txt. Coppie e prefissi saranno richiesti nei passaggi successivi.")
        elif field.key == "panel":
            text = ("Scegliere un pannello DNP senza intestazione: cinque colonne chr, pos1, pos2, REF, ALT. Le due posizioni devono essere adiacenti e gli alleli di due basi."
                    if self.choice == "1" else
                    "Scegliere una tabella separata da tabulazioni con intestazione pos, ref, alt. Esempio di riga: chr1:1770788, C, G (con tabulazioni tra i valori)."
                    if self.choice == "2" else
                    "Scegliere le coordinate DNP: colonne chr, pos1, pos2, con o senza intestazione. E' accettato anche il pannello DNP a cinque colonne.")
        else:
            text = guides[field.key]
        self.ui.message(text, kind="muted")
        if field.kind in {"file", "files", "directory"}:
            self.ui.message("Incollare un percorso completo o relativo alla cartella corrente, anche tra virgolette. In Esplora file si puo' usare 'Copia come percorso'.", kind="muted")
        if field.kind == "choice":
            self.ui.message("Selezionare una voce del menu; Invio conferma la selezione proposta.", kind="muted")
        elif field.kind not in {"files", "cutoffs"}:
            if default:
                self.ui.message("Invio mantiene il valore tra parentesi quadre; per cambiarlo, scrivere il nuovo valore.", kind="muted")
            elif not field.required:
                self.ui.message("Invio senza testo assegna un nome automatico." if field.kind == "run" else "Invio lascia il campo vuoto.", kind="muted")
            else:
                self.ui.message("Inserire il valore richiesto e premere Invio. Il campo non puo' essere lasciato vuoto.", kind="muted")
        self.ui.message(":indietro torna al campo precedente; :annulla torna al menu. Nei campi di testo, 0 non annulla.", kind="muted")

    def _selected(self, field: Field, answer: str) -> None:
        label = next(label for key, label, _ in field.options if key == answer)
        if field.key == "mode":
            detail = {
                ("1", "1"): "La lista richiede almeno un BAM; dopo averlo aggiunto si puo' continuare con Invio o aggiungerne altri.",
                ("1", "2"): "L'input e' il percorso del file bamlist che elenca i BAM da analizzare.",
                ("2", "1"): "Sono richiesti BAM, FASTA indicizzato e lista SNP.",
                ("2", "2"): "Sono richiesti pileup con QNAME e lista SNP. Il FASTA non viene richiesto.",
                ("3", "1"): "La lista richiede almeno una tabella; dopo averla aggiunta si puo' continuare con Invio o aggiungerne altre.",
                ("3", "2"): "L'input e' il percorso della cartella che contiene le tabelle dei campioni.",
            }[(self.choice, answer)]
        elif field.key == "cutoff_mode":
            detail = {
                "0": "Non occorre fornire un file di coordinate aggiuntivo.",
                "1": "E' richiesto il percorso di un pannello di coordinate DNP.",
                "2": "Ogni etichetta identifica un file di coordinate.",
                "3": "Le associazioni etichetta=percorso sono separate da virgole.",
            }[answer]
        else:
            detail = "La modalita' scelta sara' riportata nel riepilogo prima dell'avvio."
        self.ui.message(f"Selezione: {label}. {detail}", kind="muted")

    def _text(self, field: Field, default: str) -> str:
        while True:
            answer = navigation(self.ui.prompt(field.label, default=default,
                                               path=field.kind in {"file", "directory"}))
            if answer.casefold() == ":vuoto":
                answer = ""
            elif not answer:
                answer = default
            if answer or not field.required:
                return answer
            self.ui.message("Nessun valore inserito. Compilare questo campo per proseguire, oppure usare :indietro o :annulla.", kind="muted")

    def _file(self, field: Field, value: str) -> Path:
        path = require_file(Path(unquote(value)), field.label)
        if field.check:
            field.check(path)
        return path

    def _collection(self, field: Field) -> list:
        current = list(self.values.get(field.key, []))
        self._guide(field)
        if current:
            self.ui.message(self.format_value(current))
            while True:
                action = navigation(self.ui.menu("Elenco gia' inserito", [
                    ("1", "Mantieni", ""), ("2", "Sostituisci", ""),
                    ("3", "Aggiungi", ""),
                ] + ([("4", "Rimuovi il valore predefinito", "")] if not field.required else [])
                  + [("0", "Indietro", "")], default="1"))
                if action == "0":
                    raise Back
                if action == "1":
                    try:
                        for item in current:
                            if field.kind == "cutoffs":
                                self._file(Field("cutoff_file", "File cutoff", "file",
                                                 check=read_position_panel), str(item[1]))
                            else:
                                self._file(field, str(item))
                    except (ValidationError, OSError, ValueError, csv.Error) as exc:
                        self.ui.message(str(exc), kind="error")
                        self.ui.message("Sostituire l'elenco per correggere i percorsi non disponibili.", kind="muted")
                        continue
                    return current
                if action == "4" and not field.required:
                    return []
                if action in {"2", "3"}:
                    current = [] if action == "2" else current
                    break
                self.ui.message("Scegliere una delle opzioni indicate.", kind="error")
        while True:
            try:
                if current:
                    self.ui.message(f"Elementi inseriti: {len(current)}. Aggiungerne un altro oppure premere Invio senza testo per continuare.", kind="muted")
                else:
                    self.ui.message("Inserire il primo elemento per iniziare la lista. Invio senza testo mantiene aperto questo passaggio."
                                    if field.required else "Inserire il primo elemento oppure premere Invio per non salvare un elenco predefinito.", kind="muted")
                if field.kind == "cutoffs":
                    label = navigation(self.ui.prompt("Altra etichetta cutoff (Invio per continuare)" if current else "Prima etichetta cutoff"))
                    if label.casefold() == ":vuoto" and not field.required:
                        return []
                    if not label:
                        if current or not field.required:
                            return current
                        continue
                    if any(c in label for c in ",=") or any(ord(c) < 32 for c in label):
                        raise ValidationError("Etichetta cutoff non valida: evitare virgole e '='.")
                    if label in {item[0] for item in current}:
                        raise ValidationError("Etichetta cutoff duplicata.")
                    source = self._read(Field("cutoff_file", "File cutoff", "file", check=read_position_panel))
                    item = (label, source)
                else:
                    prompt = ("Altro file (Invio per continuare)" if current else
                              "Percorso del primo BAM" if field.key == "bams" else
                              "Percorso del primo pileup SNP" if field.key == "pileups" else "Percorso della prima tabella")
                    raw = navigation(self.ui.prompt(prompt, path=True))
                    if not raw:
                        if current:
                            return current
                        continue
                    item = self._file(field, raw)
                    if item in current:
                        raise ValidationError("Il file e' gia' presente nella lista.")
                current.append(item)
                self.values[field.key] = list(current)
                self.ui.message(f"Aggiunto ({len(current)}): {self.format_value(item)}", kind="success")
            except (ValidationError, OSError, ValueError, csv.Error) as exc:
                self.ui.message(str(exc), kind="error")
                self._guide(field)

    def _read(self, field: Field) -> Any:
        if field.kind in {"files", "cutoffs"}:
            return self._collection(field)
        existing = self.values.get(field.key, field.default)
        default = "" if existing is None else str(existing)
        while True:
            self._guide(field, default)
            try:
                if field.kind == "choice":
                    answer = navigation(self.ui.menu(field.label, list(field.options), default=default))
                    if answer not in {item[0] for item in field.options}:
                        raise ValidationError("Scegliere una delle opzioni indicate.")
                    self._selected(field, answer)
                    return answer
                answer = self._text(field, default)
                if field.kind == "file":
                    return self._file(field, answer) if answer or field.required else None
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
            self.ui.message("Controllare gli input. 'Modifica un campo' permette di correggerli conservando gli altri valori.", kind="muted")
            self.ui.message("La conferma preparera' file e comandi, senza eseguire il calcolo scientifico." if dry_run else
                            "Il calcolo scientifico iniziera' solo confermando 'Avvia analisi'.", kind="muted")
            choice = self.ui.menu("Come procedere?", [
                ("1", "Prepara dry-run" if dry_run else "Avvia analisi", "Con i valori mostrati"),
                ("2", "Modifica un campo", "Gli altri valori vengono conservati"),
                ("0", "Annulla", "Torna al menu senza avviare"),
            ], default="0")
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
