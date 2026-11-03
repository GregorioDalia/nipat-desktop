"""Readable run evidence derived from recorded metadata, never scientific inference."""

from __future__ import annotations

import csv
import html
import io
import json
import os
from pathlib import Path, PureWindowsPath
from urllib.parse import quote


_MAX_JSON = 32 * 1024 * 1024
_STATUS = {"succeeded": "Completata", "failed": "Non riuscita", "interrupted": "Interrotta",
           "cancelled": "Interrotta", "planned": "Pianificata: analisi non eseguita",
           "running": "In esecuzione", "preparing": "Preparazione", "pending": "In attesa",
           "blocked": "Non avviata"}
_PARAMETERS = {"reference": "Genoma di riferimento", "panel": "Pannello", "snp_panel": "Pannello SNP",
               "contamination_panel": "Pannello Contamination", "parallel": "Elaborazione parallela",
               "popfreq": "Frequenze di popolazione", "err_const": "Costante di errore",
               "cutoff_mode": "Selezione dei siti CPI", "cutoffs": "Pannelli CPI",
               "mother_prefix": "Prefisso materno", "father_prefix": "Prefisso paterno",
               "pairs": "Coppie CPI", "mode": "Modalità di input", "preset": "Workflow automatico",
               "input_dir": "Cartella degli input", "bamlist": "Lista BAM"}


def _read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Metadati non disponibili: {path.name}")
    with path.open("rb") as stream:
        content = stream.read(_MAX_JSON + 1)
    if len(content) > _MAX_JSON:
        raise ValueError(f"Metadati troppo grandi: {path.name}")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError(f"Metadati non validi: {path.name}")
    return result


def original_basename(path: str) -> str:
    """Preserve Windows names when inspecting their run on another platform."""
    return PureWindowsPath(path).name if "\\" in path else Path(path).name


def sample_rows(metadata: dict) -> list[dict[str, str]]:
    parameters = metadata.get("parameters")
    parameters = parameters if isinstance(parameters, dict) else {}
    mapping = parameters.get("sample_mapping")
    if not isinstance(mapping, list):
        return []
    result = []
    for item in mapping:
        if not isinstance(item, dict):
            continue
        identifier, source = item.get("sample_id"), item.get("original_path")
        if not isinstance(identifier, str) or not isinstance(source, str):
            continue
        name = item.get("display_name")
        result.append({"sample_id": identifier,
                       "original_name": name if isinstance(name, str) else original_basename(source),
                       "original_path": source,
                       "container_path": str(item.get("container_path", "")),
                       "role": str(item.get("role", ""))})
    return result


def _text(value: object) -> str:
    if value is None:
        return "Non registrato"
    if isinstance(value, bool):
        return "Sì" if value else "No"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _table(headers: list[str], rows: list[list[object]]) -> str:
    esc = lambda value: html.escape(_text(value))
    return ("<table><thead><tr>" + "".join(f"<th>{esc(value)}</th>" for value in headers)
            + "</tr></thead><tbody>" + "".join("<tr>" + "".join(
                f"<td><pre>{esc(value)}</pre></td>" for value in row) + "</tr>" for row in rows)
            + "</tbody></table>")


def _status(value: object) -> str:
    return _STATUS.get(value, value) if isinstance(value, str) else "Non registrato"


