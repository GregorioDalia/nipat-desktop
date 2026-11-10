# Synthetic SNPcall engine fixture

These data are artificial and contain no participant or patient information.
They test packaging and execution; they are not a domain-validation dataset.

`reference.fa` contains one 180-base synthetic contig. `reads.sam` contains 13
coordinate-sorted, unpaired, 61-base reads, each with a unique QNAME, mapping
quality 60, base quality 40, and a `61M` alignment. Both strand flags occur.
The sequence stored in each SAM record is already in alignment orientation.
Each read covers the central SNP and its two neighboring bases. Reads from
different sites have distinct names. Separate 2.0 differential cases also cover
shared names across neighboring and distant SNPs. Apart from the declared central allele, every base matches
the reference. The 30-base matching flanks avoid short-read alignment ambiguity.

The expected output is defined independently by counting the declared alleles:

| SNP | REF reads | ALT reads | Other reads | Total | REF / (REF + ALT) |
| --- | ---: | ---: | ---: | ---: | ---: |
| chrSynthetic:50 A>G | 4 | 2 | 1 | 7 | 4/6 |
| chrSynthetic:120 C>T | 2 | 3 | 1 | 6 | 2/5 |

`scripts/verify_engine_package.py` uses samtools in the tested image to convert
this SAM to BAM and generate the FASTA index. It deliberately does not generate
a BAM index: the supported SNPcall command selects regions with `mpileup -l`.
It uses the SNPcall 2.0 `-d 0` depth setting, retaining samtools default quality
filters and BAQ behavior. A mismatch with the counts above fails the regression;
the fixture is not used to alter the scientific settings.

The real-image check then runs the complete BAM workflow, validates the BED
windows and the retained seven-column pileup, compares every output field with
`expected.tsv` (numeric tolerance 1e-12), and repeats the analysis from that pileup
through the public Python workflow. The existing nine-site upstream pileup
example remains an additional independent regression.

The 17-column 2.0 oracle also uses each declared central Phred40 score:
`eps=10^(-40/10)`, with the sum of log probabilities under 0/0, 0/1 and
1/1. Both fixture sites have Other fractions above 10%, so GT is `NA` while
likelihoods remain available. No reads contain indels: both indel fields are
zero. `combined_bases`/`combined_counts` retain every observed allele in
alphabetical order, including T at50 and G at120. These expectations are
computed independently in `verify_snp_workflow.independent_snp_row`, then
compared with the pinned upstream core and the candidate.
