# **cfDNA fetal fraction and CPI distribution**

This module estimates the fetal fraction (on maternal-informative DNPs) and computes the CPI distribution across increasing fetal-read thresholds, starting from files produced in the DNPcall workflow (*i.e*., post–pileup per-site counts for mother and putative father). It generates per-pair CPI plots and a summary table.

**Reference:**  
Letizia Pistacchia, Francesco Ravasini, Elisa Bella, Eugenia D’Atanasio, Fulvio Cruciani, Beniamino Trombetta,  
*DNPcall: A New Pipeline for Accurate Double Nucleotide Polymorphism Calling*, Bioinformatics Advances, 2025;, vbaf209.  
https://doi.org/10.1093/bioadv/vbaf209

---

## Folder Structure

```text
CPI_from_cffDNA
├── cfDNA_CPI_estimator.R
├── README.md
└── examples
    ├── inputs
    │   ├── DNPcall_output
    │   │   ├── MotherA1.txt
    │   │   ├── FatherA1.txt
    │   │   ├── MotherA2.txt
    │   │   └── FatherA2.txt
    │   ├── DNPpanel.txt
    │   └── pop_allFreq.txt
    └── outputs
        ├── Summary_FetalFraction_CPI.xlsx
        └── plots
            ├── All_CPIplots.pdf
            ├── MotherA1-FatherA1_DNPs_CPIplot.pdf
            └── MotherA2-FatherA2_DNPs_CPIplot.pdf
```

---

## Software required

- **R** ≥ 4.2.0  
- **R packages**:
  - dplyr
  - tidyr
  - ggplot2
  - patchwork
  - argparse

All required R packages must be installed before running the script.

## Installation

No installation is required. Just download the repository and move into the directory:

```bash
git clone https://github.com/lpistacchia/NEWPAT.git
cd NEWPAT/CPI_from_cffDNA
```

## Usage

Below is an example using the example input files provided in `examples/`,  
where the pairs are named `MotherA1`–`FatherA1` and `MotherA2`–`FatherA2`.

```bash
Rscript cfDNA_CPI_estimator.R \
  --pileup_dir examples/inputs/DNPcall_output \
  --out_dir examples/outputs \
  --pairs "A1:A1,A2:A2" \
  --mother_prefix Mother \
  --father_prefix Father \
  --cutoff_map examples/inputs/DNPpanel.txt \
  --popfreq examples/inputs/pop_allFreq.txt
  --err_const
```

---

`--err_const` — default mismatch penalty in CPI  
Constant used in the CPI formula when an *incompatible paternal genotype* is observed at an informative DNP site.  

- Default: `"8.9230378e-05"` (empirically derived from the DNP error rate module).  
- You may override it (*e.g.* `--err_const 1e-04`).  

Since it enters the PI at *mismatching loci*, it directly affects the CPI distribution.

---

`--cutoff_map` — controls which DNPs are used  
Allows restricting computation to a specific DNP panel rather than using all pileup sites.  
You can pass either:

- a **single** list → `--cutoff_map examples/inputs/DNPpanel.txt`  
- **multiple labelled** panels → `--cutoff_map "panel1=DNPpanel1.txt,panel2=DNPpanel2.txt"`

If omitted, the script runs in **ALL mode** → uses *all positions in the pileup* (*i.e.*, no panel filtering).


## Output

1) ***`Summary_FetalFraction_CPI.xlsx`***

Contains one row per mother–father pair (and **per cutoff panel**, if multiple are provided):

| Column               | Meaning |
|----------------------|---------|
| **N_sites_mother**      | maternal-informative loci retained |
| **N_sites_father**      | loci also informative in the father (after merge) |
| **Median_fetal_fraction** | site-level median fetal fraction within the panel |
| **Max_logCPI**          | highest log10(CPI) over all thresholds |
| **Min_logCPI**          | lowest  log10(CPI) over all thresholds |
| **Median_logCPI**       | median log10(CPI) over thresholds |
| **CPI_medianFF**        | log10(CPI) computed at the median fetal-read threshold |


If `--cutoff_map` includes more than one list, the table will contain **one block of rows per cutoff label** (integrating all specified panels).

---

2) ***`PDF plots`*** (saved under `outputs/plots/`)

- **One PDF per pair** — log10(CPI) curve across increasing fetal-read thresholds  
  *(one curve per cutoff if multiple lists were given)*

- **All_CPIplots.pdf** — all pairs stacked in a single multi-panel PDF  
  *(again, integrates all cutoff panels if multiple were supplied)*




## Notes

- Input `.txt` files must be the post–DNPcall per-site matrices.
- Both `DNPpanel` and `pop_allFreq` must contain at least: `chr, pos1, pos2`
  (`pop_allFreq` must also contain `Ref_f.pop`, `Alt_f.pop`).
- If `--cutoff_map` is omitted, all sites are used (no panel filtering).
- The script does not generate pileups nor performs DNP calling.

## Contact

For questions, please contact:

Letizia Pistacchia, letizia.pistacchia@uniroma1.it  


## Citation

If you use this module, please cite the original DNPcall paper:

Letizia Pistacchia, Francesco Ravasini, Elisa Bella, Eugenia D’Atanasio, Fulvio Cruciani, Beniamino Trombetta  
“DNPcall: A New Pipeline for Accurate Double Nucleotide Polymorphism Calling”  
Bioinformatics Advances, 2025; vbaf209 — https://doi.org/10.1093/bioadv/vbaf209

