from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath

from nipat.adapters.panels import (
    read_dnp_list,
    read_position_panel,
    read_snp_positions,
)
from nipat.errors import ValidationError
from nipat.execution.mounts import INPUT_ROOT, InputMounts
from nipat.execution.runner import DockerComposeRunner
from nipat.paths import ProjectLayout
from nipat.validation.files import (
    require_contamination_input,
    require_directory,
    require_file,
    require_sidecar,
    require_snp_pileup,
)
from nipat_scientific.cpi import normalize_pairs
from nipat_scientific.files import require_dnp_input, require_population_frequencies
from nipat_scientific.plan import validate_plan


def _bind_bam(mounts: InputMounts, bam: Path, target: PurePosixPath) -> list[Path]:
    mounts.bind_file(bam, target=target)
    inputs = [bam]
    # These workflows use mpileup -l without -r: BAM indexes are optional.
    # Include an available standard index without requiring or creating one.
    for suffix in (".bai", ".csi"):
        for candidate in (Path(str(bam) + suffix), bam.with_suffix(suffix)):
            if candidate.is_file():
                index = candidate.resolve()
                mounts.bind_file(index, target=PurePosixPath(str(target) + suffix))
                inputs.append(index)
                break
    return inputs


def _bind_reference(mounts: InputMounts, reference: Path) -> tuple[PurePosixPath, list[Path]]:
    reference = require_file(reference, "FASTA")
    index = require_sidecar(reference, ".fai", "Indice FASTA")
    compressed = reference.suffix.lower() in {".gz", ".bgz", ".bgzf"}
    target = INPUT_ROOT / "reference" / ("genome.fa.gz" if compressed else "genome.fa")
    mounts.bind_file(reference, target=target)
    mounts.bind_file(index, target=PurePosixPath(str(target) + ".fai"))
    inputs = [reference, index]
    if compressed:
        gzi = require_sidecar(reference, ".gzi", "Indice FASTA BGZF")
        mounts.bind_file(gzi, target=PurePosixPath(str(target) + ".gzi"))
        inputs.append(gzi)
    return target, inputs


