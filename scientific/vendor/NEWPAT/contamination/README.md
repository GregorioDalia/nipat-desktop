# **Contamination Estimate**

Contamination Estimate is a post-processing module designed to quantify potential sample contamination in the NIPAT workflow.  
This module starts **from files produced in the DNPcall workflow**, which report per–position allele counts for all detected Double Nucleotide Polymorphisms (DNPs).
It does not perform any read processing or variant calling: it operates exclusively on DNPcall output tables.


**Reference:**  
Letizia Pistacchia, Francesco Ravasini, Elisa Bella, Eugenia D’Atanasio, Fulvio Cruciani, Beniamino Trombetta,  
*DNPcall: A New Pipeline for Accurate Double Nucleotide Polymorphism Calling*, Bioinformatics Advances, 2025;, vbaf209.  
https://doi.org/10.1093/bioadv/vbaf209

---

## Folder Structure

```text
contamination
├── detect_contamination.R
├── README.md
└── examples
    ├── inputs
    │   ├── sample1.txt
    │   ├── sample2.txt
    │   ├── DNPpanel.txt
    └── outputs
        ├── contamination_sample1
        └── contamination_sample2
        └── contamination_summary
```

---

## Software required

- **R** ≥ 4.4.2  
- **R packages**:
  - dplyr ≥ 1.1.4
  - openxlsx ≥ 4.2.8
  - tools  

All required R packages must be installed before running the script.

## Installation

No installation is required. Just download the repository and move into the directory:

```bash
git clone https://github.com/lpistacchia/NEWPAT.git
cd NEWPAT/contamination
```

## Usage

Run on a directory containing one or more DNPcall output files:

```bash
Rscript detect_contamination.R \
  path/to/DNPpanel.txt \
  path/to/input_directory/ \
  path/to/output_directory/
```

Run on a single file:

```bash
Rscript detect_contamination.R \
  path/to/DNPpanel.txt \
  sample.txt \
  path/to/output_directory/
```

---

Arguments must be provided in the exact order: 'DNPpanel.txt', 'input_path', 'output_dir'.

| Position | Argument             | Description                                                             |
| -------- | -------------------- | ----------------------------------------------------------------------- |
| **1**    | **`'DNPpanel.txt'`** | Path to the DNP panel file (`n°DNP`, `chr`, `pos1`, `pos2`).            |
| **2**    | **`'input_path'`**   | Directory **or** single file containing DNPcall workflow output tables. |
| **3**    | **`'output_dir'`**   | Directory where output files will be saved (automatically created).     |


## Output

The module produces the following files:

### **1. `contamination_<sample>.txt`**

One file per sample, containing all **informative DNPs** used for contamination estimation.

Each row includes:

- `chr`  
- `pos1`  
- `pos2`  
- `N_REF`  
- `N_ALT`  
- `N_Other`  
- `N_unexpected`  
- `contamination`  

Contamination is computed as:

*contamination = N_unexpected / (N_REF + N_ALT)*


`N_unexpected` corresponds to the read count supporting the allele **not expected** under the homozygous genotype  
(e.g. ALT in REF/REF sites, or REF in ALT/ALT sites).

Because part of `N_unexpected` may derive from sequencing errors, this value represents an **upper bound** of the true contamination level.

---

### **2. `contamination_summary.xlsx`**

An Excel file summarizing all processed samples.  
It contains, for each sample:

- **sample name** 
- **mean contamination** across informative DNPs  
- **standard deviation** of contamination  

This file provides a compact contamination overview for all samples in the run.



## Contact

For questions, please contact:

Letizia Pistacchia, letizia.pistacchia@uniroma1.it  


## Citation

If you use this module, please cite the original DNPcall paper:

Letizia Pistacchia, Francesco Ravasini, Elisa Bella, Eugenia D’Atanasio, Fulvio Cruciani, Beniamino Trombetta  
“DNPcall: A New Pipeline for Accurate Double Nucleotide Polymorphism Calling”  
Bioinformatics Advances, 2025; vbaf209 — https://doi.org/10.1093/bioadv/vbaf209

