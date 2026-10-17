# Exploratory demo evaluation

Official unrestricted demo samples; no prospective clinical validation.
Patient-disjoint development, calibration and test partitions. Previously inspected baseline holdout IDs are preserved; these are reused audit sets, not fresh validation.
Hyperparameters chosen by grouped cross-validation in the development partition.
Source calibration and alert threshold use only calibration patients; unsupported calibration is disclosed.

| Training source | Test cohort | Patients | Windows | AUROC | AUPRC | Prevalence | Sensitivity | Precision |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| eicu | internal held-out | 93 | 270 | 0.794 | 0.572 | 0.211 | 0.737 | 0.372 |
| eicu | mimic | 50 | 215 | 0.747 | 0.515 | 0.251 | 0.722 | 0.371 |
| mimic | internal held-out | 8 | 31 | 0.554 | 0.294 | 0.258 | 1.000 | 0.267 |
| mimic | eicu | 646 | 1981 | 0.620 | 0.301 | 0.207 | 0.990 | 0.213 |

A next-24h forecast does not establish 24h of advance warning.
Observed onset uses the qualifying SAMPLE time; result availability limits inputs. Biological injury may occur earlier.
Negative windows require full ICU follow-up and a late-horizon creatinine sample. RRT before a future endpoint causes censoring.
Urine output from the source demos has no assumed collection interval.
See evaluation.json for tuning, curves, calibration and leave-hospital-out results.
See cohort.json and extraction.json for exclusions, missingness and provenance.
