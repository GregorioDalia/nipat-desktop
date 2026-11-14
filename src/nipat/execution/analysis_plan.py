"""Build typed caller/consumer plans from explicit sample and family identities."""
from __future__ import annotations

from collections.abc import Collection
from pathlib import Path
import re

from nipat.errors import ValidationError
from nipat.execution.mounts import INPUT_ROOT, InputMounts
from nipat.validation.files import require_file, require_snp_pileup
from nipat_scientific.files import require_count_input, require_population_frequencies
from nipat_scientific.panels import read_dnp_list, read_position_panel, read_snp_positions

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,47}\Z")
_CONSUMERS = ("contamination", "cpi", "cpin")
_CALLERS = {"dnp": ("DNP",), "snp": ("SNP",), "both": ("DNP", "SNP"), "tables": ()}
FAMILY_ROLES = {"cpi": ("mother", "father"), "cpin": ("mother", "father", "child")}


def active_analysis_branches(
    caller: str, analyses: list[str], dnp_analyses: list[str] | None = None,
    snp_analyses: list[str] | None = None, *, table_markers: Collection[str] = (),
) -> dict[str, list[str]]:
    """Select callers and imports whose counts go into a downstream analysis."""
    if caller not in _CALLERS:
        raise ValidationError("Caller: scegliere dnp, snp, both oppure tables.")
    overrides = {"DNP": dnp_analyses, "SNP": snp_analyses}
    for selected in (analyses, *(value for value in overrides.values() if value is not None)):
        if (not isinstance(selected, list) or any(not isinstance(name, str) for name in selected)
                or len(selected) != len(set(selected)) or set(selected) - set(_CONSUMERS)):
            raise ValidationError("Analisi: scegliere una combinazione senza ripetizioni di contamination, cpi e cpin.")
    branches = {}
    for marker, override in overrides.items():
        selected = analyses if override is None else override
        if marker in _CALLERS[caller] or (marker in table_markers and selected):
            branches[marker] = selected
        elif override:
            raise ValidationError(f"Analisi {marker} richieste senza conteggi {marker} disponibili.")
    return branches


def validate_families(entries, roles: tuple[str, ...], branch_samples: Collection[str], marker: str) -> None:
    """Check explicit IDs and consistent role assignments within one analysis."""
    ids = set()
    assignments = {}
    for entry in entries:
        if not isinstance(entry, (tuple, list)) or len(entry) != len(roles) + 1:
            raise ValidationError("Ruoli familiari incompleti.")
        identifier, *members = entry
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or identifier.casefold() in ids:
            raise ValidationError("ID famiglia non valido o duplicato: " + str(identifier))
        ids.add(identifier.casefold())
        for member in members:
            if not isinstance(member, str) or member not in branch_samples:
                raise ValidationError(f"{identifier}: campione {member} non disponibile nel ramo {marker}.")
        if len(set(members)) != len(members):
            raise ValidationError(f"{identifier}: i ruoli della stessa famiglia richiedono campioni distinti.")
        for role, member in zip(roles, members):
            if member in assignments and assignments[member] != role:
                raise ValidationError(f"{member}: ruoli biologici incompatibili fra famiglie della stessa analisi.")
            assignments[member] = role


