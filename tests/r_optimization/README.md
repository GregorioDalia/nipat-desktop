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
SNP reads shared across loci and special read names; CPI long threshold ranges,
empty informative sets, missing population loci, metadata NA, ALL/named panels
and zero error; Contamination supplied/derived ratios, boundaries, one/zero
informative sites, batches and panel-only directories.

`r-equivalence.json` records the runtime image, source digests, input digests,
case outcomes, plot comparisons and elapsed times. These times include container
startup and capture instrumentation: they do not establish a performance gain.
The existing independent numeric-oracle integration suite remains required.
