# Bundled scientific entry point

The image installs this directory at `/opt/nipat/engine`, beside the bundled
`scientific` directory. Shared scientific preparation modules are installed at
`/opt/nipat/lib/nipat_scientific`. The entry point has no dependency on the
Windows application, the working directory or the host checkout. Python uses
only its standard library.

```sh
python3 /opt/nipat/engine/main.py describe --json
python3 /opt/nipat/engine/main.py verify
python3 /opt/nipat/engine/main.py run snp-call -- \
  --pileup /inputs/pileup.txt --snplist /inputs/SNPlist.txt --out /outputs/output.txt
python3 /opt/nipat/engine/main.py execute contamination --request /run/work/request.json
python3 /opt/nipat/engine/main.py execute snp-call --request /run/work/request.json
python3 /opt/nipat/engine/main.py execute dnp-call --request /run/work/request.json
```

The workflow names are `dnp-call`, `snp-call`, `contamination` and `cpi`.
Arguments after the workflow name are passed directly to the corresponding
bundled R script, after removing an optional initial `--`. All four scripts
must match the bundled `scientific/SHA256SUMS` before any workflow can run.
`describe --json` reports interface `native-r-v1`, metadata schema version 1,
the manifest hash, and each workflow's bundled path and source hash. It also
reports `workflow_interfaces.contamination = contamination-v1`,
`workflow_interfaces.snp-call = snp-call-v1`,
`workflow_interfaces.dnp-call = dnp-call-v1` and preparation metadata interface
`workflow-preparation-v1`. `preparation.file_sha256` identifies the entry point
and seven shared Python modules.
Missing modules or paths escaping the bundle are rejected. These hashes record
the Python source bytes in the selected image; the R hashes are additionally
checked against the scientific manifest. They do not identify a published
NIPAT release on their own.

Execution replaces the entry-point process with `Rscript`, preserving R's exit
status and direct signal delivery. SNPcall BAM preparation first runs samtools;
its nonzero exit prevents R execution, and termination signals are forwarded
to that subprocess. Verification or launch failures return 2.
The container runtime and R must already be available; this command performs
no downloads or package installation.

## Contamination request

The versioned preparation interface accepts this JSON object; paths identify
files and destinations inside the container, not host Windows paths:

```json
{
  "schema_version": 1,
  "workflow": "contamination",
  "panel": "/inputs/panel.txt",
  "samples": [
    {"path": "/inputs/sample_001.tsv", "name": "Original_sample.txt"}
  ],
  "work_dir": "/run/work",
  "out_dir": "/run/output"
}
```

The client selects individual files or expands a directory recursively and
maps the selected files read-only. The engine validates each table and the
panel, rejects case-insensitive sample-name collisions, copies tables
byte-for-byte into `work/inputs` with their original stems and `.txt` extension,
and writes the native panel to `work/DNPpanel.txt`. It then invokes the bundled
unchanged R script. Names can contain spaces and Unicode but cannot contain
directory separators or control characters. All validation precedes staging.

Work and output directories must be distinct and must not contain the input
files. Existing run directories are supported, but output must be empty and
the generated panel/staging directory must not already exist. Partial staging
after an I/O failure remains available for diagnosis and cannot be overwritten
by rerunning the same request. Intermediate artifacts remain in the run.

## SNPcall request

```json
{
  "schema_version": 1,
  "workflow": "snp-call",
  "mode": "bam",
  "panel": "/inputs/SNPlist.txt",
  "bam": "/inputs/sample.bam",
  "pileup": null,
  "reference": "/inputs/genome.fa",
  "work_dir": "/run/work",
  "out_dir": "/run/output"
}
```

In `pileup` mode, `bam` and `reference` must be null and `pileup` identifies
the supplied file, including the seventh QNAME column. Additional columns
remain accepted. In `bam` mode, `pileup` must be null and the reference must
have its adjacent `.fai`; BGZF references also require `.gzi`. BAM indexes
remain optional, because samtools uses `-l` rather than indexed region access.
The original chromosome names and three-base window calculation are preserved.

The engine writes `work/snp_regions.bed`, invokes samtools with the existing
mpileup options and retains `work/pileup.txt` before running R. Existing pileup
mode skips both preparation files and samtools. Both modes write
`output/SNPcall_output.txt`. Inputs are read-only and must be outside the distinct
work/output directories; existing generated artifacts and nonempty output
directories are rejected before preparation starts.

## DNPcall request

```json
{
  "schema_version": 1,
  "workflow": "dnp-call",
  "panel": "/inputs/DNP_list.txt",
  "samples": [
    {"path": "/inputs/bams/sample_0001.bam", "sample_id": "sample_0001"}
  ],
  "reference": "/inputs/genome.fa",
  "parallel": false,
  "work_dir": "/run/work",
  "out_dir": "/run/output"
}
```

The client accepts individual BAMs, multiple BAMs or a BAM list. It maps BAMs
under sequential `sample_0001.bam` aliases and retains the association with the
original files in `run.json`. List entries are resolved relative to the list's
directory. Large BAM and reference files are mounted read-only, not copied.
The reference requires `.fai`, and BGZF references additionally require `.gzi`;
BAM indexes remain optional.

The engine validates the ordered aliases and panel, then writes
`work/DNP_list.txt` and `work/bamlist.txt`. Work and output must be siblings named
`work` and `output`. Execution changes directory to their parent and supplies
relative native arguments `--bamlist=work/bamlist.txt`,
`--DNPs=work/DNP_list.txt` and `--out=output`. This preserves the unchanged R
script's output naming. Its internal shell calls require safe ASCII BAM/reference
container paths; the client supplies these even for original filenames containing
spaces or Unicode. `parallel` is a boolean and enables R's existing `--parallel`.

Existing generated staging files, nonempty output, and run-root `mpileup.txt`
or `bedfile_for_mpileup.bed` are rejected before preparation. The native script
creates and removes those last two files itself on success. The normalized panel,
BAM list and request remain available. DNPcall invokes samtools internally,
suppresses its stderr and does not check its exit status. This inherited behavior
is unchanged: the engine preserves the R exit status but cannot guarantee that
every internal samtools failure is reported. A successful process alone does not
validate its scientific output.

The shared preparation package is the single source of the existing panel and
table validators; client preflight imports use compatibility exports. CPI still
uses client-side preparation; its cutoff preparation is the remaining workflow
migration step. R algorithms are unchanged.

Input datasets and output directories are supplied separately. Production
execution must not mount application/source directories over `/opt/nipat`.
The Dockerfile does not force this command as `ENTRYPOINT`, so existing runtime
checks and the current desktop client can continue to invoke their commands
during the incremental transition.
