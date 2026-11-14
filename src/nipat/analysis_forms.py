"""Guided inputs for the five-module analysis graph and postnatal CPI."""
from __future__ import annotations

from pathlib import Path
import re

from nipat.errors import ValidationError
from nipat.execution.analysis_plan import FAMILY_ROLES, active_analysis_branches, validate_families
from nipat.wizard_forms import (Back, Field, WorkflowForm, check_name, check_popfreq,
                                 check_reference, check_count_panel, navigation, unquote)
from nipat.validation.files import require_file, require_snp_pileup
from nipat_scientific.cpin import normalize_trios
from nipat_scientific.files import require_count_input
from nipat_scientific.panels import read_dnp_list, read_snp_positions


_ANALYSES = {"0": [], "1": ["contamination"], "2": ["cpi"], "3": ["cpin"],
             "4": ["contamination", "cpi"], "5": ["contamination", "cpin"],
             "6": ["cpi", "cpin"], "7": ["contamination", "cpi", "cpin"]}
_FAMILY_FIELDS = {"pairs": "cpi", "trios": "cpin"}


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

    def _marker_selection(self):
        marker = "snp" if self.values.get("source") == "pileup" else self.values.get("marker", "both")
        return ("DNP", "SNP") if marker == "both" else (marker.upper(),)

    def _caller(self):
        if self.values.get("source") == "tables":
            return "tables"
        markers = self._marker_selection()
        return "both" if len(markers) == 2 else markers[0].lower()

    def _analysis_options(self):
        selected = self.values.get("analyses", "7")
        if selected != "8":
            return {"analyses": _ANALYSES[selected].copy()}
        overrides = {}
        for marker in self._marker_selection():
            key = marker.lower() + "_analyses"
            overrides[key] = _ANALYSES[self.values.get(key, "0")].copy()
        analyses = [name for name in _ANALYSES["7"] if any(name in names for names in overrides.values())]
        return {"analyses": analyses, **overrides}

    def _active_branches(self):
        caller = self._caller()
        return active_analysis_branches(caller, **self._analysis_options(),
                                        table_markers=self._marker_selection() if caller == "tables" else ())

    def _sample_fields(self):
        source = self.values.get("source", "bam")
        if source == "tables":
            return {marker: marker.lower() + "_tables" for marker in self._active_branches()}
        return {marker: ("pileups" if source == "pileup" else "samples") for marker in self._active_branches()}

    def _family_samples(self, analysis):
        inputs = self._sample_fields()
        return {marker: {identifier for identifier, _ in self.values.get(inputs[marker], [])}
                for marker, analyses in self._active_branches().items() if analysis in analyses}

    def _check_families(self, key, entries, samples):
        for marker, ids in samples.items():
            validate_families(entries, FAMILY_ROLES[_FAMILY_FIELDS[key]], ids, marker)

    def _validate_review(self):
        if self._caller() == "tables" and not self._active_branches():
            raise ValidationError("Per tabelle esistenti selezionare almeno un'analisi in un ramo.")
        for key, analysis in _FAMILY_FIELDS.items():
            samples = self._family_samples(analysis)
            if samples:
                self._check_families(key, self.values.get(key, []), samples)

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
        no_analysis = (("0", "Nessuna analisi", "Disattiva le analisi per il ramo") if v.get("source") == "tables"
                       else ("0", "Solo calling", "Nessuna analisi successiva"))
        fields.append(Field("analyses", "Analisi successive", "choice", "7", options=(
            no_analysis,
            ("1", "Contamination", "Tutti i campioni selezionati"),
            ("2", "CPI prenatale", "Coppie cfDNA materno / padre"),
            ("3", "CPIN postnatale", "Trii madre / padre / figlio"),
            ("4", "Contamination e CPI", "Entrambe"),
            ("5", "Contamination e CPIN", "Entrambe"),
            ("6", "CPI e CPIN", "Entrambe, con ruoli espliciti distinti"),
            ("7", "Contamination, CPI e CPIN", "Tutte le analisi"),
            ("8", "Analisi diverse per SNP e DNP", "Personalizza separatamente ogni ramo"))))
        if v.get("analyses") == "8":
            choices = fields[-1].options[:-1]
            for marker in self._marker_selection():
                fields.append(Field(f"{marker.lower()}_analyses", f"Analisi del ramo {marker}", "choice", "0", options=choices))
        branches = self._active_branches()
        if v.get("source", "bam") == "bam":
            fields += [Field("samples", "Campioni BAM con ID", "identified"),
                       Field("reference", "FASTA indicizzato", "file", check=check_reference)]
        elif v.get("source") == "pileup":
            fields.append(Field("pileups", "Pileup SNP con ID", "identified", check=require_snp_pileup))
        else:
            for marker, selected in branches.items():
                fields.append(Field(f"{marker.lower()}_tables", f"Tabelle {marker} con ID", "identified",
                                    check=lambda path, marker=marker, selected=selected:
                                    require_count_input(path, marker, cpi=bool(set(selected) & FAMILY_ROLES.keys()))))
        for marker in branches:
            if v.get("source") != "tables":
                fields.append(Field(f"{marker.lower()}_panel", f"Pannello di calling {marker}", "file",
                                    check=read_dnp_list if marker == "DNP" else
                                    lambda path: read_snp_positions(path, for_bed=v.get("source") == "bam")))
        analyses = set().union(*branches.values())
        if "cpi" in analyses:
            fields.append(Field("pairs", "Coppie CPI: ID, cfDNA materno, padre", "families"))
        if "cpin" in analyses:
            fields.append(Field("trios", "Trii CPIN: ID, madre, padre, figlio", "families"))
        for marker, selected_analyses in branches.items():
            prefix = marker.lower()
            if "cpi" in selected_analyses or "cpin" in selected_analyses:
                fields.append(Field(f"{prefix}_popfreq", f"Frequenze {marker} per CPI/CPIN", "file", check=check_popfreq))
            if "contamination" in selected_analyses:
                fields.append(Field(f"{prefix}_contamination_panel", f"Pannello Contamination {marker}", "file",
                                    required=v.get("source") == "tables", check=check_count_panel))
            if "cpi" in selected_analyses:
                fields.append(Field(f"{prefix}_cpi_cutoffs", f"Cutoff CPI {marker} (Invio = ALL)", "cutoffs", required=False))
            if "cpin" in selected_analyses:
                fields.append(Field(f"{prefix}_cpin_panel", f"Pannello CPIN {marker} con REF/ALT (facoltativo)", "file",
                                    required=False, check=check_count_panel))
        return fields + [Field("run_name", "Nome nuova esecuzione (vuoto = automatico)", "run", required=False)]

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
        samples = self._family_samples(_FAMILY_FIELDS[field.key]) if field.kind == "families" else {}
        available = set.intersection(*samples.values()) if samples else set()
        if samples:
            self.ui.message("ID validi nei rami selezionati: " + (", ".join(sorted(available)) or "nessuno"))
        while current:
            self.ui.message(self.format_value(current))
            answer = navigation(self.ui.menu("Elenco inserito", [("1", "Mantieni", ""),
                                  ("2", "Sostituisci", ""), ("3", "Aggiungi", "")], default="1"))
            if answer == "2":
                current = []
                break
            if answer not in {"1", "3"}:
                raise Back
            try:
                self._check_families(field.key, current, samples)
            except ValidationError as exc:
                self.ui.message(str(exc), kind="error")
                continue
            if answer == "1":
                return current
            break
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
        for key in dict.fromkeys(self._sample_fields().values()):
            for identifier, path in self.values.get(key, []):
                self.ui.message(f"  {identifier}: {Path(path).name}")
        self.ui.message("SNP e DNP vengono analizzati separatamente. Contamination non filtra gli input CPI o CPIN.", kind="muted")

    def arguments(self):
        selection = {"source", "marker", "analyses", "dnp_analyses", "snp_analyses"}
        arguments = {field.key: self.values.get(field.key) for field in self.fields() if field.key not in selection}
        for name in ("dnp_cpi_cutoffs", "snp_cpi_cutoffs"):
            if name in arguments and not arguments[name]:
                arguments[name] = None
        return {"caller": self._caller(), **self._analysis_options(), **arguments}
