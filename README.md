# NIPAT Desktop

**CLI 0.2.0a2, being prepared for domain validation.** Start with the Italian
[project overview](SUNTO.md) and [tester guide](docs/GUIDA_COLLEGA.md).
This revision accepts user-selected input locations and exposes the native
input modes of the four scientific workflows. Windows setup, self-tests and
a real-BAM DNPcall regression passed on the maintainer's PC on 2026-10-20.
See the [validation evidence](docs/DISTRIBUZIONE.md); the existing `v0.2.0a1`
tag remains unchanged.

On Windows x64, `1_SETUP.cmd` prepares local Python, the Docker runtime and
bundled self-tests; `2_AVVIA.cmd` opens a text wizard. Testers obtain a versioned
source archive from GitHub, following the [distribution guide](docs/DISTRIBUZIONE.md).
Docker Desktop with Linux containers is currently a manual prerequisite.

Python handles input validation, mechanical format adaptation and execution;
the scientific calculations remain in the DNPcall and NEWPAT R scripts.
The desktop GUI will use the same application layer after CLI validation.

## Input locations and results

Select existing files wherever they are stored on the computer. NIPAT mounts
the selected inputs read-only for each run; large BAM/FASTA files do not need
to be copied into the project. Container aliases handle paths containing spaces
and preserve the association with the original files in the run metadata.

By default, `data` and `runs` are beside the project. `data` is a convenience
directory, not a boundary for input selection. Use global `--data-dir` and
`--runs-dir`, or `NIPAT_DATA_DIR` and `NIPAT_RUNS_DIR`, to choose other locations.
Wizard option **5 — Cartella risultati** changes the results root for the
remaining session. Global options precede the subcommand. Relative paths are resolved from the
calling terminal's current directory; entries in a BAM list are resolved from
the list's directory. There is no required drive letter or project folder name.

Each analysis creates a new subdirectory under the selected results root,
containing `output`, `work`, `run.json` and `execution.log`. Existing runs are
never overwritten. See [execution records](docs/ESECUZIONI.md).

## Workflow examples

Run these commands from the extracted project directory. Replace the example
paths with your files; all input modes are also available in `2_AVVIA.cmd`.

```powershell
$samples = "..\campioni"
$reference = "..\riferimenti\genome.fa"
$panels = "..\pannelli"
$runs = "..\risultati"

.\nipat.cmd --runs-dir $runs dnp-call `
  --bam "$samples\sample1.bam" --bam "$samples\sample2.bam" `
  --reference $reference --panel "$panels\DNP_list.txt"

.\nipat.cmd --runs-dir $runs snp-call `
  --pileup "$samples\sample.pileup" --panel "$panels\SNPlist.txt"

.\nipat.cmd --runs-dir $runs contamination `
  --input-dir "$samples\DNPcall_outputs" --panel "$panels\DNPpanel.txt"

.\nipat.cmd --runs-dir $runs cpi `
  --input-dir "$samples\cpi" --pairs "A1:A1,A2:A2" `
  --popfreq "$panels\pop_allFreq.txt" `
  --cutoff panel1 "$panels\DNPpanel1.txt" `
  --cutoff panel2 "$panels\DNPpanel2.txt"
```

| Workflow | Supported input modes |
| --- | --- |
| DNPcall | Repeated `--bam` or `--bamlist`, plus FASTA and the five-column DNP panel; optional `--parallel`. |
| SNPcall | `--bam` with `--reference`, or a ready `--pileup` with at least seven samtools columns and QNAME in column 7; SNP panel in either mode. |
| Contamination | Repeated `--input` or recursive `--input-dir` for TXT/TSV files, plus a DNP coordinate panel. |
| CPI | Pair tables and population frequencies; optional `--panel`, repeated `--cutoff LABEL PATH`, or native `--cutoff-map`. With no filter, use all sites. |

FASTA input requires its `.fai` sidecar, and BGZF FASTA also requires `.gzi`.
BAM indexes are optional for the current `samtools mpileup -l` path.
DNPcall uses numbered sample aliases; the original-name mapping is retained
with the run. Its small DNP panel is normalized in `work`, with uppercase
REF/ALT alleles; the original remains unchanged. For one sample, the UpSet
plot is intentionally omitted.
Contamination accepts inputs without `ratio_REF_ALT`: the upstream script
calculates it from REF/ALT counts. Estimates are fractions, so `0.025` means 2.5%.
The default CPI `--err-const` remains `0.0000892303778101497` and is editable
in the wizard or CLI. See the [tester guide](docs/GUIDA_COLLEGA.md) for formats.

## Checks and development

After setup, repeat the runtime checks with:

```powershell
.\nipat.cmd doctor --runtime
.\nipat.cmd self-test
.\.runtime\python\python.exe scripts/verify_input_modes.py
```

The self-test runs four check groups: the SNP reference example, synthetic
CPI and Contamination regressions, and the new external-input checks. The last
group exercises direct SNP pileup, recursive Contamination input and CPI with
two labeled cutoffs or all sites; the standalone script repeats that group.
These checks require Docker and do not add numerical DNPcall-from-BAM coverage.
All four groups passed on Windows. A separate DNPcall run from a real BAM,
using external inputs and a different results root, reproduced all 11 rows
and 17 columns of its previous individual output. These checks support the
validation handoff; domain testing and installation on another PC remain.

For development, use Python 3.12 from a project virtual environment, install
with `python -m pip install -e ".[dev]"`, then run `nipat build-runtime` and
`python -m unittest discover -s tests -v` from the repository root.

- Keep genomic inputs, generated results and local environments outside Git.
- Preserve upstream archives. Document scientific source changes in
  `scientific/README.md` and update `scientific/SHA256SUMS`.
- Use global `--dry-run` before a workflow to check inputs and inspect commands.
  It prepares a new run recorded as `planned`, without executing the analysis.
