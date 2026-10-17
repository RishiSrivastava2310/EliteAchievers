# Completion and logic audit: 0.3.0

The adult ICU hackathon model/backend is working and verified. This audit closes
engineering gaps; it does not claim clinical readiness or universal hospital use.
No frontend was built.

## Changes delivered

- Twenty predeclared model/feature candidates, grouped development-only CV with
  explicit creatinine/missing-input sensitivity penalties. Default: **boosted_leaf3_full**
  (109 features; CV AUPRC 0.650).
- Every prediction includes an engineering input-sensitivity diagnostic.
  Threshold crossings, current-AKI boundaries and >=10 percentage-point changes
  request review. Nominal alert thresholds and evaluation remain unchanged by
  that review flag.
- Corrected lab collection/result timing, delayed baselines, valid comparison
  windows, RRT censoring, urine revisions and historical first-episode eligibility.
- Confirmed timed zero urine does not require weight; positive-volume normalized
  rates do. Overlaps are checked before clipping collections, and equivalent
  duplicate records cannot discard a known interval merely through row ordering.
- Still-qualifying lab corrections preserve earliest as-of criterion recognition;
  latest corrected value availability remains a separate timestamp.
- Later CSV weight cannot become an admission-known baseline for earlier replay.
  A corrected urine record can remove its old interval instead of inventing coverage.
- Readiness validates model/database/evaluation consistency. Corrupt/incompatible
  artifacts return unavailable status. Atomic writes preserve earlier files on
  failed writes; model caches reload after replacement.
- Patient ID search, caller-history replay, bounded supplied/stored batches,
  optional shared API key, configured CORS and bounded JSON/CSV request bodies.
- Retraining refreshes examples, results and OpenAPI. Missing example types are
  explicitly unavailable; stale examples are not silently shown.
- Advanced console accepts requested treatment context. No unsupported claim that
  context-only inputs affect the prediction.
- requirements-lock.txt, doctor.bat, API/requirements handoff and repeatable checks.

## Exact scope

See [requirements checklist](../docs/REQUIREMENTS.md).
Creatinine/BUN, MAP/heart rate, potassium/bicarbonate/lactate, shared vitals, documented
urine, age and sex drive the model. Ventilation/drugs/admission type remain
context-only because reliable administration/state harmonization is incomplete.
Weight, baselines and dialysis also support separate clinical eligibility checks.
GET /v1/model classifies every accepted measurement/patient field.

The next-24h endpoint is the first qualifying **sample time**, using only available
measurements as prediction inputs. It is not biological onset, death prediction
or a guaranteed 24h warning. The operational clinical checks reference
[KDIGO 2012](https://kdigo.org/wp-content/uploads/2016/10/KDIGO-2012-AKI-Guideline-English.pdf)
and the [official eICU lab timestamp definitions](https://eicu.mit.edu/eicutables/lab/).

## Verification evidence

- **215 automated tests passed**, no errors/failures.
- **80 adversarial clinical cases** include 32 seeded delayed/revised
  creatinine timelines checked at each availability time against an independent
  decimal-exact reference, 16 urine-volume sequences checked against separate
  arithmetic, and 8 future-data/reordering invariance cases.
  See [readable clinical cases](../docs/CLINICAL_TEST_CASES.md).
- Recognition metadata audit: 1 stay changed;
  predictors, labels, sample times and model weights were unchanged. The recorded
  correction is in expert_timing_changes.json.
- **23 raw publisher hashes**, SQLite
  integrity/foreign keys, 772,791 observations.
- 20 sampled source-to-feature/label comparisons plus training/API replay parity.
- Tests cover delayed/future data, KDIGO example trajectories, missing urine,
  corrected intervals, weight timing, dialysis, patient splits, context fields,
  model corruption/reload, atomic failure, auth/body limits, batching and search.
- Full rebuild from cached raw data was exercised, including extraction, cohort,
  both training directions, hospital holdouts and automatic handoff refresh.
- Rebuilt predictor/label table (excluding corrected documentation-time metadata) exactly matches the preserved 0.2 values: **True**.
- Current-artifact live module HTTP check: **True**.
- Current-artifact actual start_api.bat HTTP check: **True**.
- Manual/advanced console, CSV, JSON, demo launcher, doctor and cached prepare
  are exercised separately. Server smoke checks stop their own temporary servers.

Machine-readable evidence: pytest.xml, verification.json, http_smoke.json,
http_launcher_smoke.json and completion.json. Run verify.bat --http; the actual
launcher smoke can also be run with scripts/smoke_http.py --launcher.

## Additional improvement work

The bounded development-only challenger study and optional source-calibrated
fewer-alert policy are documented in [the improvement report](IMPROVEMENTS.md).
Patient/hospital fold isolation, patient weights, qualification gates, calibration
support, stale profile handling, API protection and alert-subset behavior have
regression tests. Standard predictions and model weights are preserved.

## Results and remaining weaknesses

Source calibration and thresholds stay frozen externally. Earlier calibration/test
patient IDs are preserved; all audit sets were previously inspected.
No tuning uses the target hospitals' scores. Source calibration/external separation
follows the [cross-site study design](https://doi.org/10.1038/s41467-020-19551-w).
The same source cohort permits an exploratory comparison to 0.2, not a fresh
independent validation claim.

| Train | Test | Patients | Windows | AUROC | AUPRC | Sensitivity | Precision |
|---|---|---:|---:|---:|---:|---:|---:|
| eicu | internal audit | 93 | 270 | 0.802 | 0.572 | 77.2% | 35.2% |
| eicu | mimic | 50 | 215 | 0.755 | 0.502 | 81.5% | 36.4% |
| mimic | internal audit | 8 | 31 | 0.554 | 0.294 | 100.0% | 26.7% |
| mimic | eicu | 646 | 1981 | 0.620 | 0.301 | 99.0% | 21.3% |

The default model has 44 true-alert and
77 false-alert MIMIC windows, with
10 positive windows without an alert. These are correlated
windows, not independent patients. Alert fatigue remains a major unresolved problem.

Median qualifying-sample lead among detected evaluable stays is
13.15h internally and
10.99h in MIMIC. Small MIMIC-trained reverse
transport remains weak, with unsupported calibration on its small calibration set.
Hospital holdouts evaluate 92/178
hospitals with a separate fixed logistic baseline.

In the repeated illustrative creatinine check (0.81 -> 0.85 mg/dL), the estimate
change fell from 14.74 to 6.31 percentage points. The current
example stays below the threshold. This one illustration is not proof of global
robustness. sensitivity_audit.json preserves the full grid/missing-group checks;
development CV uses separate patient stress cases.

Larger approved cohorts, reliable active treatment mappings, clinician-reviewed
labels, untouched external validation and prospective workflow evaluation remain
necessary to establish clinical utility. This project does not invent those results.
