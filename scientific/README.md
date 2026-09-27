# Scientific sources

The files below come from the supplied upstream projects. DNPcall includes the
compatibility fixes documented below; the three NEWPAT scripts remain unchanged.
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
