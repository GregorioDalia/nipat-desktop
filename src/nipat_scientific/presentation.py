"""Readable exports, separate from canonical scientific artifacts.

Identifiers used by scientific contracts never change. Display labels are data,
not R source, shell arguments, or output paths. R renders an additional copy of
each plot from the original plot object; Python copies tables, changing only
explicit identifier columns/headers. Numeric values and native files are intact.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import quote

from nipat_scientific.errors import PlanExecutionError, ValidationError


def _label(value: object, *, basename: bool) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 2048
            or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)
            or (basename and (any(char in "/\\" for char in value) or value in {".", ".."}))):
        raise ValidationError("Etichetta campione non valida: usare un nome leggibile senza caratteri di controllo.")
    return value


def normalize_presentation(value: object, sample_ids: set[str], pair_ids: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or set(value) != {"samples", "pairs"}:
        raise ValidationError("Presentazione non valida: attesi samples e pairs.")
    samples, pairs = value["samples"], value["pairs"]
    if (not isinstance(samples, dict) or set(samples) != sample_ids
            or not isinstance(pairs, dict) or not set(pairs).issubset(pair_ids)):
        raise ValidationError("Le etichette devono corrispondere esattamente ai campioni e alle coppie selezionati.")
    return {"samples": {key: _label(label, basename=True) for key, label in samples.items()},
            "pairs": {key: _label(label, basename=False) for key, label in pairs.items()}}


def validate_request_presentation(request: dict) -> dict | None:
    if "presentation" not in request:
        return None
    try:
        workflow = request["workflow"]
        if workflow == "dnp-call":
            sample_ids = {sample["sample_id"] for sample in request["samples"]}
        elif workflow == "snp-call":
            sample_ids = {"sample_0001"}
        else:
            sample_ids = {Path(sample["name"]).stem for sample in request["samples"]}
        pair_ids = ({":".join(part.strip() for part in pair.split(":"))
                     for pair in request["pairs" if workflow == "cpi" else "trios"].split(",")} if workflow in {"cpi", "cpin"} else set())
        return normalize_presentation(request["presentation"], sample_ids, pair_ids)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValidationError("Descrizione dei campioni non valida per la presentazione.") from exc


def _unique_labels(labels: dict[str, str]) -> dict[str, str]:
    # Case/normalization equivalents are disambiguated even on case-sensitive hosts.
    counts: dict[str, int] = {}
    for label in labels.values():
        folded = unicodedata.normalize("NFC", label).casefold()
        counts[folded] = counts.get(folded, 0) + 1
    output = {}
    used = set()
    for identity in sorted(labels):
        label = labels[identity]
        key = unicodedata.normalize("NFC", label).casefold()
        resolved = f"{label} [{identity}]" if counts[key] > 1 else label
        while unicodedata.normalize("NFC", resolved).casefold() in used:
            resolved += f" [{identity}]"
        used.add(unicodedata.normalize("NFC", resolved).casefold())
        output[identity] = resolved
    return output


def _filename(label: str, identity: str) -> str:
    # Restrict portable filenames, preserve Unicode in labels and in the map.
    stem = unicodedata.normalize("NFC", label)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .") or "campione"
    while len(stem.encode("utf-8")) > 135:
        stem = stem[:-1]
    token = re.sub(r"[^A-Za-z0-9_-]", "_", identity)[:40] or "sample"
    # Hash prevents collisions caused by sanitization/truncation, including pair IDs.
    fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
    return f"{stem}__{token}_{fingerprint}"


def _pair_map(request: dict, samples: dict[str, str], pairs: dict[str, str]) -> dict[str, str]:
    labels = {}
    workflow = request["workflow"]
    if workflow not in {"cpi", "cpin"}:
        return labels
    roles = ("mother", "father") if workflow == "cpi" else ("mother", "father", "child")
    role_labels = {"mother": "Madre", "father": "Padre", "child": "Figlio"}
    marker = request.get("marker_type", "DNP")
    for family in request["pairs" if workflow == "cpi" else "trios"].split(","):
        values = [part.strip() for part in family.split(":")]
        identity = ":".join(values)
        native = "-".join(role.title() + value for role, value in zip(roles, values, strict=True)) + f"_{marker}s"
        description = " | ".join(f"{role_labels[role]}: {samples[request[role + '_prefix'] + value]}"
                                 for role, value in zip(roles, values, strict=True))
        labels[native] = pairs.get(identity, description)
    return _unique_labels(labels)


def step_presentation(plan: dict, step: dict, request: dict, bindings: list[dict] = ()) -> dict | None:
    """Translate registry identities into this step's native, immutable aliases."""
    value = plan.get("presentation")
    if value is None:
        return None
    labels = value["samples"]
    selected = {}
    pair_labels = {}
    workflow = step["workflow"]
    if workflow == "dnp-call":
        selected = {f"sample_{number:04d}": labels[identity]
                    for number, identity in enumerate(step["inputs"]["samples"], 1)}
    elif workflow == "snp-call":
        selected = {"sample_0001": labels[step["inputs"]["sample"]]}
    elif workflow == "contamination":
        selected = {f"table_{number:04d}": labels[reference["sample"]]
                    for number, reference in enumerate(step["inputs"]["samples"], 1)}
    else:
        roles = ("mother", "father") if workflow == "cpi" else ("mother", "father", "child")
        role_labels = {"mother": "Madre", "father": "Padre", "child": "Figlio"}
        for binding in bindings:
            description = []
            for role, native in zip(roles, binding["native_selection"].split(":"), strict=True):
                name = labels[binding[role]["sample"]]
                selected[role.title() + native] = name
                description.append(f"{role_labels[role]}: {name}")
            identity = binding["pair" if workflow == "cpi" else "trio"]
            pair_labels[binding["native_selection"]] = value["pairs"].get(identity, identity + " — " + " | ".join(description))
    return {"samples": selected, "pairs": pair_labels}


