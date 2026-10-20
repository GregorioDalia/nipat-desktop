from __future__ import annotations

import math
import shutil
from pathlib import Path, PurePosixPath

from nipat.adapters.panels import (
    read_dnp_list,
    read_position_panel,
    read_snp_positions,
    write_dnp_list,
    write_position_panel,
    write_snp_bed,
)
from nipat.errors import ValidationError
from nipat.execution.mounts import INPUT_ROOT, InputMounts
from nipat.execution.runner import DockerComposeRunner
from nipat.paths import ProjectLayout
from nipat.validation.files import (
    DNP_OUTPUT_COLUMNS,
    require_columns,
    require_contamination_input,
    require_directory,
    require_file,
    require_sidecar,
    require_snp_pileup,
)


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


def _name_component(value: str, label: str, *, empty: bool = False) -> str:
    if (not value and not empty) or any(c in value for c in "/\\") or any(
        ord(c) < 32 or ord(c) == 127 for c in value
    ):
        raise ValidationError(f"{label} deve essere un nome, senza separatori di cartella: {value!r}")
    return value


class Workflows:
    def __init__(self, layout: ProjectLayout, runner: DockerComposeRunner) -> None:
        self.layout = layout
        self.runner = runner

    def _script(self, relative_path: str) -> PurePosixPath:
        return self.layout.container_path(self.layout.project_dir / relative_path)

    def dnp_call(
        self, *, bam: Path | None = None, bams: list[Path] | None = None,
        bamlist: Path | None = None, reference: Path, panel: Path,
        parallel: bool = False, run_name: str | None = None,
    ) -> Path:
        if sum((bam is not None, bams is not None, bamlist is not None)) != 1:
            raise ValidationError("Indicare uno o più --bam oppure un solo --bamlist.")
        source_list = None
        if bamlist is not None:
            source_list = require_file(bamlist, "Lista BAM")
            selected = []
            for line in source_list.read_text(encoding="utf-8-sig").splitlines():
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
        if len(set(checked)) != len(checked):
            raise ValidationError("Lo stesso BAM compare più volte nella lista.")
        panel = require_file(panel, "Pannello DNP")
        records = read_dnp_list(panel)
        mounts = InputMounts(self.layout)
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
            parameters={"bams": [str(path) for path in checked],
                        "bamlist": str(source_list) if source_list else None,
                        "reference": str(reference_inputs[0]), "panel": str(panel),
                        "parallel": parallel, "sample_mapping": samples},
        ):
            normalized_panel = run_dir / "work" / "DNP_list.txt"
            write_dnp_list(records, normalized_panel)
            panel_path = self.layout.container_path(normalized_panel)
            generated_list = run_dir / "work" / "bamlist.txt"
            generated_list.write_text(
                "".join(sample["container_path"] + "\n" for sample in samples), encoding="utf-8",
            )
            command: list[str | PurePosixPath] = [
                "Rscript", self._script("scientific/vendor/DNPcall/DNPcall.R"),
                f"--bamlist={self.layout.container_path(generated_list)}",
                f"--DNPs={panel_path}", f"--reference={reference_path}", "--out=output",
            ]
            if parallel:
                command.append("--parallel")
            self.runner.run(command, working_dir=self.layout.container_path(run_dir))
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
        positions = read_snp_positions(panel, for_bed=bam is not None)
        mounts = InputMounts(self.layout)
        panel_path = mounts.bind_file(panel, target=INPUT_ROOT / "snp-list.tsv")
        input_files = [panel]
        reference_path = None
        bam_path = None
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
            parameters={"mode": "bam" if bam is not None else "pileup",
                        "bam": str(bam) if bam else None,
                        "pileup": str(pileup) if pileup else None,
                        "reference": str(reference) if reference else None, "panel": str(panel)},
        ):
            if bam is not None:
                bed_file = run_dir / "work" / "snp_regions.bed"
                write_snp_bed(positions, bed_file)
                pileup_path = self.layout.container_path(run_dir / "work" / "pileup.txt")
                self.runner.run(
                    ["samtools", "mpileup", "-f", reference_path,
                     "-l", self.layout.container_path(bed_file), "--output-QNAME",
                     "--no-output-ins", "--no-output-del", "--no-output-ends",
                     "-o", pileup_path, bam_path],
                    working_dir=self.layout.container_path(run_dir / "work"),
                )
            self.runner.run(
                ["Rscript", self._script("scientific/vendor/NEWPAT/SNPcall/SNPcall.R"),
                 "--pileup", pileup_path, "--snplist", panel_path, "--out",
                 self.layout.container_path(run_dir / "output" / "SNPcall_output.txt")],
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
        records = read_position_panel(panel)
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
        run_dir = self.layout.new_run_dir("contamination", run_name)
        with self.runner.record_run(
            run_dir, workflow="contamination", inputs=[panel, *checked_inputs],
            parameters={"panel": str(panel), "inputs": [str(path) for path in checked_inputs],
                        "input_dir": str(input_dir) if input_dir else None},
        ):
            staged_dir = run_dir / "work" / "inputs"
            staged_dir.mkdir()
            for input_path in checked_inputs:
                # Small tables are copied byte-for-byte with the extension R expects.
                shutil.copy2(input_path, staged_dir / f"{input_path.stem}.txt")
            position_panel = run_dir / "work" / "DNPpanel.txt"
            write_position_panel(records, position_panel)
            self.runner.run(
                ["Rscript",
                 self._script("scientific/vendor/NEWPAT/contamination/detect_contamination.R"),
                 self.layout.container_path(position_panel), self.layout.container_path(staged_dir),
                 self.layout.container_path(run_dir / "output")],
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
        if not math.isfinite(err_const) or err_const < 0:
            raise ValidationError("La costante di errore deve essere finita e non negativa.")
        input_dir = require_directory(input_dir, "Directory input CPI")
        popfreq = require_file(popfreq, "Tabella frequenze di popolazione")
        require_columns(popfreq, {"chr", "pos1", "pos2", "Ref_f.pop", "Alt_f.pop"},
                        "Frequenze di popolazione non compatibili")
        _name_component(mother_prefix, "Prefisso madre", empty=True)
        _name_component(father_prefix, "Prefisso padre", empty=True)
        mounts = InputMounts(self.layout)
        popfreq_path = mounts.bind_file(popfreq, target=INPUT_ROOT / "population.tsv")
        checked_inputs = [popfreq]
        normalized_pairs = []
        for pair in pairs.split(","):
            identifiers = [part.strip() for part in pair.split(":")]
            if len(identifiers) != 2 or not all(identifiers):
                raise ValidationError(f"Coppia CPI non valida: {pair}")
            for label, prefix, identifier in (
                ("Madre", mother_prefix, identifiers[0]),
                ("Padre", father_prefix, identifiers[1]),
            ):
                _name_component(identifier, f"Identificativo {label}")
                name = f"{prefix}{identifier}.txt"
                source = require_file(input_dir / name, label)
                require_columns(source, DNP_OUTPUT_COLUMNS,
                                f"Input {label.lower()} non compatibile", whitespace=True)
                mounts.bind_file(source, target=INPUT_ROOT / "cpi" / name)
                checked_inputs.append(source)
            normalized_pairs.append(":".join(identifiers))
        if len(set(normalized_pairs)) != len(normalized_pairs):
            raise ValidationError("Coppia CPI duplicata.")
        pairs = ",".join(normalized_pairs)
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
            records = read_position_panel(source)
            normalized_cutoffs.append((label, source, records))
            checked_inputs.append(source)
        run_dir = self.layout.new_run_dir("cpi", run_name)
        with self.runner.record_run(
            run_dir, workflow="cpi", inputs=list(dict.fromkeys(checked_inputs)), mounts=mounts,
            parameters={"pairs": pairs, "mother_prefix": mother_prefix, "father_prefix": father_prefix,
                        "err_const": err_const, "input_dir": str(input_dir), "popfreq": str(popfreq),
                        "panel": str(panel) if panel else None,
                        "cutoffs": [{"label": label, "path": str(source)}
                                    for label, source, _ in normalized_cutoffs]},
        ):
            command: list[str | PurePosixPath] = [
                "Rscript", self._script("scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R"),
                "--pileup_dir", INPUT_ROOT / "cpi",
                "--out_dir", self.layout.container_path(run_dir / "output"),
                "--pairs", pairs, "--mother_prefix", mother_prefix,
                "--father_prefix", father_prefix, "--popfreq", popfreq_path,
                "--err_const", str(err_const),
            ]
            maps = []
            for number, (label, _, records) in enumerate(normalized_cutoffs, 1):
                filename = "DNPpanel.txt" if panel is not None else f"cutoff_{number:03d}.tsv"
                destination = run_dir / "work" / filename
                write_position_panel(records, destination)
                mapped = str(self.layout.container_path(destination))
                maps.append(f"{label}={mapped}" if label else mapped)
            if maps:
                command.extend(["--cutoff_map", ",".join(maps)])
            self.runner.run(command, working_dir=self.layout.container_path(run_dir / "work"))
        return run_dir
