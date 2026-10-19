# Consolidated decisions

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
