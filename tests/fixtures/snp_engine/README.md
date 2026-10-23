# Synthetic SNPcall engine fixture

These data are artificial and contain no participant or patient information.
They test packaging and execution; they are not a domain-validation dataset.

`reference.fa` contains one 180-base synthetic contig. `reads.sam` contains 13
coordinate-sorted, unpaired, 61-base reads, each with a unique QNAME, mapping
quality 60, base quality 40, and a `61M` alignment. Both strand flags occur.
The sequence stored in each SAM record is already in alignment orientation.
Each read covers the central SNP and its two neighboring bases. Reads from
different sites have distinct names so the unchanged R script cannot combine
them across loci. Apart from the declared central allele, every base matches
the reference. The 30-base matching flanks avoid short-read alignment ambiguity.

The expected output is defined independently by counting the declared alleles:

| SNP | REF reads | ALT reads | Other reads | Total | REF / (REF + ALT) |
| --- | ---: | ---: | ---: | ---: | ---: |
| chrSynthetic:50 A>G | 4 | 2 | 1 | 7 | 4/6 |
| chrSynthetic:120 C>T | 2 | 3 | 1 | 6 | 2/5 |

`scripts/verify_engine_package.py` uses samtools in the tested image to convert
this SAM to BAM and generate the FASTA index. It deliberately does not generate
a BAM index: the supported SNPcall command selects regions with `mpileup -l`.
It keeps the product's existing mpileup options, including its default quality
filters and BAQ behavior. A mismatch with the counts above fails the regression;
the fixture is not used to alter the scientific settings.

The real-image check then runs the complete BAM workflow, validates the BED
windows and the retained seven-column pileup, compares every output field with
`expected.tsv` (ratio tolerance 1e-12), and repeats the analysis from that pileup
through the public Python workflow. The existing nine-site upstream pileup
example remains an additional independent regression.