def build_analysis_plan(*, layout, caller: str, analyses: list[str],
                        samples=None, pileups=None, dnp_tables=None, snp_tables=None,
                        dnp_analyses=None, snp_analyses=None,
                        pairs=None, trios=None, reference=None,
                        dnp_panel=None, snp_panel=None, dnp_popfreq=None, snp_popfreq=None,
                        dnp_contamination_panel=None, snp_contamination_panel=None,
                        dnp_cpi_cutoffs=None, snp_cpi_cutoffs=None,
                        dnp_cpin_panel=None, snp_cpin_panel=None):
    from nipat.execution.workflows import _bind_bam, _bind_reference, _select_cpi_cutoffs

    table_markers = [marker for marker, tables in (("DNP", dnp_tables), ("SNP", snp_tables)) if tables]
    branch_analyses = active_analysis_branches(caller, analyses, dnp_analyses, snp_analyses,
                                               table_markers=table_markers)
    samples, pileups = list(samples or []), list(pileups or [])
    if caller == "tables" and (samples or pileups or reference):
        raise ValidationError("La modalita' tables usa tabelle esistenti, senza BAM, pileup o FASTA.")
    if caller != "tables" and not samples and not pileups:
        raise ValidationError("Indicare almeno un campione BAM oppure pileup SNP.")
    if caller in {"dnp", "both"} and not samples:
        raise ValidationError("DNPcall richiede almeno un campione BAM.")
    if pileups and caller not in {"snp", "both"}:
        raise ValidationError("I pileup esistenti si usano con SNPcall.")
    if samples and reference is None:
        raise ValidationError("I BAM richiedono un FASTA indicizzato (--reference).")
    if not samples and reference is not None:
        raise ValidationError("Il FASTA si usa soltanto con campioni BAM.")
    if caller == "tables" and not branch_analyses:
        raise ValidationError("Per tabelle esistenti selezionare almeno un ramo con tabelle e una analisi.")
    planned_analyses = set().union(*branch_analyses.values())
    if pairs and "cpi" not in planned_analyses:
        raise ValidationError("Le coppie richiedono l'analisi CPI prenatale.")
    if trios and "cpin" not in planned_analyses:
        raise ValidationError("I trii richiedono l'analisi CPIN postnatale.")
    if "cpi" in planned_analyses and not pairs:
        raise ValidationError("CPI richiede coppie esplicite: ID, campione cfDNA materno, padre.")
    if "cpin" in planned_analyses and not trios:
        raise ValidationError("CPIN richiede trii espliciti: ID, madre, padre, figlio.")

    mounts = InputMounts(layout)
    input_files, mapping, plan_samples, steps = [], [], [], []
    references = {"DNP": {}, "SNP": {}}
    physical_samples = {}
    known_ids = set()
    input_identities = {}

    def bind(source, label, relative, validator=None):
        path = require_file(Path(source), label)
        if validator:
            validator(path)
        input_files.append(path)
        return str(mounts.bind_file(path, target=INPUT_ROOT / relative))

    def identified(entries, kind, branch=None):
        collected = []
        branch_ids = set()
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValidationError("Ogni campione richiede ID e percorso.")
            identifier, source = entry
            if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
                raise ValidationError("ID campione: 1-48 lettere ASCII, numeri, '-' o '_', iniziando con una lettera.")
            if identifier.casefold() in branch_ids or identifier.casefold() in {key.casefold() for key in references.get(branch, {})}:
                raise ValidationError(f"ID campione duplicato nella stessa analisi: {identifier}")
            branch_ids.add(identifier.casefold())
            # External tables have separate plan identities; biological IDs are
            # shared between SNP and DNP branches only by explicit declaration.
            plan_id = f"{branch.lower()}_{identifier}" if branch else identifier
            if plan_id.casefold() in known_ids:
                raise ValidationError(f"ID campione ambiguo: {identifier}")
            known_ids.add(plan_id.casefold())
            path = require_file(Path(source), "Campione " + identifier)
            identity_group = branch or kind
            previous_paths = input_identities.setdefault(identity_group, [])
            if any(path.samefile(previous) for previous in previous_paths):
                raise ValidationError("Lo stesso file compare con piu' identificativi: usare un unico ID e riutilizzarlo nei ruoli.")
            previous_paths.append(path)
            if kind == "bam":
                if any(path.samefile(previous) for previous in physical_samples.values()):
                    raise ValidationError("Lo stesso BAM compare con piu' identificativi: usare un unico ID e riutilizzarlo nei ruoli.")
                target = INPUT_ROOT / "bams" / f"sample_{len(physical_samples) + 1:04d}.bam"
                input_files.extend(_bind_bam(mounts, path, target))
                physical_samples[identifier] = path
            elif kind == "snp-pileup":
                require_snp_pileup(path)
                target = INPUT_ROOT / "pileups" / f"{plan_id}.txt"
                mounts.bind_file(path, target=target)
                input_files.append(path)
            else:
                require_count_input(path, branch, cpi=bool(set(branch_analyses[branch]) & {"cpi", "cpin"}))
                target = INPUT_ROOT / "tables" / f"{plan_id}.txt"
                mounts.bind_file(path, target=target)
                input_files.append(path)
                references[branch][identifier] = {"sample": plan_id}
            plan_samples.append({"id": plan_id, "kind": kind, "path": str(target)})
            mapping.append({"sample_id": plan_id, "biological_id": identifier,
                            "original_path": str(path), "container_path": str(target)})
            collected.append(identifier)
        return collected

    bam_ids = identified(samples, "bam")
    pileup_ids = identified(pileups, "snp-pileup")
    reference_target = None
    if samples:
        reference_target, reference_inputs = _bind_reference(mounts, Path(reference))
        input_files.extend(reference_inputs)
    panels = {"DNP": None, "SNP": None}
    if caller in {"dnp", "both"}:
        if dnp_panel is None:
            raise ValidationError("DNPcall richiede --dnp-panel.")
        panels["DNP"] = bind(dnp_panel, "Pannello DNP", "dnp-panel.txt", read_dnp_list)
        steps.append({"id": "dnp", "workflow": "dnp-call", "inputs": {
            "samples": bam_ids, "reference": str(reference_target), "panel": panels["DNP"]},
            "parameters": {"parallel": False}})
        references["DNP"].update({sid: {"step": "dnp", "output": "dnp-tables", "sample": sid}
                                   for sid in bam_ids})
    if caller in {"snp", "both"}:
        if snp_panel is None:
            raise ValidationError("SNPcall richiede --snp-panel.")
        panels["SNP"] = bind(snp_panel, "Pannello SNP", "snp-panel.tsv",
                              lambda path: read_snp_positions(path, for_bed=bool(bam_ids)))
        for number, sid in enumerate([*bam_ids, *pileup_ids], 1):
            step_id = f"snp_{number:04d}"
            is_bam = sid in bam_ids
            steps.append({"id": step_id, "workflow": "snp-call", "inputs": {
                "sample": sid, "reference": str(reference_target) if is_bam else None,
                "panel": panels["SNP"]}, "parameters": {"mode": "bam" if is_bam else "pileup"}})
            references["SNP"][sid] = {"step": step_id, "output": "snp-tables", "sample": sid}
    for marker, tables in (("DNP", dnp_tables), ("SNP", snp_tables)):
        if branch_analyses.get(marker) and tables:
            identified(tables, f"{marker.lower()}-table", marker)

    def family(entries, roles, marker):
        refs = references[marker]
        validate_families(entries, roles, refs, marker)
        return [{"id": identifier, **{role: refs[member] for role, member in zip(roles, members)}}
                for identifier, *members in entries]

    for marker, selected_analyses in branch_analyses.items():
        refs = references[marker]
        prefix = marker.lower()
        freq = dnp_popfreq if marker == "DNP" else snp_popfreq
        popfreq_target = None
        if set(selected_analyses) & {"cpi", "cpin"}:
            if freq is None:
                raise ValidationError(f"CPI/CPIN richiede --{prefix}-popfreq per il ramo {marker}.")
            popfreq_target = bind(freq, "Frequenze " + marker, f"{prefix}-population.tsv",
                                  lambda path: require_population_frequencies(path, marker))
        if "contamination" in selected_analyses:
            selected_panel = dnp_contamination_panel if marker == "DNP" else snp_contamination_panel
            target = panels[marker]
            if selected_panel is not None:
                target = bind(selected_panel, "Pannello Contamination " + marker,
                              f"{prefix}-contamination-panel.tsv", lambda path: read_position_panel(path, marker))
            if target is None:
                raise ValidationError(f"Le tabelle importate richiedono --{prefix}-contamination-panel.")
            steps.append({"id": f"{prefix}_contamination", "workflow": "contamination",
                          "inputs": {"samples": list(refs.values()), "panel": target},
                          "parameters": {"marker_type": marker}})
        if "cpi" in selected_analyses:
            cutoff_spec = dnp_cpi_cutoffs if marker == "DNP" else snp_cpi_cutoffs
            cutoff_mode, cutoffs = _select_cpi_cutoffs(panel=None, cutoffs=cutoff_spec,
                                                       cutoff_map=None, marker_type=marker)
            mapped_cutoffs = [{"label": label, "path": bind(path, "Cutoff CPI", f"{prefix}-cutoffs/{i}.tsv")}
                              for i, (label, path) in enumerate(cutoffs, 1)]
            steps.append({"id": f"{prefix}_cpi", "workflow": "cpi", "inputs": {
                "pairs": family(pairs, FAMILY_ROLES["cpi"], marker),
                "popfreq": popfreq_target, "cutoffs": mapped_cutoffs},
                "parameters": {"cutoff_mode": cutoff_mode, "marker_type": marker}})
        if "cpin" in selected_analyses:
            marker_panel = dnp_cpin_panel if marker == "DNP" else snp_cpin_panel
            def check_cpin_panel(path):
                records = read_position_panel(path, marker)
                if any(not record.reference or not record.alternative for record in records):
                    raise ValidationError("Il pannello CPIN richiede anche gli alleli REF e ALT.")
            target = (bind(marker_panel, "Pannello CPIN " + marker, f"{prefix}-cpin-panel.tsv",
                           check_cpin_panel) if marker_panel is not None else None)
            steps.append({"id": f"{prefix}_cpin", "workflow": "cpin", "inputs": {
                "trios": family(trios, FAMILY_ROLES["cpin"], marker),
                "popfreq": popfreq_target, "markers": target}, "parameters": {"marker_type": marker}})
    presentation = {"samples": {item["sample_id"]: Path(item["original_path"]).name for item in mapping}, "pairs": {}}
    return ({"schema_version": 1, "samples": plan_samples, "steps": steps,
             "presentation": presentation}, mounts, list(dict.fromkeys(input_files)), mapping, branch_analyses)
