# SNPcall 2.0 in NIPAT

This directory contains NIPAT's adapted SNPcall 2.0 scientific core from
[NEWPAT commit ce59f4beeeec710b1b42d425cb87d7aad729f71d](https://github.com/lpistacchia/NEWPAT/tree/ce59f4beeeec710b1b42d425cb87d7aad729f71d/SNPcall).
The unmodified upstream script is retained in
[`tests/reference_r/2.0/SNPcall.R`](../../../../tests/reference_r/2.0/SNPcall.R).
Authorship and the upstream GPL license are preserved. NIPAT supplies input
validation, bounded process scheduling, workflow integration and revised plots.

## Running through NIPAT

```sh
nipat snp-call --pileup examples/pileup.txt --panel examples/SNPlist.txt
nipat snp-call --bam sample.bam --reference genome.fa --panel panel.tsv
nipat workflow snp-batch --bamlist samples.txt --reference genome.fa --panel panel.tsv
```

These commands use the installed scientific runtime. They create a new run
rather than overwrite an example result. The packaged example panel retains
the supported legacy three-column format. The scientific input adapter also
accepts the new four-column panel described below.

The internal R adapter keeps the following interface for the NIPAT engine:

```sh
Rscript SNPcall.R --pileup sample.pileup --snplist panel.tsv --out SNPcall_output.txt
```

It requires the bundled parallel and plot helpers and R dependencies. The
upstream BAM-list interface is exposed through `nipat workflow snp-batch`;
the R adapter itself receives one prepared sample. NIPAT generates each BAM's
three-base-window pileup with `samtools mpileup -d 0 --output-QNAME`, preserving
base qualities and the normalized indel/read-end representation.

## Inputs and scientific model

The new panel has tab-separated columns `chr`, `pos`, `ref`, `alt`. The
legacy `pos`, `ref`, `alt` format, with coordinates such as `chr1:1770788`,
is accepted and normalized. Positions range from 2 to 2147483646; alleles
are distinct single A/C/G/T bases. Lowercase alleles become uppercase in a
working copy; input files remain unchanged.

The pileup requires reference, bases, Phred qualities and QNAME in standard
samtools columns 3, 5, 6 and 7. SNPcall associates observations with each
SNP's central position and its two flanking bases, then groups by SNP and
QNAME. A read spanning neighboring windows contributes to each SNP separately.
The reference markers `.` and `,` are resolved using the pileup reference.
Recognized indel markers anywhere in a retained window exclude that read.

## Results

| Columns | Meaning |
| --- | --- |
| `chr`, `pos`, `REF`, `ALT` | Panel coordinate and alleles. |
| `N_REF`, `N_ALT`, `N_Other`, `total_count` | Retained observation counts; total includes other bases. |
| `ratio` | REF fraction: `N_REF / (N_REF + N_ALT)`. |
| `GL0`, `GL1`, `GL2` | Natural-log genotype likelihoods for `0/0`, `0/1`, `1/1`, using central-base Phred qualities of REF/ALT observations. |
| `GT` | Maximum-likelihood genotype; missing with no informative observations or an other-base fraction of at least 0.1. |
| `reads_discarded_for_indels`, `ratio_reads_discarded_for_indels` | Central-base indel count and fraction before filtering; these do not count all reads removed due to flanking indels. |
| `combined_bases`, `combined_counts` | Matching hyphen-separated observed bases and counts. |

The per-sample table remains `SNPcall_output.txt`. Genotype, REF, ALT and
other-base plots distinguish zero from missing values. Genotype summaries
and resource measurements accompany the table; multi-sample workflows add
merged genotypes and shared-call summaries. Resident memory at start/end
is not peak memory, and R timing does not include prior BAM acquisition.

SNPcall 2.0 deliberately differs from the old NIPAT SNP algorithm. The
immutable upstream 2.0 source is the scientific regression reference;
performance adaptations must retain its numerical output. See
[`scientific/README.md`](../../../README.md) for provenance and verification.

## Contact and citation

Upstream contact: Letizia Pistacchia, letizia.pistacchia@uniroma1.it.

Letizia Pistacchia, Francesco Ravasini, Elisa Bella, Eugenia D’Atanasio,
Fulvio Cruciani, Beniamino Trombetta, “DNPcall: A New Pipeline for Accurate
Double Nucleotide Polymorphism Calling”, *Bioinformatics Advances*, 2025,
vbaf209. https://doi.org/10.1093/bioadv/vbaf209
