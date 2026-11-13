"""Guided inputs for the five-module analysis graph and postnatal CPI."""
from __future__ import annotations

from pathlib import Path
import re

from nipat.errors import ValidationError
from nipat.wizard_forms import (Back, Field, WorkflowForm, check_name, check_popfreq,
                                 check_reference, check_count_panel, navigation, unquote)
from nipat.validation.files import require_file, require_snp_pileup
from nipat_scientific.cpin import normalize_trios
from nipat_scientific.files import require_count_input
from nipat_scientific.panels import read_dnp_list, read_snp_positions


class CpinForm(WorkflowForm):
    @property
    def title(self):
        return "CPIN / CPI postnatale"

    def fields(self):
        return [Field("input_dir", "Cartella tabelle madre, padre e figlio", "directory"),
                Field("trios", "Trii madre:padre:figlio (esempio M1:F1:C1,M2:F2:C2)"),
                Field("mother_prefix", "Prefisso madre", default="Mother", required=False, check=check_name),
                Field("father_prefix", "Prefisso padre", default="Father", required=False, check=check_name),
                Field("child_prefix", "Prefisso figlio", default="Child", required=False, check=check_name),
                Field("popfreq", "Frequenze di popolazione SNP o DNP", "file", check=check_popfreq),
                Field("panel", "Pannello SNP/DNP con REF e ALT (facoltativo)", "file", required=False,
                      check=check_count_panel),
                Field("run_name", "Nome nuova esecuzione (vuoto = automatico)", "run", required=False)]

    def _guide(self, field, default=""):
        descriptions = {
            "input_dir": "Le tabelle devono avere conteggi allelici, alleli REF/ALT e coordinate SNP o DNP coerenti.",
            "trios": "Ogni trio indica esplicitamente gli ID di madre, padre e figlio. Con i prefissi proposti M1:F1:C1 usa MotherM1.txt, FatherF1.txt e ChildC1.txt. Gli stessi ID locali sono ammessi con prefissi diversi, purché i tre file rappresentino campioni distinti. Separare i trii con una virgola.",
            "child_prefix": "Il file del figlio si chiama prefisso + ID + .txt. :vuoto elimina il prefisso.",
            "panel": "Facoltativo: limita ai siti e alleli del pannello. SNP: chr, pos, ref, alt; DNP: chr, pos1, pos2, REF, ALT. Senza pannello usa i siti disponibili.",
        }
        if field.key in descriptions:
            self.ui.message(descriptions[field.key], kind="muted")
            self.ui.message(":indietro torna al campo precedente; :annulla torna al menu.", kind="muted")
        else:
            super()._guide(field, default)

    def arguments(self):
        return {key: self.values[key] for key in (
            "input_dir", "trios", "mother_prefix", "father_prefix", "child_prefix", "popfreq", "panel", "run_name")}

    def _show_sample_names(self):
        try:
            _, names = normalize_trios(self.values["trios"], self.values["mother_prefix"],
                                       self.values["father_prefix"], self.values["child_prefix"])
        except ValidationError as exc:
            self.ui.message(str(exc), kind="error")
            return
        self.ui.message("Tabelle richieste: " + ", ".join(names))


