"""Scientific settings shared by direct commands and the guided client."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from nipat.errors import ValidationError
from nipat_scientific.settings import defaults, describe_settings, normalize_settings

WORKFLOWS = ("dnp-call", "snp-call", "contamination", "cpi", "cpin")


def normalize_config(value: object) -> dict:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValidationError("La configurazione scientifica deve essere un oggetto JSON per modulo.")
    unknown = set(value) - set(WORKFLOWS)
    if unknown:
        raise ValidationError("Moduli scientifici sconosciuti: " + ", ".join(sorted(unknown)))
    for workflow, settings in value.items():
        if not isinstance(settings, dict):
            raise ValidationError(f"{workflow}: atteso un oggetto JSON di parametri.")
        normalize_settings(workflow, settings)
    return copy.deepcopy(value)


def load_scientific_config(path: Path | None = None, overrides: list[str] | None = None) -> dict:
    config = {}
    if path is not None:
        try:
            config = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Configurazione scientifica JSON non valida: {path}: {exc}") from exc
        config = normalize_config(config)
    for override in overrides or []:
        if "=" not in override or "." not in override.split("=", 1)[0]:
            raise ValidationError("Usare --set modulo.parametro=valore, per esempio snp-call.min_base_quality=20.")
        target, raw = override.split("=", 1)
        workflow, key = target.split(".", 1)
        if workflow not in WORKFLOWS or not key:
            raise ValidationError(f"Parametro scientifico non valido: {target}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        config.setdefault(workflow, {})[key] = value
    return normalize_config(config)


def effective_config(config: dict, workflows=None) -> dict:
    return {workflow: normalize_settings(workflow, config.get(workflow))
            for workflow in (workflows or WORKFLOWS)}


def settings_lines(workflow: str, config: dict | None = None) -> list[str]:
    descriptor = describe_settings(workflow)
    effective = normalize_settings(workflow, (config or {}).get(workflow))
    lines = [f"{workflow}: parametri scientifici configurabili"]
    for key, definition in descriptor["parameters"].items():
        lines.append(f"  {key} = {json.dumps(effective[key], ensure_ascii=False)} "
                     f"(predefinito: {json.dumps(definition['default'], ensure_ascii=False)})")
        lines.append(f"    {definition['description']}")
        bounds = [f"tipo: {definition['type']}"]
        for key, label in (("minimum", "minimo"), ("maximum", "massimo")):
            if key in definition:
                boundary = "escluso" if definition.get("exclusive_" + key) else "incluso"
                bounds.append(f"{label} {boundary}: {definition[key]}")
        if "choices" in definition:
            bounds.append(f"valori: {definition['choices']}")
        if definition.get("unit"):
            bounds.append(f"unita': {definition['unit']}")
        if bounds:
            lines.append("    " + "; ".join(bounds))
    if descriptor.get("constraints"):
        lines.append("  Vincoli fra parametri:")
        lines.extend("    " + constraint for constraint in descriptor["constraints"])
    if descriptor.get("source_files"):
        lines.append("  Sorgenti: " + ", ".join(descriptor["source_files"]))
    lines.append("  Costanti e regole del modello (consultabili):")
    for key, definition in descriptor.get("constants", {}).items():
        lines.append(f"    {key} = {definition['value']}: {definition['description']}")
    return lines


def edit_scientific_settings(ui, config: dict) -> dict:
    """Review all defaults/constants and edit a validated per-run copy."""
    candidate = normalize_config(config)
    while True:
        selected = ui.menu("Parametri scientifici e costanti", [
            (str(index), workflow, "Mostra valori e modifica i parametri")
            for index, workflow in enumerate(WORKFLOWS, 1)
        ] + [("9", "Applica", "Usa questi valori per questa esecuzione"),
             ("0", "Annulla modifiche", "Conserva i valori precedenti")], default="0").strip()
        if selected in {"0", ":indietro", ":annulla"}:
            return config
        if selected == "9":
            return candidate
        if selected not in {str(index) for index in range(1, len(WORKFLOWS) + 1)}:
            ui.message("Scegliere un modulo, Applica oppure Annulla.", kind="error")
            continue
        workflow = WORKFLOWS[int(selected) - 1]
        for line in settings_lines(workflow, candidate):
            ui.message(line)
        ui.message("Scrivere parametro=valore (numeri, true/false, oppure testo). "
                   "Invio torna ai moduli; parametro=:default ripristina il valore distribuito.")
        while True:
            answer = ui.prompt("Parametro=valore").strip()
            if answer in {"", ":indietro", ":annulla"}:
                break
            try:
                if "=" not in answer:
                    raise ValidationError("Indicare parametro=valore.")
                key, raw = answer.split("=", 1)
                key, raw = key.strip(), raw.strip()
                if raw == ":default":
                    if key not in defaults(workflow):
                        raise ValidationError(f"Parametro sconosciuto: {key}")
                    restored = copy.deepcopy(candidate)
                    restored.setdefault(workflow, {}).pop(key, None)
                    candidate = normalize_config(restored)
                else:
                    candidate = _edited(candidate, workflow, key, raw)
                ui.message(f"{key} = {normalize_settings(workflow, candidate.get(workflow))[key]}")
            except (ValidationError, ValueError) as exc:
                ui.message(str(exc), kind="error")


def _edited(config: dict, workflow: str, key: str, raw: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    result = copy.deepcopy(config)
    result.setdefault(workflow, {})[key] = value
    return normalize_config(result)