def _write_engine_request(destination: Path, request: dict) -> None:
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(request, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _select_bams(
    *, bam: Path | None, bams: list[Path] | None, bamlist: Path | None,
) -> tuple[list[Path], Path | None]:
    """Resolve BAM selection once for direct analyses and composed workflows."""
    if sum((bam is not None, bams is not None, bamlist is not None)) != 1:
        raise ValidationError("Indicare uno o più --bam oppure un solo --bamlist.")
    source_list = None
    if bamlist is not None:
        source_list = require_file(bamlist, "Lista BAM")
        selected = []
        try:
            lines = source_list.read_text(encoding="utf-8-sig").splitlines()
        except UnicodeError as exc:
            raise ValidationError(f"Lista BAM: usare un file di testo UTF-8: {source_list}") from exc
        for line in lines:
            value = line.strip()
            if not value:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            entry = Path(value).expanduser()
            selected.append(entry if entry.is_absolute() else source_list.parent / entry)
    else:
        selected = [bam] if bam is not None else list(bams or [])
    if not selected:
        raise ValidationError("La lista BAM è vuota.")
    checked = [require_file(path, "BAM") for path in selected]
    if any(path.samefile(previous) for index, path in enumerate(checked)
           for previous in checked[:index]):
        raise ValidationError("Lo stesso BAM compare più volte nella lista.")
    return checked, source_list


def _snp_steps(samples: list[dict], *, panel: PurePosixPath,
               reference: PurePosixPath | None, mode: str) -> list[dict]:
    """Describe independent SNP analyses; never route SNP output into DNP analyses."""
    return [{"id": f"snp_{number:04d}", "workflow": "snp-call",
             "inputs": {"sample": sample["sample_id"], "panel": str(panel),
                        "reference": str(reference) if reference is not None else None},
             "parameters": {"mode": mode}}
            for number, sample in enumerate(samples, 1)]


def _expected_steps(plan: dict) -> list[dict]:
    """Persist the expected identities before launching the scientific process."""
    return [{"id": step["id"], "workflow": step["workflow"],
             **({"sample": step["inputs"]["sample"], "mode": step["parameters"]["mode"]}
                if step["workflow"] == "snp-call" else {})}
            for step in plan["steps"]]


def _append_snp_steps(plan: dict, *, samples: list[dict], panel: Path | None,
                      reference: PurePosixPath, mounts: InputMounts,
                      input_files: list[Path]) -> Path | None:
    if panel is None:
        return None
    panel = require_file(panel, "Pannello SNP")
    read_snp_positions(panel, for_bed=True)
    target = mounts.bind_file(panel, target=INPUT_ROOT / "snp-list.tsv")
    input_files.append(panel)
    plan["steps"].extend(_snp_steps(samples, panel=target, reference=reference, mode="bam"))
    return panel


def _validate_error_constant(err_const: object) -> None:
    try:
        valid_error = type(err_const) in (int, float) and math.isfinite(err_const) and err_const >= 0
    except OverflowError:
        valid_error = False
    if not valid_error:
        raise ValidationError("La costante di errore deve essere finita e non negativa.")


def _select_cpi_cutoffs(
    *, panel: Path | None, cutoffs: list[tuple[str, Path]] | None,
    cutoff_map: str | None, panel_option: str = "--panel",
) -> tuple[str, list[tuple[str, Path]]]:
    if sum((panel is not None, cutoffs is not None, cutoff_map is not None)) > 1:
        raise ValidationError(f"Scegliere {panel_option}, --cutoff oppure --cutoff-map.")
    requested_cutoffs = list(cutoffs or [])
    if cutoffs is not None and not requested_cutoffs:
        raise ValidationError("Indicare almeno un cutoff.")
    if cutoff_map is not None:
        if not cutoff_map.strip():
            raise ValidationError("La mappa cutoff è vuota; ometterla per la modalità ALL.")
        for value in cutoff_map.split(","):
            value = value.strip()
            if "=" in value:
                label, filename = (part.strip() for part in value.split("=", 1))
            else:
                label, filename = value, value
            if not filename:
                raise ValidationError("Percorso cutoff mancante.")
            requested_cutoffs.append((label, Path(filename)))
    if panel is not None:
        requested_cutoffs.append(("", panel))
    normalized_cutoffs = []
    labels = set()
    for label, source in requested_cutoffs:
        label = label.strip()
        if panel is None:
            if not label or any(c in label for c in ",=") or any(ord(c) < 32 for c in label):
                raise ValidationError("Etichetta cutoff non valida: evitare virgole e '='.")
            if label in labels:
                raise ValidationError(f"Etichetta cutoff duplicata: {label}")
            labels.add(label)
        source = require_file(source, "Pannello cutoff")
        read_position_panel(source)
        normalized_cutoffs.append((label, source))
    cutoff_mode = "panel" if panel is not None else "named" if normalized_cutoffs else "all"
    return cutoff_mode, normalized_cutoffs


class Workflows:
    def __init__(self, layout: ProjectLayout, runner: DockerComposeRunner) -> None:
        self.layout = layout
        self.runner = runner

    def dnp_call(
        self, *, bam: Path | None = None, bams: list[Path] | None = None,
        bamlist: Path | None = None, reference: Path, panel: Path,
        parallel: bool = False, run_name: str | None = None,
    ) -> Path:
        checked, source_list = _select_bams(bam=bam, bams=bams, bamlist=bamlist)
        panel = require_file(panel, "Pannello DNP")
        read_dnp_list(panel)
        mounts = InputMounts(self.layout)
        panel_path = mounts.bind_file(panel, target=INPUT_ROOT / "dnp-panel.txt")
        reference_path, reference_inputs = _bind_reference(mounts, reference)
        input_files = [*reference_inputs, panel]
        if source_list is not None:
            input_files.append(source_list)
        samples = []
        for number, path in enumerate(checked, 1):
            # Upstream derives IDs with an unanchored .bam regex and uses shell
            # arguments without quoting. Stable safe aliases avoid both problems.
            sample_id = f"sample_{number:04d}"
            target = INPUT_ROOT / "bams" / f"{sample_id}.bam"
            input_files.extend(_bind_bam(mounts, path, target))
            samples.append({"sample_id": sample_id, "original_path": str(path),
                            "container_path": str(target)})
        run_dir = self.layout.new_run_dir("dnp-call", run_name)
        with self.runner.record_run(
            run_dir, workflow="dnp-call", inputs=input_files, mounts=mounts,
            bundled_workflow="dnp-call",
            parameters={"bams": [str(path) for path in checked],
                        "bamlist": str(source_list) if source_list else None,
                        "reference": str(reference_inputs[0]), "panel": str(panel),
                        "parallel": parallel, "sample_mapping": samples},
        ):
            request = {
                "schema_version": 1, "workflow": "dnp-call", "panel": str(panel_path),
                "samples": [
                    {"path": sample["container_path"], "sample_id": sample["sample_id"]}
                    for sample in samples
                ],
                "reference": str(reference_path), "parallel": parallel,
                "work_dir": str(self.layout.container_path(run_dir / "work")),
                "out_dir": str(self.layout.container_path(run_dir / "output")),
            }
            request_file = run_dir / "work" / "engine-request.json"
            _write_engine_request(request_file, request)
            self.runner.run(
                ["python3", "/opt/nipat/engine/main.py", "execute", "dnp-call",
                 "--request", self.layout.container_path(request_file)],
                working_dir=self.layout.container_path(run_dir),
            )
        return run_dir

    def dnp_contamination(
        self, *, bam: Path | None = None, bams: list[Path] | None = None,
        bamlist: Path | None = None, reference: Path, panel: Path,
        contamination_panel: Path | None = None, parallel: bool = False,
        snp_panel: Path | None = None,
        run_name: str | None = None,
    ) -> Path:
        """Submit one DNPcall → Contamination plan to the bundled executor.

        The host only selects and mounts inputs. Scientific preparation, the
        handoff of individual DNP tables and step execution stay in the image.
        """
        checked, source_list = _select_bams(bam=bam, bams=bams, bamlist=bamlist)
        panel = require_file(panel, "Pannello DNP")
        read_dnp_list(panel)
        contamination_panel = (panel if contamination_panel is None else
                               require_file(contamination_panel, "Pannello Contamination"))
        read_position_panel(contamination_panel)
        mounts = InputMounts(self.layout)
        panel_path = mounts.bind_file(panel, target=INPUT_ROOT / "dnp-panel.txt")
        contamination_panel_path = (
            panel_path if contamination_panel == panel else
            mounts.bind_file(contamination_panel, target=INPUT_ROOT / "contamination-panel.txt")
        )
        reference_path, reference_inputs = _bind_reference(mounts, reference)
        input_files = [*reference_inputs, panel]
        if contamination_panel != panel:
            input_files.append(contamination_panel)
        if source_list is not None:
            input_files.append(source_list)
        samples = []
        for number, path in enumerate(checked, 1):
            sample_id = f"sample_{number:04d}"
            target = INPUT_ROOT / "bams" / f"{sample_id}.bam"
            input_files.extend(_bind_bam(mounts, path, target))
            samples.append({"sample_id": sample_id, "original_path": str(path),
                            "container_path": str(target)})
        plan = {
            "schema_version": 1,
            "samples": [{"id": sample["sample_id"], "kind": "bam",
                         "path": sample["container_path"]} for sample in samples],
            "steps": [
                {"id": "dnp", "workflow": "dnp-call",
                 "inputs": {"samples": [sample["sample_id"] for sample in samples],
                            "reference": str(reference_path), "panel": str(panel_path)},
                 "parameters": {"parallel": parallel}},
                {"id": "contamination", "workflow": "contamination",
                 "inputs": {"samples": [
                     {"step": "dnp", "output": "dnp-tables", "sample": sample["sample_id"]}
                     for sample in samples
                 ], "panel": str(contamination_panel_path)},
                 "parameters": {}},
            ],
        }
        snp_panel = _append_snp_steps(plan, samples=samples, panel=snp_panel,
                                      reference=reference_path, mounts=mounts, input_files=input_files)
        # Reject invalid contracts before allocating an immutable run. The
        # bundled executor validates this same plan again against its version.
        plan = validate_plan(plan)["plan"]
        run_dir = self.layout.new_run_dir("dnp-contamination", run_name)
        with self.runner.record_run(
            run_dir, workflow="dnp-contamination", inputs=input_files, mounts=mounts,
            bundled_workflow="workflow-plan-with-snp" if snp_panel else "workflow-plan",
            parameters={"preset": "dnp-contamination",
                        "bams": [str(path) for path in checked],
                        "bamlist": str(source_list) if source_list else None,
                        "reference": str(reference_inputs[0]), "panel": str(panel),
                        "contamination_panel": str(contamination_panel),
                        "parallel": parallel, "sample_mapping": samples,
                        "snp_panel": str(snp_panel) if snp_panel else None,
                        "expected_steps": _expected_steps(plan)},
        ):
            plan_file = run_dir / "work" / "engine-plan.json"
            _write_engine_request(plan_file, plan)
            self.runner.run(
                ["python3", "/opt/nipat/engine/main.py", "execute-plan",
                 "--plan", self.layout.container_path(plan_file),
                 "--run-dir", self.layout.container_path(run_dir / "output" / "workflow")],
                working_dir=self.layout.container_path(run_dir / "work"),
            )
        return run_dir

    def dnp_cpi(
        self, *, pairs: list[tuple[str, Path, Path]], reference: Path, panel: Path,
        popfreq: Path, err_const: float = 0.0000892303778101497,
        cpi_panel: Path | None = None, cutoffs: list[tuple[str, Path]] | None = None,
        cutoff_map: str | None = None, include_contamination: bool = False,
        contamination_panel: Path | None = None, parallel: bool = False,
        snp_panel: Path | None = None,
        run_name: str | None = None,
    ) -> Path:
        """Execute explicit maternal/paternal BAM pairs in one image-owned plan."""
        if type(include_contamination) is not bool:
            raise ValidationError("La selezione del passaggio Contamination deve essere booleana.")
        if not include_contamination and contamination_panel is not None:
            raise ValidationError("Il pannello Contamination richiede il workflow con Contamination.")
        _validate_error_constant(err_const)
        if not isinstance(pairs, list) or not pairs:
            raise ValidationError("Indicare almeno una coppia: ID, BAM cfDNA materno e BAM paterno.")
        checked: list[Path] = []
        roles: dict[str, str] = {}
        selected_pairs = []
        pair_mapping = []
        for pair in pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 3:
                raise ValidationError("Ogni coppia richiede ID, BAM cfDNA materno e BAM paterno.")
            pair_id, mother, father = pair
            identities = {}
            original_paths = {}
            for role, path in (("mother", mother), ("father", father)):
                source = require_file(path, "BAM cfDNA materno" if role == "mother" else "BAM paterno")
                # Resolve both symbolic-link aliases and hard links so the same
                # physical file cannot acquire inconsistent biological roles.
                number = next((index for index, previous in enumerate(checked, 1)
                               if source == previous or source.samefile(previous)), None)
                if number is None:
                    checked.append(source)
                    number = len(checked)
                sample_id = f"sample_{number:04d}"
                if sample_id in roles and roles[sample_id] != role:
                    raise ValidationError(
                        "Lo stesso BAM non può rappresentare sia cfDNA materno sia campione paterno."
                    )
                roles[sample_id] = role
                identities[role] = sample_id
                original_paths[role] = str(source)
            selected_pairs.append({
                "id": pair_id,
                **{role: {"step": "dnp", "output": "dnp-tables", "sample": identities[role]}
                   for role in ("mother", "father")},
            })
            pair_mapping.append({
                "pair_id": pair_id, "mother_sample_id": identities["mother"],
                "father_sample_id": identities["father"],
                "mother_bam": original_paths["mother"], "father_bam": original_paths["father"],
            })
        panel = require_file(panel, "Pannello DNP")
        read_dnp_list(panel)
        popfreq = require_file(popfreq, "Tabella frequenze di popolazione")
        require_population_frequencies(popfreq)
        cutoff_mode, normalized_cutoffs = _select_cpi_cutoffs(
            panel=cpi_panel, cutoffs=cutoffs, cutoff_map=cutoff_map, panel_option="--cpi-panel",
        )
        if include_contamination:
            contamination_panel = (panel if contamination_panel is None else
                                   require_file(contamination_panel, "Pannello Contamination"))
            read_position_panel(contamination_panel)
        mounts = InputMounts(self.layout)
        panel_path = mounts.bind_file(panel, target=INPUT_ROOT / "dnp-panel.txt")
        reference_path, reference_inputs = _bind_reference(mounts, reference)
        popfreq_path = mounts.bind_file(popfreq, target=INPUT_ROOT / "population.tsv")
        input_files = [*reference_inputs, panel, popfreq]
        mapped_cutoffs = []
        for number, (label, source) in enumerate(normalized_cutoffs, 1):
            input_files.append(source)
            mapped_cutoffs.append({"label": label, "path": str(mounts.bind_file(
                source, target=INPUT_ROOT / "cpi-cutoffs" / f"panel_{number:03d}.tsv",
            ))})
        samples = []
        for number, path in enumerate(checked, 1):
            sample_id = f"sample_{number:04d}"
            target = INPUT_ROOT / "bams" / f"{sample_id}.bam"
            input_files.extend(_bind_bam(mounts, path, target))
            samples.append({"sample_id": sample_id, "original_path": str(path),
                            "container_path": str(target), "role": roles[sample_id]})
        steps = [{
            "id": "dnp", "workflow": "dnp-call",
            "inputs": {"samples": [sample["sample_id"] for sample in samples],
                       "reference": str(reference_path), "panel": str(panel_path)},
            "parameters": {"parallel": parallel},
        }]
        if include_contamination:
            contamination_panel_path = (panel_path if contamination_panel == panel else
                mounts.bind_file(contamination_panel, target=INPUT_ROOT / "contamination-panel.txt"))
            input_files.append(contamination_panel)
            steps.append({
                "id": "contamination", "workflow": "contamination",
                "inputs": {"samples": [
                    {"step": "dnp", "output": "dnp-tables", "sample": sample["sample_id"]}
                    for sample in samples
                ], "panel": str(contamination_panel_path)}, "parameters": {},
            })
        steps.append({
            "id": "cpi", "workflow": "cpi",
            "inputs": {"pairs": selected_pairs, "popfreq": str(popfreq_path), "cutoffs": mapped_cutoffs},
            "parameters": {"err_const": err_const, "cutoff_mode": cutoff_mode},
        })
        plan = {
            "schema_version": 1,
            "samples": [{"id": sample["sample_id"], "kind": "bam", "path": sample["container_path"]}
                        for sample in samples],
            "steps": steps,
        }
        snp_panel = _append_snp_steps(plan, samples=samples, panel=snp_panel,
                                      reference=reference_path, mounts=mounts, input_files=input_files)
        plan = validate_plan(plan)["plan"]
        preset = "dnp-contamination-cpi" if include_contamination else "dnp-cpi"
        run_dir = self.layout.new_run_dir(preset, run_name)
        with self.runner.record_run(
            run_dir, workflow=preset, inputs=list(dict.fromkeys(input_files)), mounts=mounts,
            bundled_workflow="workflow-plan-with-snp" if snp_panel else "workflow-plan-cpi",
            parameters={"preset": preset, "bams": [str(path) for path in checked],
                        "reference": str(reference_inputs[0]), "panel": str(panel),
                        "popfreq": str(popfreq), "err_const": err_const,
                        "cutoff_mode": cutoff_mode,
                        "cutoffs": [{"label": label, "path": str(source)}
                                    for label, source in normalized_cutoffs],
                        "include_contamination": include_contamination,
                        "contamination_panel": str(contamination_panel) if contamination_panel else None,
                        "parallel": parallel, "sample_mapping": samples, "pair_mapping": pair_mapping,
                        "snp_panel": str(snp_panel) if snp_panel else None,
                        "expected_steps": _expected_steps(plan)},
        ):
            plan_file = run_dir / "work" / "engine-plan.json"
            _write_engine_request(plan_file, plan)
            self.runner.run(
                ["python3", "/opt/nipat/engine/main.py", "execute-plan",
                 "--plan", self.layout.container_path(plan_file),
                 "--run-dir", self.layout.container_path(run_dir / "output" / "workflow")],
                working_dir=self.layout.container_path(run_dir / "work"),
            )
        return run_dir

    def snp_batch(
        self, *, bams: list[Path] | None = None, bamlist: Path | None = None,
        pileups: list[Path] | None = None, reference: Path | None = None,
        panel: Path, run_name: str | None = None,
    ) -> Path:
        """Run independent per-sample SNP analyses in one sequential image-owned plan."""
        if sum(value is not None for value in (bams, bamlist, pileups)) != 1:
            raise ValidationError("Indicare --bam, --bamlist oppure --pileup per il workflow SNPcall.")
        mode = "pileup" if pileups is not None else "bam"
        if mode == "bam" and reference is None:
            raise ValidationError("Con input BAM occorre indicare --reference.")
        if mode == "pileup" and reference is not None:
            raise ValidationError("--reference si usa soltanto con input BAM.")
        source_list = None
        if mode == "bam":
            checked, source_list = _select_bams(bam=None, bams=bams, bamlist=bamlist)
        else:
            if not isinstance(pileups, list) or not pileups:
                raise ValidationError("Indicare almeno un pileup SNP.")
            checked = [require_file(path, "Pileup SNP") for path in pileups]
            if any(path.samefile(previous) for index, path in enumerate(checked)
                   for previous in checked[:index]):
                raise ValidationError("Lo stesso pileup compare più volte nella lista.")
            for path in checked:
                require_snp_pileup(path)
        panel = require_file(panel, "Pannello SNP")
        read_snp_positions(panel, for_bed=mode == "bam")
        mounts = InputMounts(self.layout)
        panel_path = mounts.bind_file(panel, target=INPUT_ROOT / "snp-list.tsv")
        input_files = [panel]
        reference_path = None
        if mode == "bam":
            reference_path, reference_inputs = _bind_reference(mounts, reference)
            reference = reference_inputs[0]
            input_files.extend(reference_inputs)
        if source_list is not None:
            input_files.append(source_list)
        samples = []
        for number, path in enumerate(checked, 1):
            identifier = f"sample_{number:04d}"
            target = INPUT_ROOT / ("bams" if mode == "bam" else "pileups") / (
                f"{identifier}.bam" if mode == "bam" else f"{identifier}.txt")
            if mode == "bam":
                input_files.extend(_bind_bam(mounts, path, target))
            else:
                mounts.bind_file(path, target=target)
                input_files.append(path)
            samples.append({"sample_id": identifier, "original_path": str(path),
                            "container_path": str(target)})
        plan = validate_plan({
            "schema_version": 1,
            "samples": [{"id": sample["sample_id"], "kind": "bam" if mode == "bam" else "snp-pileup",
                         "path": sample["container_path"]} for sample in samples],
            "steps": _snp_steps(samples, panel=panel_path, reference=reference_path, mode=mode),
        })["plan"]
        run_dir = self.layout.new_run_dir("snp-batch", run_name)
        with self.runner.record_run(
            run_dir, workflow="snp-batch", inputs=input_files, mounts=mounts,
            bundled_workflow="workflow-plan-snp",
            parameters={"preset": "snp-batch", "mode": mode,
                        "bams": [str(path) for path in checked] if mode == "bam" else [],
                        "pileups": [str(path) for path in checked] if mode == "pileup" else [],
                        "bamlist": str(source_list) if source_list else None,
                        "reference": str(reference) if reference else None, "panel": str(panel),
                        "sample_mapping": samples, "expected_steps": _expected_steps(plan)},
        ):
            plan_file = run_dir / "work" / "engine-plan.json"
            _write_engine_request(plan_file, plan)
            self.runner.run(
                ["python3", "/opt/nipat/engine/main.py", "execute-plan",
                 "--plan", self.layout.container_path(plan_file),
                 "--run-dir", self.layout.container_path(run_dir / "output" / "workflow")],
                working_dir=self.layout.container_path(run_dir / "work"),
            )
        return run_dir

    def snp_call(
        self, *, bam: Path | None = None, pileup: Path | None = None,
        reference: Path | None = None, panel: Path, run_name: str | None = None,
    ) -> Path:
        if (bam is None) == (pileup is None):
            raise ValidationError("SNPcall richiede --bam oppure --pileup, non entrambi.")
        if bam is not None and reference is None:
            raise ValidationError("Con --bam occorre indicare --reference.")
        if pileup is not None and reference is not None:
            raise ValidationError("--reference si usa soltanto con --bam.")
        panel = require_file(panel, "Lista SNP")
        read_snp_positions(panel, for_bed=bam is not None)
        mounts = InputMounts(self.layout)
        panel_path = mounts.bind_file(panel, target=INPUT_ROOT / "snp-list.tsv")
        input_files = [panel]
        reference_path = None
        bam_path = None
        pileup_path = None
        if bam is not None:
            bam = require_file(bam, "BAM")
            bam_path = INPUT_ROOT / "bam" / "sample.bam"
            input_files.extend(_bind_bam(mounts, bam, bam_path))
            reference_path, reference_inputs = _bind_reference(mounts, reference)
            input_files.extend(reference_inputs)
            reference = reference_inputs[0]
        else:
            pileup = require_file(pileup, "Pileup SNP")
            require_snp_pileup(pileup)
            input_files.append(pileup)
            pileup_path = mounts.bind_file(pileup, target=INPUT_ROOT / "snp-pileup.txt")
        run_dir = self.layout.new_run_dir("snp-call", run_name)
        with self.runner.record_run(
            run_dir, workflow="snp-call", inputs=input_files, mounts=mounts,
            bundled_workflow="snp-call",
            parameters={"mode": "bam" if bam is not None else "pileup",
                        "bam": str(bam) if bam else None,
                        "pileup": str(pileup) if pileup else None,
                        "reference": str(reference) if reference else None, "panel": str(panel)},
        ):
            request = {
                "schema_version": 1, "workflow": "snp-call",
                "mode": "bam" if bam is not None else "pileup",
                "panel": str(panel_path),
                "bam": str(bam_path) if bam_path is not None else None,
                "pileup": str(pileup_path) if pileup_path is not None else None,
                "reference": str(reference_path) if reference_path is not None else None,
                "work_dir": str(self.layout.container_path(run_dir / "work")),
                "out_dir": str(self.layout.container_path(run_dir / "output")),
            }
            request_file = run_dir / "work" / "engine-request.json"
            _write_engine_request(request_file, request)
            self.runner.run(
                ["python3", "/opt/nipat/engine/main.py", "execute", "snp-call",
                 "--request", self.layout.container_path(request_file)],
                working_dir=self.layout.container_path(run_dir / "work"),
            )
        return run_dir

    def contamination(
        self, *, inputs: list[Path] | None = None, input_dir: Path | None = None,
        panel: Path, run_name: str | None = None,
    ) -> Path:
        if (inputs is None) == (input_dir is None):
            raise ValidationError("Indicare --input oppure --input-dir per Contamination.")
        panel = require_file(panel, "Pannello DNP")
        read_position_panel(panel)
        if input_dir is not None:
            input_dir = require_directory(input_dir, "Directory input Contamination")
            selected = sorted(
                (path for path in input_dir.rglob("*")
                 if path.is_file() and path.suffix.lower() in {".txt", ".tsv"}
                 and path.resolve() != panel),
                key=lambda path: str(path).casefold(),
            )
        else:
            selected = list(inputs or [])
        if not selected:
            raise ValidationError("Nessuna tabella di input per Contamination.")
        checked_inputs = []
        names = set()
        for input_path in selected:
            checked = require_file(input_path, "Output DNPcall")
            require_contamination_input(checked)
            name = (checked.stem + ".txt").casefold()
            if name in names:
                raise ValidationError(f"Nome file duplicato nello staging: {checked.stem}.txt")
            names.add(name)
            checked_inputs.append(checked)
        mounts = InputMounts(self.layout)
        panel_path = mounts.bind_file(panel, target=INPUT_ROOT / "contamination-panel.txt")
        samples = [
            {
                "path": str(mounts.bind_file(
                    source, target=INPUT_ROOT / "contamination" / f"sample_{number:04d}.txt",
                )),
                "name": f"{source.stem}.txt",
            }
            for number, source in enumerate(checked_inputs, 1)
        ]
        run_dir = self.layout.new_run_dir("contamination", run_name)
        with self.runner.record_run(
            run_dir, workflow="contamination", inputs=[panel, *checked_inputs],
            mounts=mounts, bundled_workflow="contamination",
            parameters={"panel": str(panel), "inputs": [str(path) for path in checked_inputs],
                        "input_dir": str(input_dir) if input_dir else None},
        ):
            request = {
                "schema_version": 1, "workflow": "contamination", "panel": str(panel_path),
                "samples": samples,
                "work_dir": str(self.layout.container_path(run_dir / "work")),
                "out_dir": str(self.layout.container_path(run_dir / "output")),
            }
            request_file = run_dir / "work" / "engine-request.json"
            _write_engine_request(request_file, request)
            self.runner.run(
                ["python3", "/opt/nipat/engine/main.py", "execute", "contamination",
                 "--request", self.layout.container_path(request_file)],
                working_dir=self.layout.container_path(run_dir / "work"),
            )
        return run_dir

    def cpi(
        self, *, input_dir: Path, pairs: str, mother_prefix: str, father_prefix: str,
        popfreq: Path, panel: Path | None = None,
        err_const: float = 0.0000892303778101497, run_name: str | None = None,
        cutoffs: list[tuple[str, Path]] | None = None, cutoff_map: str | None = None,
    ) -> Path:
        if sum((panel is not None, cutoffs is not None, cutoff_map is not None)) > 1:
            raise ValidationError("Scegliere --panel, --cutoff oppure --cutoff-map.")
        _validate_error_constant(err_const)
        input_dir = require_directory(input_dir, "Directory input CPI")
        popfreq = require_file(popfreq, "Tabella frequenze di popolazione")
        require_population_frequencies(popfreq)
        pairs, names = normalize_pairs(pairs, mother_prefix, father_prefix)
        mounts = InputMounts(self.layout)
        popfreq_path = mounts.bind_file(popfreq, target=INPUT_ROOT / "population.tsv")
        checked_inputs = [popfreq]
        samples = []
        for number, name in enumerate(names, 1):
            source = require_file(input_dir / name, "Tabella campione CPI")
            require_dnp_input(source)
            sample_path = mounts.bind_file(
                source, target=INPUT_ROOT / "cpi" / f"sample_{number:04d}.txt",
            )
            samples.append({"path": str(sample_path), "name": name})
            checked_inputs.append(source)
        cutoff_mode, normalized_cutoffs = _select_cpi_cutoffs(
            panel=panel, cutoffs=cutoffs, cutoff_map=cutoff_map,
        )
        checked_inputs.extend(source for _, source in normalized_cutoffs)
        mapped_cutoffs = [
            {"label": label, "path": str(mounts.bind_file(
                source, target=INPUT_ROOT / "cpi-cutoffs" / f"panel_{number:03d}.tsv",
            ))}
            for number, (label, source) in enumerate(normalized_cutoffs, 1)
        ]
        run_dir = self.layout.new_run_dir("cpi", run_name)
        with self.runner.record_run(
            run_dir, workflow="cpi", inputs=list(dict.fromkeys(checked_inputs)), mounts=mounts,
            bundled_workflow="cpi",
            parameters={"pairs": pairs, "mother_prefix": mother_prefix, "father_prefix": father_prefix,
                        "err_const": err_const, "input_dir": str(input_dir), "popfreq": str(popfreq),
                        "panel": str(panel) if panel else None,
                        "cutoff_mode": cutoff_mode,
                        "cutoffs": [{"label": label, "path": str(source)}
                                    for label, source in normalized_cutoffs]},
        ):
            request = {
                "schema_version": 1, "workflow": "cpi", "samples": samples,
                "pairs": pairs, "mother_prefix": mother_prefix, "father_prefix": father_prefix,
                "popfreq": str(popfreq_path), "cutoff_mode": cutoff_mode,
                "cutoffs": mapped_cutoffs, "err_const": err_const,
                "work_dir": str(self.layout.container_path(run_dir / "work")),
                "out_dir": str(self.layout.container_path(run_dir / "output")),
            }
            request_file = run_dir / "work" / "engine-request.json"
            _write_engine_request(request_file, request)
            self.runner.run(
                ["python3", "/opt/nipat/engine/main.py", "execute", "cpi",
                 "--request", self.layout.container_path(request_file)],
                working_dir=self.layout.container_path(run_dir / "work"),
            )
        return run_dir
