# Synthetic DNPcall engine fixture

These artificial data contain no participant or patient information. They test
packaging and execution, not scientific or clinical validity.

`reference.fa` contains one 300-base synthetic contig (`chrDnpSynthetic`). Its
background bases were generated with Python `random.Random(505).choice("ACGT")`,
then the three declared REF dinucleotides were substituted at positions 50–51,
140–141 and 230–231. `DNP_list.txt` deliberately uses lowercase allele letters
to exercise normalization before passing the panel to the unchanged R script.

Each of `reads_A.sam` and `reads_B.sam` contains 63 coordinate-sorted, unpaired,
62-base reads with unique QNAMEs, mapping quality 60, base quality 40 and `62M`
alignments. Both strand flags occur. SAM sequences are already in alignment
orientation. Each read contains the chosen central dinucleotide and 30 matching
reference bases on either side. There are no indels. The start positions are
20, 110 and 200, and names are unique across loci and samples.

The expected counts below are defined by the synthetic input design, not by
running DNPcall or its new wrapper. They are committed in `expected.tsv`.

| Sample | Position | REF | ALT | Other | REF reads | ALT reads | Other reads | GT |
| --- | ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| A | 50 | AC | GT | AT | 20 | 0 | 1 | 0/0 |
| A | 140 | TA | CG | TG | 10 | 10 | 1 | 0/1 |
| A | 230 | GC | AT | GA | 0 | 20 | 1 | 1/1 |
| B | 50 | AC | GT | AT | 0 | 20 | 1 | 1/1 |
| B | 140 | TA | CG | TG | 12 | 8 | 1 | 0/1 |
| B | 230 | GC | AT | GA | 20 | 0 | 1 | 0/0 |

Every locus has 21 reads, of which 20 are REF/ALT. The Other fraction, 1/21,
is below the native R threshold of 0.1 that masks a genotype. The heterozygous
log-likelihood is independently known: 20 × log(0.5), approximately −13.863.
It does not depend on base quality because the model assigns probability 0.5
to either expected allele under the heterozygous genotype.

`scripts/verify_engine_package.py` uses samtools inside the tested image to
convert both SAMs to BAM and generate the FASTA index. It does not generate
BAM indexes; `mpileup -l` supports this input mode. Default base-quality filters
and BAQ remain enabled. No scientific settings are changed to fit the fixture.
GL0 and GL2 are not hardcoded from the SAM's original Q40 because BAQ can alter
qualities. All scientific table fields, including those likelihoods, must also
match an independent invocation of the unchanged packaged R interface.

The real-image checks cover the complete engine request and the public client
workflow with a project directory containing only `compose.yaml`: a single BAM,
multiple BAMs with identical original basenames in distinct folders, and a BAM
list with quoted relative paths, spaces and a UTF-8 BOM. Selection order is
deliberately reversed for the multiple-BAM tests. Sequential and parallel
results must match in every table field. Assertions cover counts, haplotypes,
genotypes, sample mappings, normalized panel/list, summary columns and PDF
presence/signatures. Single-sample runs produce five PDFs and skip UpSet;
two-sample runs produce ten PDFs. Original inputs must remain unchanged.

The source-free client checks also verify image/preparation identities, read-only
input mounts, a writable current run only, and disabled container networking.
Successful native DNPcall removes its temporary pileup and BED; the normalized
panel and BAM list in `work` remain available as execution evidence.
