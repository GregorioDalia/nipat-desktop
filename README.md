# NIPAT Desktop

**CLI 0.2.0a1 for domain validation.** Start with the short Italian
[project overview](SUNTO.md) and the [tester guide](docs/GUIDA_COLLEGA.md).
On Windows x64, `1_SETUP.cmd` prepares local Python, Docker runtime and bundled
self-tests; `2_AVVIA.cmd` opens a text wizard. The [distribution guide](docs/DISTRIBUZIONE.md)
describes distribution through a versioned GitHub release. Testers download
the source archive from GitHub; setup downloads Python and builds the scientific
runtime locally. Docker Desktop with Linux containers is currently required.

Local Python orchestration for four existing scientific R workflows:

- DNPcall;
- SNPcall, including automatic pileup generation;
- contamination estimate;
- cfDNA fetal fraction and CPI.

The current milestone is a reproducible command-line prototype. The desktop GUI
will be built on the same application layer after the four workflows are reproduced.

Each new workflow run records `run.json` and `execution.log` alongside `work`
and `output`. Metadata tracks the complete workflow, commands, input evidence,
code hashes and resolved Docker image ID. `--dry-run` is recorded as planned,
never as a completed analysis. See [execution records](docs/ESECUZIONI.md).

```powershell
nipat wizard
nipat self-test
```

The self-test runs the bundled SNP reference case and synthetic CPI/Contamination
regressions. It does not replace validation from raw BAMs or domain evaluation.

## Expected workspace

```text
D:\Nipat_project\
├── nipat-desktop\     this Git repository
├── upstream\          original archives, kept unchanged
├── data\
│   ├── reference\
│   ├── samples\
│   ├── panels\
│   └── test-cases\
└── runs\              generated results and logs
```

All paths passed to NIPAT must be inside the repository, `data`, or `runs`. These
are the only host directories mounted into the Linux runtime; repository and
genomic inputs are read-only, while only `runs` is writable.

## First setup in PyCharm

Open the terminal in `D:\Nipat_project\nipat-desktop` and run:

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
nipat doctor
nipat build-runtime
nipat doctor --runtime
pytest
```

The first image build can take several minutes because it compiles samtools and
installs the R packages. Later builds reuse Docker's cache.

The tests can also run without installing development dependencies:

```powershell
python -m unittest discover -s tests
```

## DNPcall: first real run

Use full PowerShell paths or quote them as below:

```powershell
nipat dnp-call `
  --bam "D:\Nipat_project\data\samples\IonXpress_008_R_2023_06_01_09_58_51_user_S5-0398-543-niPAT_Cruciani_chip2__pool1_Auto_user_S5-0398-543-niPAT_Cruciani_chip2__pool1_926.bam" `
  --reference "D:\Nipat_project\data\reference\Homo_sapiens.GRCh37.dna.primary_assembly.fa" `
  --panel "D:\Nipat_project\data\panels\DNP_list.txt" `
  --run-name first-dnp-call
```

Results are written to:

```text
D:\Nipat_project\runs\first-dnp-call\output
```

Add `--parallel` only after the initial serial run has been reproduced.

For a single sample, DNPcall intentionally skips the UpSet plot. The local
compatibility fixes and source hashes are documented in `scientific/README.md`.

## SNPcall

The SNP list must be tab-separated with header `pos, ref, alt`, where `pos` is
formatted as `chr:position`.

```powershell
nipat snp-call `
  --bam "D:\Nipat_project\data\samples\sample.bam" `
  --reference "D:\Nipat_project\data\reference\Homo_sapiens.GRCh37.dna.primary_assembly.fa" `
  --panel "D:\Nipat_project\data\panels\SNPlist.txt"
```

## Contamination

Inputs require `chr`, `pos1`, `pos2`, `N_REF`, `N_ALT`, and `N_Other`.
The upstream R script calculates `ratio_REF_ALT` when absent and uses it when
provided. Input copies are staged with a lowercase `.txt` extension, as required
by the R directory reader; originals remain unchanged and colliding names are
rejected. Zero-contamination sites are included when informative.

```powershell
nipat contamination `
  --input "D:\Nipat_project\data\test-cases\sample1.txt" `
  --input "D:\Nipat_project\data\test-cases\sample2.txt" `
  --panel "D:\Nipat_project\data\panels\DNP_list.txt"
```

Results include per-sample TXT files and `contamination_summary.txt`, containing
`informative_DNPs`, `mean_contamination`, and `sd_contamination`. Estimates are
fractions: for example, `0.025` means 2.5%.

With the scientific image already built, run the synthetic numeric check:

```powershell
python scripts/verify_contamination_update.py
```

It checks inputs with and without a ratio, zero-contamination sites, exclusions,
and a sample with no informative sites. See `tests/fixtures/contamination/README.md`.

## CPI

```powershell
nipat cpi `
  --input-dir "D:\Nipat_project\data\test-cases\cpi" `
  --pairs "A1:A1,A2:A2" `
  --mother-prefix Mother `
  --father-prefix Father `
  --popfreq "D:\Nipat_project\data\panels\pop_allFreq.txt" `
  --panel "D:\Nipat_project\data\panels\DNP_list.txt"
```

The default `err_const` is `0.0000892303778101497`; override it only through an
explicitly reviewed run with `--err-const`.

### CPI numeric regression check

With the scientific Docker image already built, run from the repository root:

```powershell
python scripts/verify_cpi_update.py
```

This runs the actual CPI workflow on two synthetic pairs and checks the CSV
against analytical expectations, including the updated two-fetal-read minimum
and a pair with no informative sites. It also checks that the three PDF files
were produced. Each invocation creates a new directory under `runs` and prints
its path. It does not require genomic input files or overwrite earlier runs.
The fixture and calculations are documented in `tests/fixtures/cpi/README.md`.
This integration check is separate from the Python-only unit tests.

## Development safeguards

- Never place BAM, BAI, FASTA, FAI or generated results in this repository.
- Keep upstream archives unchanged; review and document any changes to `scientific/vendor` in `scientific/README.md` and update `scientific/SHA256SUMS`.
- Use `--dry-run` before a new workflow to validate inputs and display commands.
- Each named run is immutable: an existing run directory is never overwritten.
