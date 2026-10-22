# Bundled scientific entry point

The image installs this directory at `/opt/nipat/engine`, beside the bundled
`scientific` directory. It has no dependency on the Windows application, the
working directory or the host checkout. Python uses only its standard library.

```sh
python3 /opt/nipat/engine/main.py describe --json
python3 /opt/nipat/engine/main.py verify
python3 /opt/nipat/engine/main.py run snp-call -- \
  --pileup /inputs/pileup.txt --snplist /inputs/SNPlist.txt --out /outputs/output.txt
```

The workflow names are `dnp-call`, `snp-call`, `contamination` and `cpi`.
Arguments after the workflow name are passed directly to the corresponding
bundled R script, after removing an optional initial `--`. All four scripts
must match the bundled `scientific/SHA256SUMS` before any workflow can run.
`describe --json` reports interface `native-r-v1`, metadata schema version 1,
the manifest hash, and each workflow's bundled path and source hash. These
identify the interface and source bytes, not a published NIPAT release.

Execution replaces the entry-point process with `Rscript`, preserving R's exit
status and direct signal delivery. Verification or launch failures return 2.
The container runtime and R must already be available; this command performs
no downloads or package installation.

This is the first packaging increment towards 0.5. It accepts **native script
inputs**: desktop panel normalization, SNP pileup generation, sample aliases,
Contamination staging and CPI cutoff preparation are not yet moved here.
Consequently it does not yet replace the desktop `Workflows` service or claim
that every desktop input mode is self-contained. R algorithms are unchanged.

Input datasets and output directories are supplied separately. Production
execution must not mount application/source directories over `/opt/nipat`.
The Dockerfile does not force this command as `ENTRYPOINT`, so existing runtime
checks and the current desktop client can continue to invoke their commands
during the incremental transition.
