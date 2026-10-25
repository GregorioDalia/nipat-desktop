# Synthetic CPI regression fixture

These are invented counts and coordinates, not genomic observations or a real
population-frequency panel. They exercise the CPI integration using an explicit
analytical reference. They are not an evaluation of the method on real samples.
The separate script `scripts/verify_cpi_update.py` runs the unchanged upstream R
implementation through NIPAT and checks the emitted CSV and PDF presence.

## Informative pair

All sites have 100 REF+ALT reads and zero other reads. Maternal and paternal
alleles and coordinates match the synthetic panel and frequency table.

| pos1 | Maternal REF/ALT | Paternal REF/ALT | ALT frequency | PI | Fetal reads |
| --- | --- | --- | --- | --- | --- |
| 100 | 98/2 | 0/100 | 0.2 | 1 / 0.2 = 5 | 2 |
| 200 | 97/3 | 50/50 | 0.25 | 0.5 / 0.25 = 2 | 3 |
| 300 | 96/4 | 0/100 | 0.5 | 1 / 0.5 = 2 | 4 |
| 400 | 99/1 | 0/100 | 0.2 | Excluded | 1 |

The three retained sites have fetal fractions 4%, 6%, and 8%, with median 6%.
The CPI products at minimum fetal-read thresholds 2, 3, and 4 are respectively
20, 4, and 2. Their log10 values are approximately 1.301030, 0.602060, and
0.301030. Median fetal reads are 3, giving `CPI_medianFF = 0.602` in the CSV;
despite the column name, this field contains log10(CPI), not the CPI product.

| CSV field | Expected value after upstream rounding |
| --- | --- |
| N_sites_mother | 3 |
| N_sites_father | 3 |
| Median_fetal_fraction_raw | 0.06 |
| Median_fetal_fraction_percent | 6 |
| Max_logCPI | 1.301 |
| Min_logCPI | 0.301 |
| Median_logCPI | 0.602 |
| Mean_logCPI | 0.735 |
| CPI_medianFF | 0.602 |

The fourth site has only one fetal read and must be excluded from both the
summary and CPI iterations. Including it would incorrectly yield four sites
and a median fetal fraction of 5%.

## Pair without informative sites

The second mother has 100 REF and zero ALT reads at every site. Expected site
counts are both zero; all fraction and CPI fields must be literal `NA`, not zero
or an infinite value. This is a valid no-information outcome.

## Scope

One invocation creates a fresh run outside the repository and verifies exactly
these two CSV rows, the generated cutoff-panel path, and the PDF signatures of
both pair plots and `All_CPIplots.pdf`. It does not compare PDF bytes, inspect
plot appearance, or verify individual curve points that are not exported to CSV.
No BAM or reference genome is required. The runtime image must provide the
complete `cpi-v1` interface and its R dependencies.
The check also verifies the image-owned code metadata and isolated mounts.
