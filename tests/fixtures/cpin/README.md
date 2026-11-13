# Analytical CPIN fixture

Nine synthetic loci exercise postnatal SNP and DNP analysis with identical counts.
They are designed independently of the implementation; no human data are included.
The homozygous mother contributes REF and population REF/ALT frequencies are 0.6/0.4.

| Locus | Expected outcome with defaults |
|---|---|
| 1 | Heterozygous child, heterozygous father: PI = 0.5 / 0.4 = 1.25 |
| 2 | Homozygous REF child and father: PI = 1 / 0.6 |
| 3 | Heterozygous child, REF father: mismatch PI = epsilon / 0.4 |
| 4 | Mother/child incompatible homozygotes |
| 5 | Maternal Other/total = 11/100 exceeds 0.1 |
| 6 | Zero maternal coverage; missing total is legitimate and becomes zero in memory |
| 7 | One read per child allele is below minimum 2 |
| 8 | Father REF ratio 0.7 is unassigned |
| 9 | Heterozygous mother is outside the model |

With SNP epsilon 0.001, heterozygous-child CPI is 0.003125 and all-compatible CPI
is 0.005208333333333333. DNP uses epsilon 0.0000892303778101497 in the same formulas.
The all-compatible support curve retains all three loci through threshold 50;
thresholds 51..100 retain only locus 2. The heterozygous curve ends at 50.
The optional allele-bearing panel contains the three eligible loci.
