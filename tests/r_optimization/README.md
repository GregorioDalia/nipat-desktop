# Scientific R qualification

Two complementary gates qualify version 0.8.50. Both use synthetic inputs and
must pass against the actual scientific image. No personal sequencing data are
included in either gate.

```sh
python scripts/verify_r_equivalence.py \
  --image nipat-scientific-runtime:ci-test \
  --output-dir build/r-equivalence
python scripts/verify_five_modules.py \
  --image nipat-scientific-runtime:ci-test \
  --full --output build/five-modules
```

Use separate new/empty output directories. Docker is required; the caller gate
also requires Poppler's `pdftoppm` and `pdfinfo`. Containers have no network,
read-only source/oracle mounts, four CPUs and 8 GiB. Source and helper hashes
must match the checkout before candidate science can run. The downstream gate
runs the installed code in `/opt/nipat`, never host candidate overrides. Its
local-R mode snapshots candidate code to prevent concurrent development edits
from changing an Rscript that is already running.

## Preserved DNP/SNP caller models

`verify_r_equivalence.py` compares DNP defaults against immutable NIPAT 0.8.5
commit `eafadf7002a9c7d7c1b9af9ccafc47d698a059e5`, and SNP against the complete
scientific core of SNPcall 2.0 from NEWPAT commit
`ce59f4beeeec710b1b42d425cb87d7aad729f71d`. The complete historical six-file
archive remains hash-pinned; its obsolete CPI/Contamination formulas are not
used as oracles for the updated models.

The caller comparisons require:

- identical complete scientific table bytes, including schema, order and NA;
- `identical()` unrounded R values, types and attributes;
- renderable bounded PDFs and exact serial/parallel page pixels at 36 DPI,
  excluding volatile PDF metadata;
- histogram zero/edge/missing semantics and all-locus pagination in
  `presentation/check_plots.R`;
- unchanged input files and successful focused DNP/SNP, presentation and
  resource-budget checks.

`capture.R` evaluates native DNP source and SNP's `call_sample` interface. The
SNP oracle excludes only the final native BAM-list invocation; empty samples
use the literal upstream worker fallback. The historical DNP plot appends
`NA_count` and `DNP_name` after exporting its genotype table. Capture excludes
exactly those two presentation-only fields on both sides; all other scientific
fields remain exact.

The 17 cases cover neighboring DNPs, insertion/deletion reads, strands, varied
qualities and names, uncovered sites, one/multiple BAMs, block boundaries,
numeric chromosomes and repeated names. SNP cases cover reads shared across
loci, extra pileup columns, varied qualities, overlapping windows and entirely
uncovered samples. Every case runs serial and a maximum-two-process candidate.
Selected DNP/SNP cases additionally run automatic and maximum-four scheduling,
including a repeated maximum-four run. They require real child processes with
overlapping task intervals, not only a requested pool size. CPU, memory and
manual limits are checked against observed work. Indexed-pileup and cancellation
checks remain part of this gate.

`r-equivalence.json` records source/input digests, image identity, exact
comparisons, worker evidence, plots and elapsed observations. These times
include container startup and capture instrumentation, so are not performance
claims. `performance/check_costs.R` retains three isolated DNP benchmarks:
tokenization, quality decoding and central-observation extraction. Strict
output equality precedes three alternating-order observations per variant.
`Rprofmem` allocation totals are not peak RAM, and timing has no pass/fail
threshold.

## Updated downstream models

`verify_five_modules.py` complements the caller gate with CPI, CPIN and
Contamination from both SNP and DNP count tables. Frozen original scripts from
NEWPAT commit `9c2a8be60afcb944153710da6a61cd0559e2b4cf` are pinned separately
under `tests/reference_r/NEWPAT_20261113`. Independent hand-derived fixtures
verify counts, missing values, mismatch constants, full CPI curves, compact
CPIN threshold intervals, the new contamination denominator, optional zero
inclusion, minimum support and unused NA metadata.

The full matrix also checks 2/3/5 prenatal pairs, postnatal trios and
contamination samples under serial, auto and maximum-two-process execution.
Reference scientific fields and deterministic row order must match; added
candidate diagnostics and PDF metadata are not scientific differences.
`five-module-qualification.json` records numerical assertions, reference comparisons,
installed candidate/helper hashes, immutable image identity and actual worker
budgets/completion/concurrency. Every execution binds input, output and log
hashes, checks that inputs remain unchanged and checks native R effective
settings against the requested configuration, including readable constants.
Hashes describe raw execution bytes before archive path redaction. Tiny batch
cases require distinct real child processes without a scheduling-dependent
overlap assertion; the controlled parallel scheduler barrier separately proves
simultaneous execution. Details and derivations are in
`tests/fixtures/five_modules/README.md`.

Engine workflow/BAM integration, presentation contracts and native Windows
installer checks are separate mandatory qualifications. Count-table oracles
alone do not qualify those boundaries.
