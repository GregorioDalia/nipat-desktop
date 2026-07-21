# DNPcall
## Info and citation
R and samtools based script to call Double Nucleotide Polymorphisms (DNPs) based on reads name.

Authors: Letizia Pistacchia and Francesco Ravasini

For issues: fravasini01@gmail.com

If your using DNPcall please cite the [original publication](https://doi.org/10.1093/bioadv/vbaf209):

Letizia Pistacchia, Francesco Ravasini, Elisa Bella, Eugenia D’Atanasio, Fulvio Cruciani, Beniamino Trombetta, DNPcall: A New Pipeline for Accurate Double Nucleotide Polymorphism Calling, Bioinformatics Advances, 2025;, vbaf209, https://doi.org/10.1093/bioadv/vbaf209

DNPcall leverages the read name information in samtools pileup file format to finely reconstruct the microhaplotype represented by the DNP.

On the left, a schematic representation of how DNPcall works: on the right, an example on the behaviour of DNPs and adjacent SNPs.

![Figure1-1](https://github.com/user-attachments/assets/04b4764d-001f-49ab-9490-440084f104d3)



## Software required
`samtools` [version 1.18 or higher](https://www.htslib.org/)

`R` version 4.2.0 or higher

`R` packages: `tidyverse` and `ComplexUpset` (both can be installed with `install.packages('package_name')`)

## Installation
DNPcall does not require particular installation processes, just download repository and go in the directory:

`git clone https://github.com/fravasini/DNPcall.git`

`cd DNPcall`

Be sure that samtools, R and all the scripts have permissions and are executable.

## Usage
To use DNPcall just run on the terminal the command:

`Rscript DNPcall.R --bamlist=list_of_bams --DNPs=list_of_DNPs --reference=reference_genome --out=output_name`

where:

- `list_of_bams` is the list of bamfiles to be analyzed, one per row with the full path to them. An example can be found in `DNPcall/examples/inputs/bamlist.txt`

- `list_of_DNPs` is the list of DNPs to be called. An example can be found in `DNPcall/examples/inputs/gnomAD_chr22_DNPs_list.txt`. The columns are in the order: chromosome, position #1 of DNP, position #2 of  DNP, reference allele, alternative allele.

- `reference_genome` is the reference genome in fasta format.

- `output_name` is the desired name of the summary output with all samples (note that the individual outputs will have the bam file name without extension).

Additional optional flag:

- `--parallel` to parallelize on the different individuals (can be useful if many individuals, but not too many DNPs, are present). To use this option, just run the same command as before with this flag:

`Rscript DNPcall.R --bamlist=list_of_bams --DNPs=list_of_DNPs --reference=reference_genome --out=output_name --parallel`

## Outputs
DNPcall will produce several files that: (1) return the genotypes of the individuals: (2) may help discriminate between DNPs and adjacent SNPs and (3) asses the overall quality of putative DNPs. Examples of these files can be found in the `examples/outputs` directory of this repository.

### Summary files:

- `{output_name}_AllGenotypes.txt` a table containing all the genotypes for each sample and each DNP analyzed. 0/0 is reference homozygous, 0/1 is heterozygous and 1/1 is alternative homozygous.

- `DNPs_covered_UpSet_plot.pdf` an UpSet plot showing DNP coverage among samples.

- `Unassigned_genotypes.pdf` a bar plot with the occurrences of unassigned genotypes (NA) per DNP.

### Individual-specific file:

- `full_output_{name_of_the_sample}` a table with exhaustive information for each individual, one DNP per line. The columns represent:

`chr`: chromosome

`pos1`: position #1 of DNP

`pos2`: position #2 of DNP

`REF`: reference allele

`ALT`: alternative allele

`N_REF`: number of reads matching reference allele

`N_ALT`: number of reads matching alternative allele

`N_Other`: number of reads matching other allele, different from both reference and alternative

`GL0`: genotype likelihood for reference homozygous (0/0)

`GL1`: genotype likelihood for heterozygous (0/1)

`GL0`: genotype likelihood for alternative homozygous (1/1)

`combined_bases`: list of all the combination of bases found in the two position of the DNP (including reference and alternative alleles)

`combined_counts`: number of all the reads matching all the combination of bases, in the same order as the previous column

`total_count`: total number of reads

`reads_discarded_for_indels`: number of reads filtered out due to the presence of indels

`ratio_reads_discarded_for_indels`: number of reads filtered out due to the presence of indels divided by the total number of reads in that DNP

- Three bar plots with the distribution of reference reads (`{name_of_the_sample}_Ref_read_count.pdf`), alternative reads (`{name_of_the_sample}_Alt_read_count.pdf`) and other (i.e., different from both reference and alternative) reads  (`{name_of_the_sample}_Other_read_count.pdf`).

- `{name_of_the_sample}_N_genotypes.pdf` a bar plot with the distribution of the possible genotypes (0/0, 0/1, 1/1 and NA) identified for the sample.

## Useful resources used to produce the examples in this repository

[SGDP project and data](https://reichdata.hms.harvard.edu/pub/datasets/sgdp/)

[gnomAD data (including Multi Nucleotide Variants)](https://gnomad.broadinstitute.org/data)