def prepare_presentation(request: dict, script: Path, arguments: list[str]) -> list[str]:
    """Prepare a data-only rendering map and return the R presentation entrypoint."""
    value = validate_request_presentation(request)
    if value is None:
        return ["Rscript", str(script), *arguments]
    output, work = Path(request["out_dir"]), Path(request["work_dir"])
    directory = output / "presentation"
    directory.mkdir(exist_ok=False)
    samples = _unique_labels(value["samples"])
    pairs = _pair_map(request, samples, value["pairs"])
    replacements = {**samples, **pairs}
    replacements.update({f"GT_{key}": f"GT_{label}" for key, label in samples.items()})
    plots = {}
    tables = {}

    def export(source: str, target: str, *, sample: str | None = None, kind: str = "table") -> None:
        record = {"source": source, "target": target, "sample": sample}
        (plots if kind == "plot" else tables)[source] = record

    workflow = request["workflow"]
    if workflow == "dnp-call":
        for identity, label in samples.items():
            stem = _filename(label, identity)
            export(f"individual_outputs/full_output_{identity}.txt", f"{stem}_DNP.txt", sample=identity)
            for suffix in ("N_genotypes", "Ref_read_count", "Alt_read_count", "Other_read_count"):
                export(f"plots/{identity}/{identity}_{suffix}.pdf", f"{stem}_{suffix}.pdf", sample=identity, kind="plot")
        export("summary/output_AllGenotypes.txt", "DNP_AllGenotypes.txt")
        export("summary/Unassigned_genotypes.pdf", "DNP_Unassigned_genotypes.pdf", kind="plot")
        if len(samples) > 1:
            export("summary/DNPs_covered_UpSet_plot.pdf", "DNPs_covered_UpSet_plot.pdf", kind="plot")
    elif workflow == "snp-call":
        identity = "sample_0001"
        stem = _filename(samples[identity], identity)
        export("SNPcall_output.txt", f"{stem}_SNP.txt", sample=identity)
        for suffix in ("N_genotypes", "Ref_read_count", "Alt_read_count", "Other_read_count"):
            export(f"plots/{identity}/{identity}_{suffix}.pdf", f"{stem}_{suffix}.pdf", sample=identity, kind="plot")
        export("summary/SNPcall_AllGenotypes.txt", "SNP_AllGenotypes.txt")
        export("summary/Unassigned_genotypes.pdf", "SNP_Unassigned_genotypes.pdf", sample=identity, kind="plot")
        export("summary/resources.tsv", "SNP_resources.tsv")
    elif workflow == "contamination":
        export("contamination_summary.txt", "Contamination_summary.txt")
        for identity, label in samples.items():
            export(f"contamination_{identity}.txt", f"{_filename(label, identity)}_Contamination.txt", sample=identity)
    elif workflow == "cpin":
        export("Summary_Postnatal_CPI.txt", "Summary_Postnatal_CPI.txt")
        selection = request.get("scientific_settings", {}).get("site_selection", "both")
        analyses = {"other_allele": ["heterozygous_child_sites"], "all": ["all_compatible_sites"],
                    "both": ["heterozygous_child_sites", "all_compatible_sites"]}[selection]
        for identity, label in pairs.items():
            stem = _filename(label, identity)
            export(f"sites/{identity}_sites.tsv", f"{stem}_sites.tsv")
            for analysis in analyses:
                export(f"curves/{identity}_{analysis}_curve.tsv", f"{stem}_{analysis}_curve.tsv")
                export(f"plots/{identity}_{analysis}_CPIplot.pdf", f"{stem}_{analysis}_CPI.pdf", kind="plot")
        export("All_CPIplots.pdf", "All_CPIplots.pdf", kind="plot")
    else:
        # The original summary retains its exact numbers and row order.
        for source in ("Summary_FetalFraction_CPI.csv",):
            export(source, source)
        for identity, label in pairs.items():
            export(f"plots/{identity}_CPIplot.pdf", f"{_filename(label, identity)}_CPI.pdf", kind="plot")
        export("plots/All_CPIplots.pdf", "All_CPIplots.pdf", kind="plot")
    config = {
        "schema_version": 1, "workflow": workflow, "script": str(script.resolve()),
        "output": str(output.resolve()), "directory": str(directory.resolve()),
        "samples": samples, "original_samples": value["samples"], "pairs": pairs,
        "replacements": replacements, "plots": plots, "tables": tables,
    }
    config_path = work / "presentation-config.json"
    with config_path.open("x", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    for identity, label in samples.items():
        print(f"NIPAT campione {identity}: {label}", flush=True)
    return ["Rscript", str(Path(__file__).with_suffix(".R")), *arguments]


def _copy_table(source: Path, target: Path, replacements: dict[str, str], *, sample: str | None = None) -> None:
    delimiter = "," if source.suffix == ".csv" else "\t"
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=delimiter, strict=True))
    if not rows:
        raise PlanExecutionError("presentation.table", f"Tabella senza intestazione: {source.name}")
    original_headers = rows[0][:]
    identity_columns = {index for index, header in enumerate(original_headers) if header in {"Pair", "Trio", "individuo", "sample"}}
    rows[0] = [_spreadsheet_label(replacements.get(header, header)) if header.startswith("GT_") else header
               for header in original_headers]
    for row in rows[1:]:
        if len(row) != len(original_headers):
            raise PlanExecutionError("presentation.table", f"Tabella non rettangolare: {source.name}")
        for index in identity_columns:
            row[index] = (_spreadsheet_label(replacements[row[index]])
                          if row[index] in replacements else row[index])
    if sample is not None:
        if "Sample" in original_headers:
            raise PlanExecutionError("presentation.table", "La tabella scientifica contiene già una colonna Sample.")
        rows[0].insert(0, "Sample")
        for row in rows[1:]:
            row.insert(0, _spreadsheet_label(sample))
    with target.open("x", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter=delimiter, lineterminator="\n").writerows(rows)


