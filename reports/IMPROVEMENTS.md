# Improvement study and alert tradeoff

The deployed risk model and standard alert policy are unchanged. Five additional
challengers were compared with the incumbent using source development patients
only. This study is current for the deployed artifact: **True**.
Qualified challenger: none; retain the incumbent.

## Bounded model comparison

Three folds isolate patients; three additional folds isolate hospitals and purge
every held-hospital patient's other stays from fitting data. The current study
uses 455 development patients,
170 hospitals and
1433 correlated windows.
These are previously used development data, not an untouched external evaluation.

| Configuration | Patient-fold AUPRC | Hospital-fold AUPRC | Combined selection score |
|---|---:|---:|---:|
| incumbent | 0.650 | 0.677 | 0.591 |
| patient_balanced | 0.646 | 0.664 | 0.568 |
| regularized | 0.659 | 0.667 | 0.586 |
| patient_balanced_regularized | 0.644 | 0.645 | 0.562 |
| blend_75_tree | 0.668 | 0.678 | 0.589 |
| blend_50_tree | 0.655 | 0.655 | 0.554 |

Score = AUPRC - 0.5 * creatinine-stress p95 change - 0.25 * missing-group
p95 change, averaged equally over the two fold families. Choices and acceptance
criteria were recorded before fitting in improvement_protocol.json. Qualification
requires >=0.01 score gain, no family AUPRC drop >0.01, no Brier increase >0.005,
no creatinine-stress increase >0.02, and improvement in at least 4/6 folds.
The 75% tree blend improved average precision and Brier scores but failed the
recorded robustness/consistency gate; this does not justify replacing production.

## Optional alert policy

GET /v1/alert-profiles returns thresholds and audit results. Predictions include
alert_options.standard and, when supported, alert_options.fewer_alerts.
The original alert/alert_threshold/risk_category remain the standard policy.
There is one risk estimate; thresholds change alert decisions, not that estimate.

The stricter threshold maximizes source-calibration precision with >=70% window
sensitivity and must exceed the standard threshold. At least five calibration
patients per outcome class are required. Both thresholds are frozen before
internal/external audit evaluation. The sensitivity floor is a demonstration
policy, not a clinical guideline or an external guarantee.

| Policy | Audit set | Threshold | True-alert windows | False-alert windows | Missed positive windows | Sensitivity | Precision |
|---|---|---:|---:|---:|---:|---:|---:|
| standard | internal | 16.94% | 44 | 81 | 13 | 77.2% | 35.2% |
| standard | mimic | 16.94% | 44 | 77 | 10 | 81.5% | 36.4% |
| fewer_alerts | internal | 22.01% | 41 | 58 | 16 | 71.9% | 41.4% |
| fewer_alerts | mimic | 22.01% | 41 | 60 | 13 | 75.9% | 40.6% |

These are repeated prediction windows, not unique patients or alarms in a live
workflow. Fewer alerts can miss more AKI. Previously inspected audit outcomes
remain exploratory; profile comparison does not establish prospective utility.
Missing/stale optional profiles fall back to the standard forecast, while the
profile-report endpoint returns 503 until profiles are refreshed.

## Inputs left as context after source review

- Medication: eICU orders and infusion records are currently merged into one flag, unlike MIMIC administration sources. Orders are not proof of administration. Missing entries are not confirmed non-exposure.
- Ventilation: Positive procedure/treatment mentions lack a harmonized current on/off interval and verified absence. A past mention is not proof of ventilation at prediction time.
- Admission: eICU unitadmitsource is a location (ED/floor/OR), whereas MIMIC admission_type describes admission urgency. Current categories are incomplete and not equivalent.

Documentation counts are retained in input_support_audit.json. Activating these
flags without fixing their meaning and timing would add unsupported certainty.
A future administration adapter needs separate provenance, confirmed start/stop
knowledge and unknown-versus-absent handling before development-only evaluation.

References: [official eICU medication semantics](https://eicu.mit.edu/eicutables/medication/),
[eICU patient/admission columns](https://eicu.mit.edu/eicutables/patient/),
[group-isolated validation](https://scikit-learn.org/1.8/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html),
[boosted-tree sample weights](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html).

Reproduce with .venv\Scripts\python.exe scripts\qualify_improvements.py.
Refresh policies without retraining with scripts\refresh_alert_profiles.py;
prepare/train also refreshes them automatically. Run verify.bat --http for regression
and live API checks. Larger approved cohorts, clinician-reviewed labels and
prospective evaluation remain necessary to establish clinical reliability.
