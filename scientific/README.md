# Scientific sources

The files below come from the supplied upstream projects. DNPcall includes the
compatibility fixes documented below. CPI uses the unmodified upstream update
recorded below; SNPcall and contamination retain the supplied baseline versions.
`SHA256SUMS` records the exact versions currently used by the application.

- `vendor/DNPcall/DNPcall.R`
- `vendor/NEWPAT/SNPcall/SNPcall.R`
- `vendor/NEWPAT/contamination/detect_contamination.R`
- `vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R`

Mechanical compatibility code belongs under `src/nipat/adapters`; orchestration
belongs under `src/nipat/execution`.

## DNPcall compatibility fixes

The local DNPcall fixes preserve data-frame dimensions when selecting a single
genotype column (`drop = FALSE`) in the unassigned-genotype summary and the UpSet
input builder. The UpSet plot is generated only when at least two sample columns
are present; a single-sample run intentionally omits
`DNPs_covered_UpSet_plot.pdf` and prints a message instead.

These changes occur after the genotype table is saved and leave the genotype
calling code and scientific thresholds unchanged.

- Supplied DNPcall SHA-256: `d3bd76d63c5b07f80f5befbfb11012337b7cacf3b3ed9ea3b10d40be0813beb8`.
- Patched DNPcall SHA-256: `d0600427d058a141da8683d98904c51be95ec09ebd5804ea879164d1f5ce7e36`.

The Python workflow passes `--out=output` and runs DNPcall from the run directory.
This avoids embedding an absolute path in the summary filename constructed by
the R script. Results remain under the run's `output` directory.

Keep the supplied upstream archives unchanged. Any further scientific-source
changes require explicit review, a provenance note here, and a matching manifest
update.

## CPI upstream update (2026-10-19)

`vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R` is a byte-for-byte copy
from [NEWPAT commit 17d2b8bbd09b1a0ff0651198c21e544aef197824](https://github.com/lpistacchia/NEWPAT/tree/17d2b8bbd09b1a0ff0651198c21e544aef197824).
The script's last change is commit `e82301f995ba46ee60f676133ca24ce5f9cb5ee2`
(2026-10-18). Its Git blob is `a362c976f9e9280e64f5bc2ec4a7b83b1e9647e6`.

- Previous SHA-256: `9c6de9ce07b75a7506b8713459192ecd449522bdc9b1321baf6bbd09704e116d`.
- Updated SHA-256: `10ca01a476f5259b65a063aea95ff76e57c11567a304667065ea9c7b9206545a`.

The summary now excludes sites with fewer than two fetal reads, consistently
with the existing CPI iteration filter. Site counts and median fetal fraction
may therefore change. Plots now annotate cfDNA percentage and log10(CPI).
The CPI formula, `err_const`, command-line interface and R dependencies are
unchanged. No local modifications were applied to this upstream script.

Run `python scripts/verify_cpi_update.py` with Docker available to check the
numeric summary against synthetic, analytically derived expectations. See
`tests/fixtures/cpi/README.md` for inputs, calculations and test boundaries.
