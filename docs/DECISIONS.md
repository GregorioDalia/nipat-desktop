# Consolidated decisions

## CLI validation handoff (2026-10-20)

- Consolidate run evidence before the GUI: `run.json` and a live/persistent
  `execution.log` describe the full workflow, including multi-command SNPcall.
- Resolve and record the actual Docker image ID and scientific package versions;
  use that image ID for the run. A Docker tag alone is not a version guarantee.
- The first assisted distribution targets Windows x64 through a versioned
  GitHub release. Testers download the source archive directly from GitHub;
  setup prepares embedded Python 3.12.10 and builds the Docker scientific runtime.
  Docker Desktop Linux containers are currently a manual prerequisite.
  Prerequisite installation automation is planned, not implemented in this release.
- The text wizard calls the same Workflows services as the existing CLI.
  DNPcall remains serial by default; advanced options remain in direct commands.
- CLI 0.2.0a1 is a validation candidate. Bundled numerical checks cover the SNP
  reference example and synthetic CPI/Contamination cases; domain validation
  and raw-BAM coverage are separate. No scientific algorithm changes here.
- Windows setup was exercised on the maintainer's PC on 2026-10-20: 48 Python
  tests passed, one symlink test was skipped, and all three real Docker numerical
  self-tests passed. Docker was already installed and the build reused cached
  layers; a clean-machine installation and the colleague's domain tests remain.

## Existing scientific and architectural decisions

- The R scripts supplied on 2026-07-21 are the scientific baseline. DNPcall includes the compatibility fixes, while CPI and contamination include the upstream updates recorded in `scientific/README.md`; SNPcall retains the supplied baseline version.
- The first prototype covers DNPcall, SNPcall, contamination and CPI.
- `DNP_list.txt` is the provisional trusted DNP panel.
- The Python layer may derive `n°DNP`, `chr`, `pos1`, `pos2` mechanically from that list.
- SNPcall pileup generation is performed automatically from BAM, FASTA and the SNP list.
- Population-frequency tables remain user-selectable.
- The current `err_const` default is frozen but exposed by the CPI command.
- Scientific thresholds follow the recorded upstream versions. The CPI update applies the existing minimum of two fetal reads to its summary as well as its curves. Defaults are documented in `config/defaults.toml`.
- The application is local and is being designed for Windows, Linux and macOS.
- Genomic data and run outputs remain outside the Git repository.

## Contamination interface

The DNPcall output does not include `ratio_REF_ALT`. The vendored contamination
script from NEWPAT commit `17d2b8bbd09b1a0ff0651198c21e544aef197824` computes the
missing field as `N_REF / (N_REF + N_ALT)`, excluding zero-denominator sites. An
existing ratio column is passed through to the upstream script. Python validates
the required count/coordinate columns and does not invent a scientific field.

Contamination now includes informative sites with zero unexpected reads. The
resulting counts, mean and standard deviation can differ from the baseline.
The summary is a tab-separated TXT with an informative-site count. Samples with
no informative sites have count zero and `NA` estimates.
