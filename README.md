# NIPAT Desktop

Local Python orchestration for four existing scientific R workflows:

- DNPcall;
- SNPcall, including automatic pileup generation;
- contamination estimate;
- cfDNA fetal fraction and CPI.

The current milestone is a reproducible command-line prototype. The desktop GUI
will be built on the same application layer after the four workflows are reproduced.

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

The command intentionally stops when an input lacks `ratio_REF_ALT`. That is the
known interface mismatch awaiting scientific confirmation.

```powershell
nipat contamination `
  --input "D:\Nipat_project\data\test-cases\sample1.txt" `
  --input "D:\Nipat_project\data\test-cases\sample2.txt" `
  --panel "D:\Nipat_project\data\panels\DNP_list.txt"
```

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

## Development safeguards

- Never place BAM, BAI, FASTA, FAI or generated results in this repository.
- Never modify files under `scientific/vendor` in place.
- Use `--dry-run` before a new workflow to validate inputs and display commands.
- Each named run is immutable: an existing run directory is never overwritten.