def _spreadsheet_label(value: str) -> str:
    """Keep a sample label as text when a TSV/CSV is opened in a spreadsheet."""
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def _file_record(path: Path, root: Path, **metadata) -> dict:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise PlanExecutionError("presentation.output", f"Esportazione assente o fuori destinazione: {path.name}")
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"path": path.relative_to(root).as_posix(), "sha256": digest, **metadata}


def finish_presentation(request: dict, root: Path) -> dict | None:
    """Validate every expected readable copy after canonical output validation."""
    if "presentation" not in request:
        return None
    work, output = Path(request["work_dir"]), Path(request["out_dir"])
    config = json.loads((work / "presentation-config.json").read_text(encoding="utf-8"))
    directory = output / "presentation"
    files = []
    for source, entry in config["tables"].items():
        native, readable = output / source, directory / entry["target"]
        _file_record(native, root)
        _copy_table(native, readable, config["replacements"],
                    sample=config["samples"][entry["sample"]] if entry["sample"] else None)
        files.append(_file_record(readable, root, kind="table", source=native.relative_to(root).as_posix(), sample=entry["sample"]))
    for source, entry in config["plots"].items():
        native, readable = output / source, directory / entry["target"]
        _file_record(native, root)
        record = _file_record(readable, root, kind="plot", source=native.relative_to(root).as_posix(), sample=entry["sample"])
        if readable.read_bytes()[:5] != b"%PDF-":
            raise PlanExecutionError("presentation.plot", f"PDF non valido: {readable.name}")
        files.append(record)
    map_path = directory / "sample-map.tsv"
    with map_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["internal_id", "original_name", "display_name"])
        writer.writerows((identity, _spreadsheet_label(config["original_samples"][identity]), _spreadsheet_label(label))
                        for identity, label in config["samples"].items())
    links = "".join(f'<li><a href="{quote(Path(item["path"]).name)}">{html.escape(Path(item["path"]).name)}</a></li>'
                    for item in files)
    mappings = "".join(f"<tr><td>{html.escape(identity)}</td><td>{html.escape(label)}</td></tr>"
                       for identity, label in config["samples"].items())
    index = directory / "index.html"
    index.write_text(_html_page("Risultati NIPAT", f"<h1>{html.escape(request['workflow'])}</h1>"
                     "<p>Queste copie riportano i nomi originali dei campioni. I valori scientifici sono invariati. "
                     "Le tabelle individuali aggiungono la colonna Sample per identificare il campione. "
                     "I risultati canonici e gli identificativi interni restano disponibili nella cartella superiore.</p>"
                     "<p>Nei file CSV/TSV i nomi che un foglio di calcolo potrebbe interpretare come formule "
                     "hanno un apostrofo iniziale di protezione. Qui e nella tabella di corrispondenza il nome resta completo.</p>"
                     f"<table><tr><th>Identificativo interno</th><th>Campione</th></tr>{mappings}</table>"
                     '<p><a href="sample-map.tsv">Tabella di corrispondenza</a></p>'
                     f"{_interpretation_notes(request['workflow'])}<h2>Risultati</h2><ul>{links}</ul>"), encoding="utf-8")
    report = {"schema_version": 1, "interface": "readable-results-v1", "status": "complete",
              "index": _file_record(index, root), "sample_map": _file_record(map_path, root), "files": files}
    (work / "presentation-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _interpretation_notes(workflow: str) -> str:
    """Explain units and missing data without inventing scientific estimates."""
    common = ("<h2>Come leggere i risultati</h2><p>NA indica un valore non disponibile o un genotipo non assegnato; "
              "non equivale a zero. I conteggi e le stime sono riportati come prodotti dal modulo scientifico.</p>")
    descriptions = {
        "snp-call": (
            "<p>SNPcall 2.0: N_REF, N_ALT e N_Other contano le osservazioni conservate; total_count è la loro somma. "
            "ratio è N_REF / (N_REF + N_ALT), quindi è la frazione di riferimento. GL0, GL1 e GL2 sono "
            "log-verosimiglianze naturali dei genotipi 0/0, 0/1 e 1/1: non sono probabilità né punteggi Phred. "
            "GT è il genotipo assegnato dal modello; quando la frazione Other raggiunge la soglia configurata resta NA.</p>"
            "<p>reads_discarded_for_indels e la relativa ratio descrivono gli indel alla base centrale prima del filtro "
            "sull'intera finestra: non contano tutte le letture eliminate nei fianchi. Gli istogrammi includono una classe "
            "separata per zero; gli estremi delle classi positive sono inclusi. Il grafico UpSet confronta i loci con "
            "GT assegnato, non la sola presenza di copertura.</p>"
            "<p>resources.tsv riporta tempo di elaborazione del campione e RSS osservata all'inizio e alla fine "
            "(MiB); queste osservazioni non misurano il picco di memoria. Per il tempo complessivo e la memoria "
            "del contenitore consultare la diagnostica dell'esecuzione.</p>"),
        "dnp-call": (
            "<p>N_REF, N_ALT e N_Other sono i conteggi delle osservazioni conservate; ratio è la frazione di riferimento "
            "N_REF / (N_REF + N_ALT). GL0, GL1 e GL2 sono log-verosimiglianze naturali. "
            "Gli istogrammi includono zero in una classe separata e usano intervalli positivi con entrambi gli estremi "
            "inclusi. Il grafico UpSet confronta i loci con genotipo assegnato, non la sola copertura. "
            "Il grafico dei genotipi non assegnati è suddiviso in pagine per mantenere leggibili tutti i loci.</p>"),
        "cpi": (
            "<p>Median_fetal_fraction_raw è una frazione; Median_fetal_fraction_percent è la stessa misura in percentuale. "
            "Le colonne logCPI e, per compatibilità con lo script originale, CPI_medianFF contengono log10(CPI), "
            "non CPI grezzo. I grafici distinguono log10(CPI) dai conteggi dei siti matching/mismatching. "
            "I confronti senza siti informativi mantengono NA e sono indicati come privi di dati.</p>"),
        "cpin": (
            "<p>Log10_CPI è il logaritmo in base dieci dell'indice; CPI è il valore grezzo. Le analisi "
            "heterozygous_child_sites e all_compatible_sites applicano selezioni diverse, riportate separatamente. "
            "La tabella dei siti conserva anche esclusioni e motivi; le curve indicano intervalli inclusivi di "
            "soglie Min_child_reads–Through_min_child_reads con identico risultato. "
            "Un confronto privo di siti utilizzabili mantiene NA.</p>"),
        "contamination": (
            "<p>Le stime di contaminazione sono frazioni: 0,025 corrisponde al 2,5%. La tabella di riepilogo separa "
            "i campioni e riporta anche il numero di loci usati. Un campione senza loci informativi mantiene "
            "le stime NA; non deve essere interpretato come contaminazione nulla.</p>"),
    }
    return common + descriptions.get(workflow, "")


def _html_page(title: str, body: str) -> str:
    return ('<!doctype html><html lang="it"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>body{{font:16px system-ui,sans-serif;max-width:1000px;'
            'margin:3rem auto;padding:0 1rem;line-height:1.5}}td,th{padding:.4rem .8rem;text-align:left;'
            'border-bottom:1px solid #ddd}a{overflow-wrap:anywhere}</style>' + body + '</html>')


def finish_plan_presentation(plan: dict, state: dict, root: Path) -> dict | None:
    if "presentation" not in plan:
        return None
    directory = root / "presentation"
    directory.mkdir(exist_ok=False)
    entries = []
    for step in state["steps"]:
        presentation = step.get("artifacts", {}).get("presentation")
        if presentation is not None:
            target = presentation["index"]["path"]
            entries.append(f'<li>{html.escape(step["id"])}: <a href="../{quote(target, safe="/")}">'
                           f'{html.escape(step["workflow"])} — risultati</a></li>')
        else:
            entries.append(f'<li>{html.escape(step["id"])}: {html.escape(step["status"])}</li>')
    summaries = []
    for group in state.get("snp_summary", []):
        links = []
        for label, item in [("Genotipi di tutti i campioni", group["genotypes"]),
                            ("Risorse per campione", group["resources"]),
                            ("Nomi dei campioni", group["sample_labels"]),
                            *[(Path(item["path"]).name, item) for item in group["plots"]]]:
            _file_record(root / item["path"], root)
            links.append(f'<li><a href="../{quote(item["path"], safe="/")}">{html.escape(label)}</a></li>')
        summaries.append(f'<h3>{html.escape(group["id"])} — {len(group["samples"])} campioni</h3>'
                         f'<ul>{"".join(links)}</ul>')
    summary_html = ("<h2>Confronto SNPcall 2.0 tra campioni</h2>"
                    "<p>Ogni gruppo usa lo stesso pannello e riferimento. Le tabelle dei genotipi mantengono "
                    "gli identificativi interni; la tabella dei nomi consente di risalire ai campioni originali. "
                    "UpSet confronta i loci con genotipo assegnato, non la sola copertura.</p>" + "".join(summaries)
                    if summaries else "")
    index = directory / "index.html"
    index.write_text(_html_page("Workflow NIPAT", "<h1>Risultati del workflow</h1>"
                     f'<p>Stato: {html.escape(state["status"])}</p><ul>{"".join(entries)}</ul>{summary_html}'), encoding="utf-8")
    return {"schema_version": 1, "index": _file_record(index, root)}
