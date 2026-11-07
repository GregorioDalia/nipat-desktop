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
Qualification containers are limited to four CPUs and 8 GiB; the production
scheduler must also respect the actual available CPU and memory. Insufficient
resources to exercise real parallelism fail qualification rather than silently
turning a serial run into a parallel pass.

The comparisons require:

- identical complete TSV/CSV/TXT output bytes, including schema, order and NA;
- `identical()` unrounded R values, types and attributes;
- identical PDF page pixels at 36 DPI, excluding volatile PDF metadata;
- unchanged inputs and successful focused R checks under `*/check_*.R`.

`capture.R` evaluates the complete scientific source with its native CLI
arguments. It retains unrounded DNP tables, SNP tables, Contamination summaries
and every distinct CPI calculation's inputs and threshold results. Repeated CPI
calls in the reference are collapsed only after confirming identical results.
Forked CPI calculations write separate process-local audit records. Their
invocation list is canonicalized by complete inputs for the value comparison;
the result data and scientific file order remain subject to exact comparison.
The production scripts need no diagnostic flags or test-specific branches.

Every case compares the frozen reference with the explicitly serial candidate.
Representative DNP, SNP and Contamination cases and three CPI scheduling paths
(pairs, cutoffs, threshold intervals) also run automatic scheduling, maximum
two processes, maximum four processes and a repeated maximum-four run. Each
candidate independently equals the same oracle. The four main workflow cases
must show at least two actual child PIDs with overlapping task intervals.
The two supplemental CPI cases require distinct actual child PIDs and report
observed overlap without requiring it: their tiny threshold tasks can finish
before the next worker starts. Requested pool sizes alone do not qualify.
CPU, memory and manual process
limits are checked against each recorded plan. The requested maximum need not
be reached when the effective resource budget is smaller.

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
