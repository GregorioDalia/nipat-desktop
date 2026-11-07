# Scientific R equivalence

`scripts/verify_r_equivalence.py` runs the frozen NIPAT 0.8.5 scripts and the
candidate scripts in the same immutable scientific image. The candidate files
inside that image must match the checkout. The reference is pinned to commit
`eafadf7002a9c7d7c1b9af9ccafc47d698a059e5`; its six files and digests are
checked independently of its manifest.

```sh
python scripts/verify_r_equivalence.py \
  --image nipat-scientific-runtime:ci-test \
  --output-dir build/r-equivalence
```

The output directory must be new. Docker and Poppler's `pdftoppm` are required.
Containers have no network and mount sources and inputs read-only. Inputs are
generated from public synthetic fixtures; no personal sequencing data are used.

The comparisons require:

- identical complete TSV/CSV/TXT output bytes, including schema, order and NA;
- `identical()` unrounded R values, types and attributes;
- identical PDF page pixels at 36 DPI, excluding volatile PDF metadata;
- unchanged inputs and successful focused R checks under `*/check_*.R`.

`capture.R` evaluates the complete scientific source with its native CLI
arguments. It retains unrounded DNP tables, SNP tables, Contamination summaries
and every distinct CPI calculation's inputs and threshold results. Repeated CPI
calls in the reference are collapsed only after confirming identical results.
The production scripts need no diagnostic flags or test-specific branches.

Cases include neighboring DNPs, insertion/deletion reads, forward/reverse reads,
mixed-case read names, uncovered sites, one/two samples and parallel execution;
varied DNP qualities; SNP reads shared across loci, special read names and
additional pileup columns; CPI shared parents, long threshold ranges,
empty informative sets, missing population loci, metadata NA, ALL/named panels
and zero error; Contamination supplied/derived ratios, boundaries, one/zero
informative sites, batches and panel-only directories.

`r-equivalence.json` records the runtime image, source digests, input digests,
case outcomes, plot comparisons and elapsed times. These times include container
startup and capture instrumentation: they do not establish a performance gain.
The existing independent numeric-oracle integration suite remains required.

Focused comparisons cover all printable SAM quality characters, missing and
nonstandard input fallbacks, read groups shorter than a complete SNP window,
indels in flanking observations, locale-dependent names, independent maternal,
paternal and mismatch threshold boundaries, and overflow/underflow transitions.

`performance/check_costs.R` additionally measures five bounded synthetic cases:
DNP tokenization, quality decoding, central-observation extraction, and CPI
with dense or sparse thresholds. It requires strict output equality first,
then records three timing observations per variant with alternating order.
`performance-observations.tsv` contains elapsed times excluding container and
package startup. Allocation totals come from a separate `Rprofmem` pass when
supported by R; they are cumulative allocated bytes, **not peak RAM**. These
observations describe isolated operations, not whole-workflow speedups, and
there is no timing threshold that can fail CI due to runner load.
