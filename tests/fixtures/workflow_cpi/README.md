# Synthetic BAM-to-CPI workflow regression

The scientific integration check generates artificial reads in
`scripts/verify_workflow_execution.py` and runs the public automatic workflow
through the packaged image. No participant or patient data are used.

The sequence contexts, reference, chromosome and three DNP positions come from
`tests/fixtures/dnp_engine`. The generator selects one REF and one ALT 62M
alignment template at each position from its committed `reads_A.sam` and
`reads_B.sam`. It preserves the aligned sequence and mapping quality 60, assigns
unique read names, alternates strand flags 0/16, and sets every base quality to
Phred 40. Alignments remain sorted by position; no indels or Other alleles are
introduced. Each generated BAM contains 300 reads and is deliberately unindexed.
The image's samtools converts SAM to BAM and indexes the synthetic FASTA.

| DNP positions | Maternal REF / ALT | Paternal REF / ALT | Other | REF / ALT population frequency |
| --- | ---: | ---: | ---: | --- |
| 50–51, 140–141, 230–231 | 96 / 4 at each site | 50 / 50 at each site | 0 | 0.75 / 0.25 |

The expectations derive from these input counts, independently of the code
under test:

- All three maternal sites satisfy the homozygous-majority criterion and have
  four fetal reads. Each fetal-fraction estimate is `2 × 4 / 100 = 0.08` (8%).
- Each paternal site is heterozygous. Its paternity index is `0.5 / 0.25 = 2`.
  Across all three sites CPI is `2³ = 8`, so the log10 summaries round to
  `0.903` for every fetal-read threshold 2 through 4.
- A named panel selecting only the first site retains the same fetal fraction,
  one maternal/paternal site and log10 CPI rounded to `0.301`.
- Contamination retains all three maternal sites with `4 / 100 = 0.04` per site:
  the mean is 0.04 and the sample standard deviation is 0. The paternal sample
  has no informative contamination sites, giving count 0 and `NA` estimates.

The full preset must execute DNPcall once, then Contamination and CPI. CPI reads
DNPcall's original individual tables directly. Passing the Contamination output
instead would lose the heterozygous paternal sites and fail this oracle.

Additional checks compare every CPI CSV value with a separate execution of the
same packaged R workflow, verify PDF filenames/signatures, preserve explicit
maternal/paternal identities and input bytes, and record one container command
and distinct step states. PDF appearance is not compared.

The separate DNPcall → CPI preset uses the existing DNP fixture unchanged and
checks its expected zero-informative-site/`NA` result. Imported-table plans reuse
`tests/fixtures/cpi` and `tests/fixtures/cpi_engine` for positive numerical
regressions, shared maternal inputs, multiple pairs, ALL/single/named panels and
an error-constant-sensitive case. These are software regression checks, not
acceptance of the scientific method on real samples.
