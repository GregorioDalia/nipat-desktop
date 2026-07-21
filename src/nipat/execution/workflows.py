from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

from nipat.adapters.panels import (
    read_dnp_list,
    read_snp_positions,
    write_position_panel,
    write_snp_bed,
)
from nipat.errors import ValidationError
from nipat.execution.runner import DockerComposeRunner
from nipat.paths import ProjectLayout
from nipat.validation.files import (
    DNP_OUTPUT_COLUMNS,
    require_columns,
    require_contamination_input,
    require_directory,
    require_file,
    require_sidecar,
)


class Workflows:
    def __init__(self, layout: ProjectLayout, runner: DockerComposeRunner) -> None:
        self.layout = layout
        self.runner = runner

    def _script(self, relative_path: str) -> PurePosixPath:
        return self.layout.container_path(self.layout.project_dir / relative_path)

    def dnp_call(
        self,
        *,
        bam: Path,
        reference: Path,
        panel: Path,
        parallel: bool,
        run_name: str | None,
    ) -> Path:
        bam = require_file(bam, "BAM")
        require_sidecar(bam, ".bai", "Indice BAM")
        reference = require_file(reference, "FASTA")
        require_sidecar(reference, ".fai", "Indice FASTA")
        panel = require_file(panel, "Pannello DNP")
        read_dnp_list(panel)
        for path in (bam, reference, panel):
            self.layout.container_path(path)

        run_dir = self.layout.new_run_dir("dnp-call", run_name)
        bamlist = run_dir / "work" / "bamlist.txt"
        bamlist.write_text(f"{self.layout.container_path(bam)}\n", encoding="utf-8")

        command: list[str | PurePosixPath] = [
            "Rscript",
            self._script("scientific/vendor/DNPcall/DNPcall.R"),
            f"--bamlist={self.layout.container_path(bamlist)}",
            f"--DNPs={self.layout.container_path(panel)}",
            f"--reference={self.layout.container_path(reference)}",
            f"--out={self.layout.container_path(run_dir / 'output')}",
        ]
        if parallel:
            command.append("--parallel")
        self.runner.run(
            command,
            working_dir=self.layout.container_path(run_dir / "work"),
        )
        return run_dir

    def snp_call(
        self,
        *,
        bam: Path,
        reference: Path,
        panel: Path,
        run_name: str | None,
    ) -> Path:
        bam = require_file(bam, "BAM")
        require_sidecar(bam, ".bai", "Indice BAM")
        reference = require_file(reference, "FASTA")
        require_sidecar(reference, ".fai", "Indice FASTA")
        panel = require_file(panel, "Lista SNP")
        positions = read_snp_positions(panel)
        for path in (bam, reference, panel):
            self.layout.container_path(path)

        run_dir = self.layout.new_run_dir("snp-call", run_name)
        bed_file = run_dir / "work" / "snp_regions.bed"
        pileup_file = run_dir / "work" / "pileup.txt"
        output_file = run_dir / "output" / "SNPcall_output.txt"
        write_snp_bed(positions, bed_file)

        self.runner.run(
            [
                "samtools",
                "mpileup",
                "-f",
                self.layout.container_path(reference),
                "-l",
                self.layout.container_path(bed_file),
                "--output-QNAME",
                "--no-output-ins",
                "--no-output-del",
                "--no-output-ends",
                "-o",
                self.layout.container_path(pileup_file),
                self.layout.container_path(bam),
            ],
            working_dir=self.layout.container_path(run_dir / "work"),
        )
        self.runner.run(
            [
                "Rscript",
                self._script("scientific/vendor/NEWPAT/SNPcall/SNPcall.R"),
                "--pileup",
                self.layout.container_path(pileup_file),
                "--snplist",
                self.layout.container_path(panel),
                "--out",
                self.layout.container_path(output_file),
            ],
            working_dir=self.layout.container_path(run_dir / "work"),
        )
        return run_dir

    def contamination(
        self,
        *,
        inputs: list[Path],
        panel: Path,
        run_name: str | None,
    ) -> Path:
        panel = require_file(panel, "Pannello DNP")
        records = read_dnp_list(panel)
        if not inputs:
            raise ValidationError("Indicare almeno un file DNPcall con --input.")
        checked_inputs: list[Path] = []
        for input_path in inputs:
            checked = require_file(input_path, "Output DNPcall")
            require_contamination_input(checked)
            self.layout.container_path(checked)
            checked_inputs.append(checked)

        run_dir = self.layout.new_run_dir("contamination", run_name)
        staged_dir = run_dir / "work" / "inputs"
        staged_dir.mkdir()
        for input_path in checked_inputs:
            destination = staged_dir / input_path.name
            if destination.exists():
                raise ValidationError(f"Nome file duplicato negli input: {input_path.name}")
            shutil.copy2(input_path, destination)

        position_panel = run_dir / "work" / "DNPpanel.txt"
        write_position_panel(records, position_panel)
        self.runner.run(
            [
                "Rscript",
                self._script("scientific/vendor/NEWPAT/contamination/detect_contamination.R"),
                self.layout.container_path(position_panel),
                self.layout.container_path(staged_dir),
                self.layout.container_path(run_dir / "output"),
            ],
            working_dir=self.layout.container_path(run_dir / "work"),
        )
        return run_dir

    def cpi(
        self,
        *,
        input_dir: Path,
        pairs: str,
        mother_prefix: str,
        father_prefix: str,
        popfreq: Path,
        panel: Path | None,
        err_const: float,
        run_name: str | None,
    ) -> Path:
        input_dir = require_directory(input_dir, "Directory input CPI")
        popfreq = require_file(popfreq, "Tabella frequenze di popolazione")
        require_columns(
            popfreq,
            {"chr", "pos1", "pos2", "Ref_f.pop", "Alt_f.pop"},
            "Frequenze di popolazione non compatibili",
        )
        self.layout.container_path(input_dir)
        self.layout.container_path(popfreq)

        for pair in (part.strip() for part in pairs.split(",")):
            identifiers = pair.split(":")
            if len(identifiers) != 2 or not all(identifiers):
                raise ValidationError(f"Coppia CPI non valida: {pair}")
            mother = require_file(input_dir / f"{mother_prefix}{identifiers[0]}.txt", "Madre")
            father = require_file(input_dir / f"{father_prefix}{identifiers[1]}.txt", "Padre")
            require_columns(mother, DNP_OUTPUT_COLUMNS, "Input madre non compatibile")
            require_columns(father, DNP_OUTPUT_COLUMNS, "Input padre non compatibile")

        cutoff: Path | None = None
        if panel is not None:
            panel = require_file(panel, "Pannello DNP")
            records = read_dnp_list(panel)
            run_dir = self.layout.new_run_dir("cpi", run_name)
            cutoff = run_dir / "work" / "DNPpanel.txt"
            write_position_panel(records, cutoff)
        else:
            run_dir = self.layout.new_run_dir("cpi", run_name)

        command: list[str | PurePosixPath] = [
            "Rscript",
            self._script("scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R"),
            "--pileup_dir",
            self.layout.container_path(input_dir),
            "--out_dir",
            self.layout.container_path(run_dir / "output"),
            "--pairs",
            pairs,
            "--mother_prefix",
            mother_prefix,
            "--father_prefix",
            father_prefix,
            "--popfreq",
            self.layout.container_path(popfreq),
            "--err_const",
            str(err_const),
        ]
        if cutoff is not None:
            command.extend(["--cutoff_map", self.layout.container_path(cutoff)])
        self.runner.run(command, working_dir=self.layout.container_path(run_dir / "work"))
        return run_dir
