"""Presentation of the read-only scientific catalog, shared by CLI and menu."""

from __future__ import annotations

import json

from nipat.terminal import Terminal
from nipat_scientific.catalog import WORKFLOWS, load_catalog


TEXT = {
    "it": {
        "title": "Catalogo scientifico",
        "notice": "Descrizione dei sorgenti distribuiti, non dei valori di un run. Le regole interne sono consultabili e non vengono modificate.",
        "source": "Sorgente R",
        "parameters": "Opzioni pubbliche R e corrispondenza NIPAT",
        "rules": "Regole interne R (sola lettura)",
        "preparation": "Preparazione degli input",
        "default": "Default R", "required": "Obbligatorio in R", "yes": "si", "no": "no",
        "unset": "non specificato", "position": "argomento posizionale",
        "mapping": "Gestione NIPAT", "cli": "Opzioni CLI", "request": "Campi della richiesta",
        "direct": "diretta", "adapted": "adattata", "managed": "gestita da NIPAT",
        "missing": "non esposta", "value": "Valore o regola", "scope": "Ambito",
        "origin": "Origine", "evidence": "Riferimento", "all": "Tutte le sezioni",
        "back": "Indietro", "language": "Lingua / Language", "choose": "Scegliere una voce indicata.",
    },
    "en": {
        "title": "Scientific catalog",
        "notice": "Description of the distributed sources, not the effective values of a run. Internal rules are read-only and are not changed.",
        "source": "R source",
        "parameters": "Public R options and NIPAT mapping",
        "rules": "Internal R rules (read-only)",
        "preparation": "Input preparation",
        "default": "R default", "required": "Required by R", "yes": "yes", "no": "no",
        "unset": "not specified", "position": "positional argument",
        "mapping": "NIPAT mapping", "cli": "CLI options", "request": "Request fields",
        "direct": "direct", "adapted": "adapted", "managed": "managed by NIPAT",
        "missing": "not exposed", "value": "Value or rule", "scope": "Scope",
        "origin": "Origin", "evidence": "Reference", "all": "All sections",
        "back": "Back", "language": "Language / Lingua", "choose": "Choose one of the listed options.",
    },
}
SECTIONS = {"parameters": "public_parameters", "rules": "fixed_settings",
            "preparation": "preparation_settings"}


def _value(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def catalog_lines(catalog: dict, *, language: str = "it", section: str = "all") -> list[str]:
    """Translate presentation only; preserve identifiers, formulas and values."""
    if language not in TEXT or section not in {*SECTIONS, "all"}:
        raise ValueError("Unsupported catalog language or section.")
    text = TEXT[language]
    lines = [text["title"], text["notice"]]
    for workflow, document in catalog["workflows"].items():
        source = document["source"]
        lines.extend(["", workflow, f"{text['source']}: {source['path']}",
                      f"SHA-256: {source['sha256']}"])
        for label, group in SECTIONS.items():
            if section not in {"all", label}:
                continue
            lines.extend(["", text[label]])
            for entry in document[group]:
                lines.extend(["", f"[{entry['id']}] {entry['description'][language]}"])
                if label == "parameters":
                    default = text["unset"] if entry["default"] is None else _value(entry["default"])
                    native = ", ".join(entry["r_names"])
                    if entry["position"] is not None:
                        native += f" ({text['position']} {entry['position']})"
                    lines.extend([f"  R: {native}; {text['default']}: {default}; "
                                  f"{text['required']}: {text['yes'] if entry['required'] else text['no']}",
                                  f"  {text['mapping']}: {text[entry['nipat']['mapping']]}; "
                                  f"{text['cli']}: {', '.join(entry['nipat']['cli']) or '-'}",
                                  f"  {text['request']}: {', '.join(entry['nipat']['request_fields']) or '-'}"])
                else:
                    lines.append(f"  {text['value']}: {_value(entry['value'])}")
                if label == "preparation":
                    lines.extend([f"  {text['origin']}: {entry['origin']}; {text['scope']}: {entry['applies_to']}"])
                    evidence = entry["evidence"]
                    start, end = evidence["source_lines"]
                    lines.append(f"  {text['evidence']}: {evidence['path']}:{start}-{end}")
                    if evidence.get("url"):
                        lines.append(f"  {evidence['url']}")
                else:
                    start, end = entry["source_lines"]
                    lines.append(f"  {text['evidence']}: {source['path']}:{start}-{end}")
    return lines


def show_catalog(ui: Terminal) -> None:
    """Browse without starting a runtime or writing scientific preferences."""
    language = "it"
    while True:
        text = TEXT[language]
        choice = ui.menu(text["title"], [
            *((str(index), workflow, "") for index, workflow in enumerate(WORKFLOWS, 1)),
            ("l", text["language"], "IT / EN"), ("0", text["back"], ""),
        ], default="0").strip().lower()
        if choice in {"0", ":indietro", ":annulla"}:
            return
        if choice == "l":
            language = "en" if language == "it" else "it"
            continue
        if choice not in {"1", "2", "3", "4"}:
            ui.message(text["choose"], kind="muted")
            continue
        workflow = WORKFLOWS[int(choice) - 1]
        document = load_catalog(workflow)
        while True:
            selected = ui.menu(workflow, [
                ("1", text["parameters"], ""), ("2", text["rules"], ""),
                ("3", text["preparation"], ""), ("0", text["back"], ""),
            ], default="0").strip().lower()
            if selected in {"0", ":indietro", ":annulla"}:
                break
            section = {"1": "parameters", "2": "rules", "3": "preparation"}.get(selected)
            if section is None:
                ui.message(text["choose"], kind="muted")
                continue
            for line in catalog_lines(document, language=language, section=section):
                ui.message(line)