def _spreadsheet_cell(value: str) -> str:
    # A filename is data, including when opened in a spreadsheet. The exact
    # original remains in run.json and in the escaped HTML report.
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def _write_exclusive(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def write_run_report(run_dir: Path) -> dict:
    """Write a local HTML report and TSV map after final run metadata is saved.

    Reads only run-owned records; input paths are displayed, never opened.
    Existing files are never replaced, including symlinks. A failed analysis
    still receives a report; no completion or scientific validity is inferred.
    """
    run_dir = Path(run_dir).resolve()
    metadata = _read_json(run_dir / "run.json")
    rows = sample_rows(metadata)
    summary = run_dir / "run-report.html"
    mapping = run_dir / "sample-map.tsv"
    for destination in (summary, mapping):
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Resoconto già presente: {destination.name}")

    tsv = io.StringIO(newline="")
    writer = csv.writer(tsv, delimiter="\t", lineterminator="\n")
    keys = ["sample_id", "original_name", "original_path", "container_path", "role"]
    writer.writerow(keys)
    writer.writerows([_spreadsheet_cell(row[key]) for key in keys] for row in rows)

    status = metadata.get("status")
    status = _STATUS.get(status, _text(status)) if isinstance(status, str) else "Non registrato"
    body = [f"<h1>NIPAT — {html.escape(_text(metadata.get('run_name', run_dir.name)))}</h1>",
            _table(["Voce", "Valore"], [
                ["Analisi", metadata.get("workflow")], ["Stato", status],
                ["Inizio (UTC)", metadata.get("started_at")], ["Fine (UTC)", metadata.get("finished_at")],
            ]),
            "<p>Questo resoconto descrive l'esecuzione registrata. Il completamento tecnico non costituisce una validazione scientifica.</p>"]
    if metadata.get("error"):
        body.append("<h2>Interruzione</h2><pre>" + html.escape(_text(metadata["error"])) + "</pre>")
    body.append("<h2>Campioni</h2>")
    if rows:
        body.append(_table(["Identificativo interno", "Nome originale", "File originale", "Ruolo"],
                           [[row["sample_id"], row["original_name"], row["original_path"], row["role"]]
                            for row in rows]))
        body.append("<p>Gli identificativi interni collegano le fasi; i file originali non sono rinominati. "
                    "<a href='sample-map.tsv'>Scarica la corrispondenza dei campioni (TSV)</a>. "
                    "Nel TSV i valori che potrebbero essere formule sono preceduti da un apostrofo; "
                    "i nomi esatti sono riportati qui e in run.json.</p>")
    else:
        body.append("<p>Questa esecuzione non registra una corrispondenza dei campioni. Consultare gli input in run.json.</p>")

    parameters = metadata.get("parameters")
    if isinstance(parameters, dict):
        values = [[_PARAMETERS.get(key, key), value] for key, value in parameters.items()
                  if key not in {"sample_mapping", "bams", "inputs", "expected_steps"}]
        if values:
            body.extend(["<h2>Impostazioni registrate</h2>", _table(["Impostazione", "Valore"], values)])

    state_path = run_dir / "output" / "workflow" / "workflow-state.json"
    if state_path.is_file() and not any(path.is_symlink() for path in
                                       (run_dir / "output", state_path.parent, state_path)):
        state = _read_json(state_path)
        steps = state.get("steps")
        if isinstance(steps, list):
            body.extend(["<h2>Fasi dell'analisi</h2>", _table(["Fase", "Analisi", "Stato", "Errore"],
                [[item.get("id"), item.get("workflow"), _status(item.get("status")),
                  item.get("error") or ""] for item in steps if isinstance(item, dict)])])

    snapshot = metadata.get("resource_snapshot")
    if isinstance(snapshot, dict):
        from nipat.resource_ui import resource_lines
        body.append("<h2>Risorse rilevate prima dell'analisi</h2><ul>" + "".join(
            f"<li>{html.escape(line)}</li>" for line in resource_lines(snapshot)) + "</ul>")
    options = metadata.get("execution_options")
    if isinstance(options, dict):
        body.extend(["<h2>Limiti richiesti per l'analisi</h2>", _table(["Impostazione", "Valore"], [
            ["Quota CPU", options.get("cpus") or "Nessun limite aggiuntivo"],
            ["RAM (MiB)", options.get("memory_mb") or "Nessun limite aggiuntivo"],
            ["Numero massimo di processi", options.get("pids_limit") or "Nessun limite aggiuntivo"],
            ["Checksum degli input", options.get("input_hashes")],
        ])])
    commands = metadata.get("commands")
    if isinstance(commands, list):
        diagnostics = []
        for number, command in enumerate(commands, 1):
            evidence = command.get("container_diagnostics") if isinstance(command, dict) else None
            diagnosis = evidence.get("diagnosis") if isinstance(evidence, dict) else None
            if isinstance(diagnosis, dict) and diagnosis.get("message"):
                diagnostics.append([number, diagnosis.get("message")])
        if diagnostics:
            body.extend(["<h2>Diagnostica registrata</h2>", _table(["Comando", "Esito del controllo"], diagnostics)])

    source = metadata.get("source")
    runtime = metadata.get("runtime")
    if isinstance(source, dict):
        body.extend(["<h2>Versioni e provenienza</h2>", _table(["Componente", "Versione registrata"], [
            ["NIPAT", source.get("nipat_version")], ["Sorgente", source.get("git") or source.get("release")],
            ["Motore scientifico", runtime],
        ])])
    body.append("<h2>Consultazione</h2><ul>")
    for relative, label in (
        ("output/presentation/index.html", "Risultati con i nomi originali dei campioni"),
        ("output/workflow/presentation/index.html", "Risultati del workflow con i nomi originali"),
        ("execution.log", "Registro dell'esecuzione"), ("run.json", "Metadati completi"),
    ):
        path = run_dir / relative
        if path.is_file() and not any(part.is_symlink() for part in [path, *path.parents] if part != run_dir.parent):
            body.append(f"<li><a href='{quote(relative)}'>{html.escape(label)}</a></li>")
    body.append("</ul><p>I risultati nativi del motore restano nella cartella output. "
                "Le copie di presentazione mantengono i valori scientifici e rendono riconoscibili i nomi.</p>")
    page = ("<!doctype html><html lang='it'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            "<title>Resoconto NIPAT</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:1100px;"
            "margin:2em auto;padding:0 1em;color:#172c3c}h1,h2{color:#165c75}table{border-collapse:collapse;"
            "width:100%;margin:1em 0}td,th{border:1px solid #ccd7dd;padding:.6em;text-align:left;vertical-align:top}"
            "th{background:#eef5f8}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font:inherit}"
            "a{color:#125b83}</style><body>" + "\n".join(body) + "</body></html>\n")
    _write_exclusive(mapping, tsv.getvalue())
    _write_exclusive(summary, page)
    return {"schema_version": 1, "summary": summary.name, "sample_map": mapping.name,
            "files": [summary.name, mapping.name]}
