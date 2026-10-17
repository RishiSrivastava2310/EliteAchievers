# Exploratory demo evaluation

Official unrestricted demo samples; no prospective clinical validation.
Patient-disjoint development, calibration and test partitions.
Hyperparameters chosen by grouped cross-validation in the development partition.
Source calibration and alert threshold use only calibration patients; unsupported calibration is disclosed.

| Training source | Test cohort | Patients | Windows | AUROC | AUPRC | Prevalence | Sensitivity | Precision |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| eicu | internal held-out | 99 | 289 | 0.769 | 0.534 | 0.208 | 0.800 | 0.356 |
| eicu | mimic | 53 | 234 | 0.717 | 0.463 | 0.265 | 0.806 | 0.355 |
| mimic | internal held-out | 8 | 35 | 0.543 | 0.280 | 0.257 | 1.000 | 0.281 |
| mimic | eicu | 660 | 2082 | 0.591 | 0.256 | 0.201 | 0.988 | 0.207 |

A next-24h forecast does not establish 24h of advance warning.
Recorded AKI onset is based on result availability; physiologic injury may occur earlier.
Negative windows require full ICU follow-up and a late-horizon creatinine measurement.
Urine output from the source demos has no assumed collection interval.
See evaluation.json for tuning, curves, calibration and leave-hospital-out results.
See cohort.json and extraction.json for exclusions, missingness and provenance.
