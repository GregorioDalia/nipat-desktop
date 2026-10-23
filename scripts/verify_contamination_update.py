"""Run the R contamination workflow against synthetic analytical references."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

from nipat.errors import NipatError, ValidationError
from nipat.execution.runner import DockerComposeRunner
from nipat.execution.workflows import Workflows
from nipat.paths import ProjectLayout


EXPECTED_SITES = {
    ("chr1", "100", "101"): (1.0, 0.0),
    ("chr1", "200", "201"): (0.0, 0.0),
    ("chr1", "300", "301"): (0.95, 0.05),
    ("chr1", "400", "401"): (0.05, 0.05),
}
EXPECTED_SD = 0.0288675134594813


def read_tsv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not required.issubset(reader.fieldnames or []):
            raise ValidationError(f"Colonne mancanti nel risultato: {path.name}")
        return list(reader)


def check_number(value: str | None, expected: float, label: str) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}: valore non numerico {value!r}") from exc
    if not math.isfinite(number) or not math.isclose(
        number, expected, rel_tol=0, abs_tol=1e-12
    ):
        raise ValidationError(f"{label}: ottenuto {value}, atteso {expected}")


def check_outputs(run_dir: Path) -> None:
    output = run_dir / "output"
    summary = read_tsv(
        output / "contamination_summary.txt",
        {"individuo", "informative_DNPs", "mean_contamination", "sd_contamination"},
    )
    if len(summary) != 3 or {row["individuo"] for row in summary} != {
        "NoRatio", "WithRatio", "NoSites"
    }:
        raise ValidationError("Il riepilogo deve contenere esattamente i tre campioni di test.")
    by_sample = {row["individuo"]: row for row in summary}
    for sample in ("NoRatio", "WithRatio"):
        for column, expected in (
            ("informative_DNPs", 4),
            ("mean_contamination", 0.025),
            ("sd_contamination", EXPECTED_SD),
        ):
            check_number(by_sample[sample][column], expected, f"{sample}: {column}")
        sites = read_tsv(
            output / f"contamination_{sample}.txt",
            {"chr", "pos1", "pos2", "ratio_REF_ALT", "contamination"},
        )
        coordinates = [(row["chr"], row["pos1"], row["pos2"]) for row in sites]
        if len(sites) != 4 or set(coordinates) != set(EXPECTED_SITES):
            raise ValidationError(f"{sample}: siti mantenuti diversi da quelli attesi.")
        for row, coordinate in zip(sites, coordinates):
            ratio, contamination = EXPECTED_SITES[coordinate]
            label = f"{sample}: {coordinate}"
            check_number(row["ratio_REF_ALT"], ratio, f"{label} ratio")
            check_number(row["contamination"], contamination, f"{label} contamination")

    empty = by_sample["NoSites"]
    check_number(empty["informative_DNPs"], 0, "NoSites: informative_DNPs")
    for column in ("mean_contamination", "sd_contamination"):
        if empty[column] != "NA":
            raise ValidationError(f"NoSites: {column} deve essere NA.")
    empty_sites = read_tsv(
        output / "contamination_NoSites.txt", {"chr", "pos1", "pos2", "contamination"}
    )
    if empty_sites:
        raise ValidationError("NoSites: atteso file per sito con sola intestazione.")


def check_bundled_run(run_dir: Path, layout: ProjectLayout, *, workflow: str = "contamination") -> None:
    """Check the real client selected only the bundled engine and scoped mounts."""
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    config = json.loads((run_dir / "work/engine-compose.json").read_text(encoding="utf-8"))
    service = config["services"]["scientific"]
    if set(config["services"]) != {"scientific"}:
        raise ValidationError("Atteso soltanto il servizio scientifico isolato.")
    if service.get("read_only") is not True or service.get("network_mode") != "none":
        raise ValidationError("Il motore deve avere filesystem in sola lettura e rete disabilitata.")
    mappings = {item["container_path"] for item in record["input_mounts"]}
    run_target = str(layout.container_path(run_dir))
    volumes = service["volumes"]
    if len(volumes) != len(mappings) + 1 or {v["target"] for v in volumes} != mappings | {run_target}:
        raise ValidationError("Mount inattesi: consentiti soltanto input selezionati e singolo run.")
    for volume in volumes:
        if volume.get("type") != "bind" or volume.get("bind", {}).get("create_host_path") is not False:
            raise ValidationError("Il mount non deve creare automaticamente cartelle host.")
        if volume.get("read_only", False) != (volume["target"] != run_target):
            raise ValidationError("Permessi dei mount non coerenti con input/output.")
    runtime = record["runtime"]
    engine = runtime.get("engine", {})
    if (record["status"] != "succeeded" or record["source"].get("role") != "client"
            or record.get("workflow") != workflow
            or engine.get("workflow_interfaces", {}).get(workflow) != f"{workflow}-v1"
            or engine.get("preparation", {}).get("interface") != "workflow-preparation-v1"
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", runtime.get("image_id", ""))):
        raise ValidationError("Identità dell'immagine o provenienza del motore mancanti.")
    hashes = engine["preparation"].get("file_sha256", {})
    required = {"engine/main.py", *(f"lib/nipat_scientific/{name}.py" for name in (
        "__init__", "errors", "panels", "files", "contamination", "snp", "dnp",
    ))}
    if set(hashes) != required or any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in hashes.values()):
        raise ValidationError("Hash del codice di preparazione incompleti o non validi.")
    commands = record["commands"]
    if len(commands) != 1:
        raise ValidationError(f"Attesa un'unica invocazione completa del motore {workflow}.")
    argv = commands[0]["argv"]
    compose_paths = [argv[index + 1].replace("\\", "/")
                     for index, value in enumerate(argv[:-1]) if value == "-f"]
    if (len(compose_paths) != 1 or not compose_paths[0].endswith("/engine-compose.json")
            or "/opt/nipat/engine/main.py" not in argv or "execute" not in argv
            or argv[argv.index("execute") + 1:argv.index("execute") + 2] != [workflow]):
        raise ValidationError("La CLI non sta usando esclusivamente il motore incorporato.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", help="nome opzionale di una nuova esecuzione")
    args = parser.parse_args()
    layout = ProjectLayout.discover()
    try:
        if layout.project_dir != Path(__file__).resolve().parents[1]:
            raise ValidationError(
                "Usare la venv di questa repository e verificare NIPAT_PROJECT_DIR."
            )
        fixture = layout.project_dir / "tests" / "fixtures" / "contamination"
        inputs = [
            fixture / "samples" / name
            for name in ("NoRatio.tsv", "WithRatio.TXT", "NoSites.txt")
        ]
        originals = {path: path.read_bytes() for path in inputs}
        run_dir = Workflows(layout, DockerComposeRunner(layout)).contamination(
            inputs=inputs, panel=fixture / "DNP_list.txt", run_name=args.run_name
        )
        print(f"Risultati del test: {run_dir}", flush=True)
        for path in inputs:
            if path.read_bytes() != originals[path]:
                raise ValidationError(f"Input originale modificato: {path.name}")
        check_outputs(run_dir)
        check_bundled_run(run_dir, layout)
    except (NipatError, OSError) as exc:
        print(f"Verifica Contamination fallita: {exc}", file=sys.stderr)
        return 1
    print("Verifica Contamination superata: riepilogo e valori per sito attesi.")
    print("Con/senza ratio: 4 siti, media 0.025 (2.5%), SD 0.0288675134594813.")
    print("Campione senza siti informativi: conteggio 0, media e SD NA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
