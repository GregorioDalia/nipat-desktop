# NIPAT Desktop

**Development candidate: CLI 0.3.0a2 — guided terminal experience.**
The published Windows installer remains **v0.3.0a1**, for domain testing with
working WSL2. The new interface is described in the
[0.3.0a2 candidate notes](docs/RELEASE_0.3.0a2.md).
Start with the Italian [project overview](SUNTO.md) and
[usage guide](docs/GUIDA_UTILIZZO.md).

The new distribution builds `NIPAT-Setup.exe` on GitHub. It prepares portable
Python and a dedicated WSL2 environment with Docker Engine, imports a prebuilt
scientific image, and runs self-tests. Docker Desktop is not required for this
installation mode. Initial WSL activation can require administrator consent
and a restart; setup resumes under the original Windows account.
The initial installer target is **Windows 11 x64**.

The current testing scope assumes **WSL2 is already working**. Download
`NIPAT-Setup.exe` from the versioned GitHub release and wait for `NIPAT: ready`
before starting analyses. Initial WSL activation and Windows restart/resume
on a clean PC remain unverified. See the
[installer evidence and remaining checks](docs/INSTALLATORE_WINDOWS.md).
The published `v0.2.0a2` remains unchanged and uses the source archive plus
Docker Desktop. The source setup (`1_SETUP.cmd`, then `2_AVVIA.cmd`) remains
available. See [distribution and prior evidence](docs/DISTRIBUZIONE.md).

Python handles input validation, mechanical format adaptation and execution;
the scientific calculations remain in the DNPcall and NEWPAT R scripts.
The desktop GUI will use the same application layer after CLI validation.

## Guided CLI candidate (0.3.0a2)

The source candidate adds a NIPAT banner with version, a vertical menu and
arrow/Enter navigation in supported interactive terminals. Numbered choices
remain available; redirected output and simple terminals use plain text.
Contextual instructions accompany mode selection and input fields in all four
workflows, with format examples and an explanation of Enter. In a file list,
Enter repeats the instructions until the first file is added; it then ends the
list. Inputs are checked as they are entered. Use `:indietro` to revisit an input
or `:annulla` to return to the main menu; entered values are retained while
editing. Review the selected input files, parameters and results destination,
then explicitly choose **Avvia analisi**. In text and path fields, `0` does not
cancel the operation; use `:annulla`.

The final screen offers the results folder, run folder, log and an execution
summary. **6 — Ultima esecuzione** reopens the most recent result screen in the
current session. **7 — Guida all'uso** separates **1 — Come usare NIPAT** from
**2 — Verifica strumenti di analisi**. The check runs only when requested and
is not executed in `--dry-run`; opening the help menu does not verify the runtime.
**5 — Cartella risultati** still applies only to the current session.
Persistent preferences, a cross-session history and automatic workflow chaining
are not part of this revision. The direct CLI and scientific input modes remain
available, and the interface adds no external Python dependencies.

The new terminal interactions require manual Windows verification; record those
results separately from the existing installer and scientific evidence below.

## Input locations and results

Select existing files accessible to the selected runtime. The WSL installer
initially supports fixed local Windows drive paths; UNC shares and network drives
are not supported by this backend. NIPAT mounts
the selected inputs read-only for each run; large BAM/FASTA files do not need
to be copied into the project. Container aliases handle paths containing spaces
and preserve the association with the original files in the run metadata.

For source checkouts, `data` and `runs` are beside the project. The installer
uses `%LOCALAPPDATA%\NIPAT\data` and `%LOCALAPPDATA%\NIPAT\runs`. `data` is a convenience
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

Run these commands from the directory containing `nipat.cmd`: the extracted
project, or `%LOCALAPPDATA%\Programs\NIPAT` for the installed application.
Replace the example paths with your files; all input modes are also available
in `2_AVVIA.cmd` or the **NIPAT** Start-menu shortcut.

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
in the wizard or CLI. See the [usage guide](docs/GUIDA_UTILIZZO.md) for formats.

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
These checks use the configured scientific runtime: the installer starts its
own WSL engine automatically; source installations use the available Docker
engine. They do not add numerical DNPcall-from-BAM coverage.
All four groups passed on Windows with Docker Desktop in `0.2.0a2`. A separate DNPcall run from a real BAM,
using external inputs and a different results root, reproduced all 11 rows
and 17 columns of its previous individual output. These checks support the
validation handoff. On 21 October 2026, the locally corrected WSL candidate
also completed setup and self-tests, restarted its engine after WSL termination,
and reproduced 11 sites and the 11 compared count/genotype columns from the
same real BAM. The rebuilt installer passed CI, including image load/run/reload
in its shipped engine. These are separate checks: a complete installation of
that rebuilt EXE on another PC and independent domain validation remain.
See the [recorded evidence](docs/INSTALLATORE_WINDOWS.md).

For development, use Python 3.12 from a project virtual environment, install
with `python -m pip install -e ".[dev]"`, then run `nipat build-runtime` and
`python -m unittest discover -s tests -v` from the repository root.

- Keep genomic inputs, generated results and local environments outside Git.
- Preserve upstream archives. Document scientific source changes in
  `scientific/README.md` and update `scientific/SHA256SUMS`.
- Use global `--dry-run` before a workflow to check inputs and inspect commands.
  It prepares a new run recorded as `planned`, without executing the analysis.
