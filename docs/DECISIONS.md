# Consolidated decisions

- The current R scripts supplied on 2026-07-21 are the canonical scientific implementation.
- The first prototype covers DNPcall, SNPcall, contamination and CPI.
- `DNP_list.txt` is the provisional trusted DNP panel.
- The Python layer may derive `n°DNP`, `chr`, `pos1`, `pos2` mechanically from that list.
- SNPcall pileup generation is performed automatically from BAM, FASTA and the SNP list.
- Population-frequency tables remain user-selectable.
- The current `err_const` default is frozen but exposed by the CPI command.
- Scientific thresholds stay unchanged. They are documented in `config/defaults.toml`.
- The application is local and is being designed for Windows, Linux and macOS.
- Genomic data and run outputs remain outside the Git repository.

## Open scientific interface issue

The current DNPcall output does not include `ratio_REF_ALT`, while the current
contamination script requires it. Until the authors confirm the intended formula,
the orchestration layer rejects incompatible input with an explicit message. It
does not silently create or reinterpret a scientific field.
