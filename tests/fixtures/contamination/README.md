# Synthetic contamination regression fixture

These invented counts and coordinates are an analytical test reference, not
observations from biological samples. Run `python scripts/verify_contamination_update.py`
from the repository root with the existing scientific Docker image available.
Each invocation creates a new run outside the repository.

`NoRatio.tsv` and `WithRatio.TXT` contain the same counts. The second additionally
provides the ratio expected from REF/(REF+ALT); the first requires R to derive it.
Their extensions exercise normalization of staged copies to lowercase `.txt`,
which the upstream directory reader requires. Original files stay unchanged.

| pos1 | REF reads | ALT reads | Other reads | Expected result |
| --- | --- | --- | --- | --- |
| 100 | 100 | 0 | 0 | Included: contamination 0 |
| 200 | 0 | 100 | 0 | Included: contamination 0 |
| 300 | 95 | 5 | 0 | Included: contamination 0.05 |
| 400 | 5 | 95 | 0 | Included: contamination 0.05 |
| 500 | 50 | 50 | 0 | Excluded: ratio 0.5 |
| 600 | 0 | 0 | 0 | Excluded: zero denominator |
| 700 | 95 | 5 | 11 | Excluded: Other/(REF+ALT) = 0.11 |
| 800 | 90 | 10 | 0 | Excluded: outside the panel |

Both samples must have four informative DNPs, mean contamination
`(0 + 0 + 0.05 + 0.05) / 4 = 0.025` (2.5%), and sample standard deviation
`sqrt(0.0025 / (4 - 1)) = 0.0288675134594813`.
The calculation includes zero-contamination sites; excluding them would instead yield
two sites and a mean of 0.05. The verifier checks exact retained coordinates as
well as ratios and per-site contamination, so a matching aggregate alone cannot pass.

`NoSites.txt` includes only the four excluded cases and supplies the minimal
six-column schema: chr, pos1, pos2, N_REF, N_ALT, N_Other. It must yield count 0,
literal `NA` for mean and SD, and a per-site TXT containing only its header.

The summary must be `contamination_summary.txt`, tab-separated with three sample
rows and the columns individuo, informative_DNPs, mean_contamination,
sd_contamination. Per-site files are `contamination_<sample>.txt`.

The expected values are derived analytically. The integration check executes
the bundled R script through NIPAT and verifies numerical results in the selected
runtime image.
