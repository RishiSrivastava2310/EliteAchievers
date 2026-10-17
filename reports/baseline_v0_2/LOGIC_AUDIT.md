# Clinical logic and model audit: version 0.2

The backend is working as an adult ICU research demonstration. The audit corrected
clinical timing and cohort errors, retrained using development patients only, and
verified console/API/data consistency. False alerts, missing-input sensitivity
and hospital transfer remain material limitations.

## What changed

- **Sample vs result time:** an abnormal sample collected before prediction is
  already an observed outcome for retrospective labelling, even if its result
  arrives later. Features still use only information available at prediction.
- **Delayed baselines:** an older baseline arriving late can establish existing
  AKI at that later time. It must not be ignored forever or used before arrival.
- **Valid comparisons:** two creatinine measurements more than seven days apart
  do not establish an acute comparison. Feature comparison windows are relative
  to the latest sample, rather than a later scoring time.
- **Dialysis censoring:** RRT during follow-up can lower creatinine. Windows with
  RRT before a future endpoint are censored instead of labelled falsely negative.
- **Urine history:** corrected interval volumes replace earlier versions; missing
  or overlapping coverage remains unknown. A prior qualifying urine episode
  prevents a recovered patient re-entering first-episode prediction.
- **Coverage:** old readings no longer count as current model inputs. Forecasting
  requires recent creatinine, a valid earlier comparison and at least three
  measurement groups within 24h. The coverage rule is a research policy.
- **Audit counts:** repeated diagnosis matches are reported separately from unique
  chronic-dialysis stays. This reporting correction did not alter patient data.
- **Artifact compatibility:** version checks prevent old weights silently being
  used with changed feature definitions.

Definitions and five example trajectories were checked against
[KDIGO 2012, chapters 2.1 and 2.4/Table 7](https://kdigo.org/wp-content/uploads/2016/10/KDIGO-2012-AKI-Guideline-English.pdf).
The collection/entry distinction follows the
[official eICU laboratory documentation](https://eicu.mit.edu/eicutables/lab/).
A high admission creatinine followed by recovery can still hide existing AKI
when no earlier baseline is known; real-time inference does not invent one.

## Training and evaluation

Fourteen prespecified model/feature configurations were compared by grouped
development-only cross-validation. The selected default uses
**boosted_regularized7_lean**, with 38 features.
Calibration and the 18.40% alert threshold use source
calibration patients only. The source model and threshold stay frozen externally.
This separation is consistent with the source-calibration/external-validation
design in the [cross-site AKI prediction study](https://doi.org/10.1038/s41467-020-19551-w).

Old calibration/test patient IDs were preserved. Newly eligible patients went
only to development. These are **previously inspected, reused audit sets**.
The endpoint and cohort changed, so the new scores are not a clean head-to-head
improvement claim over version 0.1. The old artifacts/results remain in
baseline_v0_1; audit_protocol.json records the search and split policy.

| Train | Test | Patients | Windows | AUROC | AUPRC | Window sensitivity | Precision |
|---|---|---:|---:|---:|---:|---:|---:|
| eicu | internal audit | 93 | 270 | 0.794 | 0.572 | 73.7% | 37.2% |
| eicu | mimic | 50 | 215 | 0.747 | 0.515 | 72.2% | 37.1% |
| mimic | internal audit | 8 | 31 | 0.554 | 0.294 | 100.0% | 26.7% |
| mimic | eicu | 646 | 1981 | 0.620 | 0.301 | 99.0% | 21.3% |

For the default eICU-trained model:
- eICU AUROC patient-block bootstrap 95% interval:
  0.710?0.878.
- MIMIC AUROC interval:
  0.630?0.859.
- MIMIC has 39 true-alert and 66 false-alert windows,
  plus 15 positive windows without an alert. Repeated windows
  are correlated and are not independent patient events.
- Median sample lead among detected evaluable stays:
  12.83h in eICU and 10.04h in MIMIC.
  Only 23.8% of MIMIC events
  with an eligible positive window were warned at least 18h before the sample.
- The small MIMIC-trained model transfers poorly and has unsupported probability
  calibration. The reverse direction remains a demonstrated weakness.
- Hospital holdouts cover 178 hospitals in the labelled eICU cohort;
  92 meet evaluation-size requirements.
  These use a separate fixed logistic baseline, not the deployed model.

Intervals condition on the fitted model and do not account for all training
uncertainty. A next-24h forecast does not establish 24h advance warning.

## Verification and illustrations

Run **verify.bat** for the tests and offline audit, or **verify.bat --http** to
include a real temporary localhost server. No full dataset download is needed.

Verification covers 76 tests, 23 raw-file publisher hashes, SQLite integrity and
foreign keys across 772,791 observations, 20 source-to-feature/label replay samples,
CSV/JSON parity, invalid/future input, current AKI, urine coverage and patient splits.
Manual entry, demo.bat, CSV launcher and cached preparation were exercised.
See pytest.xml, verification.json and http_smoke.json for machine-readable evidence.

The demo now shows both success and failure illustrations:
- selected successful historical case: 51.32% risk; qualifying sample 18.35h later;
- missed early warning window: 4.98% risk; sample 19.48h later; a later alert can occur;
- false alert: 21.67% risk, with no observed qualifying AKI in the next 24h and
  late follow-up testing.

These cases were selected retrospectively and are not performance estimates.
Their outcome overlays and provenance are separate from prediction inputs.

## Unresolved logical/robustness concerns

The sensitivity audit keeps other synthetic inputs fixed. Changing the last
creatinine from 0.81 to 0.85 mg/dL moves the estimate from 17.26% to 32.00%;
omitting bicarbonate changes a no-alert example to an alert. These are warning
signs about measurement noise, missingness and threshold stability. They were
recorded after evaluation and were not used to keep selecting a better-looking
model. See sensitivity_audit.json.

Missing urine is never assumed normal or zero. Drugs, ventilation and fluids
remain context-only. The model predicts a creatinine-defined endpoint, not
all causes of deterioration, death, or proven biological injury onset.

The next meaningful improvement is larger approved cohorts, clinician-reviewed
baseline/endpoint rules, explicit noise/missingness robustness work, an untouched
external cohort and prospective alert-workflow evaluation. This prototype has
not established clinical utility or universal cross-hospital performance.
