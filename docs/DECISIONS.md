# Consolidated decisions

- The R scripts supplied on 2026-07-21 are the scientific baseline. DNPcall includes the compatibility fixes and CPI includes the upstream update recorded in `scientific/README.md`; SNPcall and contamination retain the supplied baseline versions.
- The first prototype covers DNPcall, SNPcall, contamination and CPI.
- `DNP_list.txt` is the provisional trusted DNP panel.
- The Python layer may derive `n°DNP`, `chr`, `pos1`, `pos2` mechanically from that list.
- SNPcall pileup generation is performed automatically from BAM, FASTA and the SNP list.
- Population-frequency tables remain user-selectable.
- The current `err_const` default is frozen but exposed by the CPI command.
- Scientific thresholds follow the recorded upstream versions. The CPI update applies the existing minimum of two fetal reads to its summary as well as its curves. Defaults are documented in `config/defaults.toml`.
- The application is local and is being designed for Windows, Linux and macOS.
- Genomic data and run outputs remain outside the Git repository.

## Open scientific interface issue

The current DNPcall output does not include `ratio_REF_ALT`, while the vendored
contamination script requires it. NEWPAT commit
`17d2b8bbd09b1a0ff0651198c21e544aef197824` now computes the missing field as
`N_REF / (N_REF + N_ALT)`, excluding zero-denominator sites. Updating contamination
and its Python validation is a separate integration task. Until that update is
applied, the current wrapper continues to reject input without `ratio_REF_ALT`.