class AnalysisForm(WorkflowForm):
    """Select callers, any consumer subset, explicit roles and typed resources."""
    @property
    def title(self):
        return "Workflow / SNP e DNP verso Contamination, CPI e CPIN"

    def _branches(self):
        selected = self.values.get("marker", "both")
        return ("dnp", "snp") if selected == "both" else (selected,)

    def fields(self):
        v = self.values
        fields = [Field("source", "Origine dei conteggi", "choice", "bam", options=(
            ("bam", "BAM", "Calling automatico DNP e/o SNP"),
            ("pileup", "Pileup SNP", "SNPcall da pileup con QNAME"),
            ("tables", "Tabelle esistenti", "Usa direttamente conteggi SNP/DNP")))]
        if v.get("source") != "pileup":
            fields.append(Field("marker", "Tipo di marcatori", "choice", "both", options=(
                ("dnp", "DNP", "Solo dinucleotidi"), ("snp", "SNP", "Solo SNP"),
                ("both", "DNP e SNP", "Due rami separati nello stesso workflow"))))
        fields.append(Field("analyses", "Analisi successive", "choice", "7", options=(
            ("0", "Solo calling", "Nessuna analisi successiva"),
            ("1", "Contamination", "Tutti i campioni selezionati"),
            ("2", "CPI prenatale", "Coppie cfDNA materno / padre"),
            ("3", "CPIN postnatale", "Trii madre / padre / figlio"),
            ("4", "Contamination e CPI", "Entrambe"),
            ("5", "Contamination e CPIN", "Entrambe"),
            ("6", "CPI e CPIN", "Entrambe, con ruoli espliciti distinti"),
            ("7", "Contamination, CPI e CPIN", "Tutte le analisi"),
            ("8", "Analisi diverse per SNP e DNP", "Personalizza separatamente ogni ramo"))))
        branches = ("snp",) if v.get("source") == "pileup" else self._branches()
        if v.get("analyses") == "8":
            choices = fields[-1].options[:-1]
            for marker in branches:
                fields.append(Field(f"{marker}_analyses", f"Analisi del ramo {marker.upper()}", "choice", "0", options=choices))
        if v.get("source", "bam") == "bam":
            fields += [Field("samples", "Campioni BAM con ID", "identified"),
                       Field("reference", "FASTA indicizzato", "file", check=check_reference)]
        elif v.get("source") == "pileup":
            fields.append(Field("pileups", "Pileup SNP con ID", "identified", check=require_snp_pileup))
        else:
            for marker in branches:
                fields.append(Field(f"{marker}_tables", f"Tabelle {marker.upper()} con ID", "identified",
                                    check=lambda path, marker=marker: require_count_input(path, marker.upper(), cpi=bool(set(self._analyses(marker)) & {"cpi", "cpin"}))))
        for marker in branches:
            if v.get("source") != "tables":
                fields.append(Field(f"{marker}_panel", f"Pannello di calling {marker.upper()}", "file",
                                    check=read_dnp_list if marker == "dnp" else
                                    lambda path: read_snp_positions(path, for_bed=v.get("source") == "bam")))
        analyses = self._analyses()
        if "cpi" in analyses:
            fields.append(Field("pairs", "Coppie CPI: ID, cfDNA materno, padre", "families"))
        if "cpin" in analyses:
            fields.append(Field("trios", "Trii CPIN: ID, madre, padre, figlio", "families"))
        for marker in branches:
            selected_analyses = self._analyses(marker)
            if "cpi" in selected_analyses or "cpin" in selected_analyses:
                fields.append(Field(f"{marker}_popfreq", f"Frequenze {marker.upper()} per CPI/CPIN", "file", check=check_popfreq))
            if "contamination" in selected_analyses:
                fields.append(Field(f"{marker}_contamination_panel", f"Pannello Contamination {marker.upper()}", "file",
                                    required=v.get("source") == "tables", check=check_count_panel))
            if "cpi" in selected_analyses:
                fields.append(Field(f"{marker}_cpi_cutoffs", f"Cutoff CPI {marker.upper()} (Invio = ALL)", "cutoffs", required=False))
            if "cpin" in selected_analyses:
                fields.append(Field(f"{marker}_cpin_panel", f"Pannello CPIN {marker.upper()} con REF/ALT (facoltativo)", "file",
                                    required=False, check=check_count_panel))
        return fields + [Field("run_name", "Nome nuova esecuzione (vuoto = automatico)", "run", required=False)]

    def _analyses(self, marker=None):
        combinations = {"0": [], "1": ["contamination"], "2": ["cpi"], "3": ["cpin"],
                        "4": ["contamination", "cpi"], "5": ["contamination", "cpin"],
                        "6": ["cpi", "cpin"], "7": ["contamination", "cpi", "cpin"]}
        selected = self.values.get("analyses", "7")
        if selected != "8":
            return combinations[selected]
        if marker:
            return combinations[self.values.get(marker + "_analyses", "0")]
        branches = ("snp",) if self.values.get("source") == "pileup" else self._branches()
        return [name for name in ("contamination", "cpi", "cpin")
                if any(name in self._analyses(branch) for branch in branches)]

    def _guide(self, field, default=""):
        if field.key in {"reference", "run_name", "cutoff_file"}:
            super()._guide(field, default)
            return
        self.ui.message(field.label, kind="muted")
        if field.key == "samples" or field.key.endswith("tables") or field.key == "pileups":
            self.ui.message("Per ogni file assegnare un ID univoco e poi scegliere il percorso. Gli ID saranno usati per dichiarare i ruoli familiari. Nei due rami usare gli stessi ID per gli stessi campioni biologici.")
        elif field.key in {"pairs", "trios"}:
            self.ui.message("Usare gli ID dei campioni elencati, senza percorsi. I ruoli non vengono dedotti dai nomi dei file. Il cfDNA materno del CPI prenatale e il campione madre del CPIN possono essere campioni diversi.")
        elif field.key.endswith("cpin_panel"):
            self.ui.message("Pannello facoltativo con coordinate e alleli REF/ALT; Invio include tutti i siti disponibili.")
        elif field.key.endswith("contamination_panel") and not field.required:
            self.ui.message("Invio usa il pannello di calling del ramo corrispondente.")
        elif field.kind == "cutoffs":
            self.ui.message("Ogni etichetta identifica un pannello di coordinate. Invio senza elementi usa ALL.")
        self.ui.message(":indietro torna al campo precedente; :annulla torna al menu. Invio mantiene un valore proposto.", kind="muted")

    def _selected(self, field, answer):
        if field.key == "source" and answer == "pileup":
            self.values["marker"] = "snp"
        self.ui.message("Selezione: " + next(label for key, label, _ in field.options if key == answer))

    def _read(self, field):
        if field.kind == "choice" and any(len(key) > 1 for key, _, _ in field.options):
            options = list(field.options)
            current = self.values.get(field.key, field.default)
            default = str(next((index for index, item in enumerate(options, 1) if item[0] == current), 1))
            while True:
                self._guide(field)
                selected = navigation(self.ui.menu(field.label,
                    [(str(index), label, description) for index, (_, label, description) in enumerate(options, 1)],
                    default=default))
                if selected not in {str(index) for index in range(1, len(options) + 1)}:
                    self.ui.message("Scegliere una delle opzioni indicate.", kind="error")
                    continue
                answer = options[int(selected) - 1][0]
                self._selected(field, answer)
                return answer
        if field.kind not in {"identified", "families"}:
            return super()._read(field)
        self._guide(field)
        current = list(self.values.get(field.key, []))
        if current:
            self.ui.message(self.format_value(current))
            answer = navigation(self.ui.menu("Elenco inserito", [("1", "Mantieni", ""),
                                  ("2", "Sostituisci", ""), ("3", "Aggiungi", "")], default="1"))
            if answer == "1":
                return current
            if answer == "2":
                current = []
            elif answer != "3":
                raise Back
        available = {identifier for key in ("samples", "pileups", "dnp_tables", "snp_tables")
                     for identifier, _ in self.values.get(key, [])}
        while True:
            try:
                identifier = navigation(self.ui.prompt("ID (Invio conclude l'elenco)"))
                if not identifier:
                    if current:
                        return current
                    self.ui.message("Inserire almeno un elemento.", kind="error")
                    continue
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}", identifier):
                    raise ValidationError("ID: 1-48 lettere ASCII, numeri, '_' o '-', iniziando con una lettera.")
                if identifier.casefold() in {row[0].casefold() for row in current}:
                    raise ValidationError("ID duplicato.")
                if field.kind == "identified":
                    self._path_guide()
                    path = require_file(Path(unquote(navigation(self.ui.prompt("File del campione", path=True)))), "Campione")
                    if field.check:
                        field.check(path)
                    row = (identifier, path)
                else:
                    self.ui.message("ID disponibili: " + ", ".join(sorted(available)))
                    roles = ("cfDNA materno", "padre") if field.key == "pairs" else ("madre", "padre", "figlio")
                    members = []
                    for role in roles:
                        member = navigation(self.ui.prompt("ID campione " + role))
                        if member not in available:
                            raise ValidationError(f"ID campione sconosciuto: {member}")
                        members.append(member)
                    if len(set(members)) != len(members):
                        raise ValidationError("I ruoli della stessa famiglia richiedono campioni distinti.")
                    row = (identifier, *members)
                current.append(row)
                self.values[field.key] = list(current)
                self.ui.message("Aggiunto: " + str(row))
            except (ValidationError, OSError, ValueError) as exc:
                self.ui.message(str(exc), kind="error")

    @staticmethod
    def format_value(value):
        if isinstance(value, (list, tuple)):
            if isinstance(value, tuple):
                return " | ".join(str(part) for part in value)
            return "\n".join(AnalysisForm.format_value(row) for row in value)
        return WorkflowForm.format_value(value)

    def _show_sample_names(self):
        for key in ("samples", "pileups", "dnp_tables", "snp_tables"):
            for identifier, path in self.values.get(key, []):
                self.ui.message(f"  {identifier}: {Path(path).name}")
        self.ui.message("SNP e DNP vengono analizzati separatamente. Contamination non filtra gli input CPI o CPIN.", kind="muted")

    def arguments(self):
        source = self.values["source"]
        caller = "tables" if source == "tables" else "snp" if source == "pileup" else self.values["marker"]
        active = {field.key for field in self.fields()}
        names = ("samples", "pileups", "dnp_tables", "snp_tables", "pairs", "trios", "reference",
                 "dnp_panel", "snp_panel", "dnp_popfreq", "snp_popfreq", "dnp_contamination_panel",
                 "snp_contamination_panel", "dnp_cpi_cutoffs", "snp_cpi_cutoffs", "dnp_cpin_panel", "snp_cpin_panel")
        arguments = {name: self.values.get(name) for name in names if name in active}
        for name in ("dnp_cpi_cutoffs", "snp_cpi_cutoffs"):
            if not arguments.get(name):
                arguments[name] = None
        if self.values.get("analyses") == "8":
            for marker in (("snp",) if source == "pileup" else self._branches()):
                arguments[marker + "_analyses"] = self._analyses(marker)
        return {"caller": caller, "analyses": self._analyses(), "run_name": self.values["run_name"], **arguments}
