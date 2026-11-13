# Independent 0.8.50 downstream fixtures

Both marker types encode the same counts, with SNP `chr,pos,A,C` or DNP
`chr,pos1,pos2,AA,CC`. They are count tables, not real patient data or BAM files.
The corresponding population tables use independent, explicitly assigned
frequencies; no expected answer is derived by running the candidate.

## Contamination

Four loci have `(REF,ALT,Other)` counts `(95,5,11)`, `(100,0,0)`, `(80,20,0)`,
`(0,0,5)`. The first is retained by the new Other/total filter (`11/111 <= .1`).
The first two are homozygous under the configured ratio rules. Consequently:

- Include zeros: 2 informative sites, mean `.025`, SD `sqrt(.00125)`.
- Exclude zeros: 1 informative site, mean `.05`, SD `NA`.

The old filter `11/100 > .1` would incorrectly retain only the zero site when
used as a reference for the newly requested model.

## Prenatal CPI

Maternal minor-allele counts are 2, 3, 4 and 1 out of 100; paternal genotypes
and ALT frequencies give PI contributions 5, 2, 2 and 5. With minimum support
2, CPI at thresholds 2,3,4 is therefore 20,4,2; the median fetal fraction is
6%. With minimum 1, the new first CPI is 100 and the fraction is 5%. Minimum
5 gives no informative sites. A separate no-sites pair tests explicit NA.
The metadata variant adds an unused all-NA column to population frequencies:
this must not discard scientifically usable sites.
The mismatch variant replaces the father at maternal support 3 with a REF
homozygote: that site's PI becomes `epsilon/.25`, yielding curve products
`40*epsilon,8*epsilon,2`. This separately verifies SNP/DNP mismatch constants.

## Postnatal CPI

Nine loci test: heterozygous paternal transmission, paternal mismatch, compatible
homozygous child, opposite mother/child homozygotes, heterozygous mother,
insufficient child support, no coverage (`total_count=NA`), excess Other,
and an unassigned paternal genotype. Only the first three pass all filters.

Their PI contributions are `0.5/0.4`, `epsilon/0.4`, and `1/0.6`, respectively.
The heterozygous-child selection contains the first two; the all-compatible
selection adds the third. Their obligatory paternal allele supports are 5,6,10,
which independently define the entire small threshold curve. `epsilon` is
`.001` for SNP and `.0000892303778101497` for DNP.

The optional full qualification copies these explicit fixtures to distinct
sample identities to test 2,3,5 trios, prenatal pairs or contamination samples. Copies are only
a process/identity stress fixture; they do not represent biological replication.

Run:

```sh
python scripts/verify_five_modules.py --full --output build/qualification-0850
# CI: use the installed R/Python payload, with its hashes checked first.
python scripts/verify_five_modules.py --image "$NIPAT_RUNTIME_IMAGE" --full --output build/qualification-image
```

The verification also executes frozen upstream scripts and compares every
reference summary field. Added candidate diagnostics and PDF bytes are not
treated as scientific differences. DNP/SNP calling, native installers, and the
combined workflow executor have separate mandatory checks.
