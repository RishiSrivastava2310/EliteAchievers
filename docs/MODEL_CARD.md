# Model card: AKI Early Warning 0.3

## Intended use and clinical target

Adult ICU hackathon/research demonstration on official unrestricted MIMIC-IV
demo v2.2 and eICU demo v2.0.1. Predict the first observed creatinine-defined AKI
episode within 24h. This is not validated for treatment decisions, biological
onset, death prediction, treatment benefit or a guaranteed 24h advance warning.

Operational KDIGO-2012: >=0.3 mg/dL compared with a preceding measurement within
48h, or >=1.5 times a preceding observed value within 7 days. The preceding
minimum is a proxy baseline. Stable high creatinine alone does not prove an
acute change. Earlier AKI or dialysis/RRT excludes an incident forecast.

Only available values/revisions enter features. Delayed baselines can establish
AKI when they arrive. Future recovery never invents a healthy real-time baseline.
Still-qualifying lab corrections preserve the earliest as-of criterion recognition;
current stage/value use the latest corrected result. A retracted abnormal result
is not retained as current AKI. Corrected urine records replace volume and interval.
Urine checks need complete non-overlapping coverage. Positive-volume normalized
rates also need weight; exact timed zero output does not.

Outcome time is the qualifying sample measurement/collection time, using final
available corrections; result-entry time remains separate. Already collected
samples are not future AKI. Negatives require full 24h follow-up and a sample
collected 18-24h into the horizon. RRT before a future endpoint censors the window.
Testing, death/discharge and unknown admission baselines create selection bias.

Score every 6h during ICU hours 12-168, with creatinine within 24h, an available
preceding 7-day comparison and >=3 recent measurement groups. The coverage
minimum is a research policy, not a clinical guideline.

## Features and selection

Active: creatinine, BUN, potassium, bicarbonate, lactate, MAP, heart rate, SpO2,
respiratory rate, temperature, documented urine volumes, age, recorded sex and
ICU time. Full/compact representations use recent values/ages, summaries, slopes
and creatinine changes. Drug/ventilation/fluids/admission/comorbid fields are
context-only pending reliable timing and harmonization.

Twenty prespecified candidates compare logistic, boosted-tree and spline-logistic
models, with optional training-only group dropout. Derived masked copies are not
independent patients; calibration/test outcomes are not augmented.
Preprocessing fits development data only.

Patient-grouped development CV selects:
AUPRC - 0.5 * creatinine-stress p95 risk change
      - 0.25 * missing-group p95 risk change.
Stress features are rebuilt from available raw observations of up to 90 distinct
development patients/source, one window each. Latest creatinine +/-0.04 mg/dL
and removal of one optional group are engineering assumptions, not a laboratory
error model. See completion_protocol.json and evaluation.json.

## Calibration and evaluation

Only source calibration patients fit positive-slope sigmoid calibration and a
threshold maximizing precision at >=80% window sensitivity. Raw uncalibrated
estimates remain explicit when slope is non-positive or fewer than five patients
per outcome class support calibration. The target sensitivity is not guaranteed
externally.

Earlier source calibration/test patient IDs are preserved; newly eligible
patients enter development. These are previously inspected reused audit sets,
not fresh validation. Source models/thresholds stay frozen externally, in both
dataset directions. Default deployment prefers larger eICU independently of
test scores.

Hospital holdouts use a separate fixed logistic baseline/0.5 threshold, removing
all held-out-hospital patients from training. They do not validate the selected
deployed model. Small-hospital insufficiency is reported.

Metrics include discrimination, AUPRC/prevalence, calibration/Brier, confusion,
window/event sensitivity, sample lead and alerts/100 evaluated windows.
Patient-block intervals preserve repeated-window dependence but omit full
training uncertainty. Event denominators require eligible positive windows.

## Explanations, sensitivity and limits

Median-replacement contributions are non-additive, non-causal and not SHAP.

Each forecast reports input-sensitivity ranges. They are not confidence intervals
or bounds on true risk. Review is requested for threshold crossing, current-AKI
boundary or >=10 percentage-point estimate change. This demo review rule leaves
the nominal alert and threshold evaluation unchanged.

Small selected demos, weak reverse transfer, false alerts, missingness and hidden
admission AKI remain limits. A lower stress change is not clinical robustness
proof. Larger approved cohorts, clinician-reviewed labels, untouched external
evaluation and prospective workflow evaluation remain necessary for clinical use.

References: [KDIGO 2012](https://kdigo.org/wp-content/uploads/2016/10/KDIGO-2012-AKI-Guideline-English.pdf),
[eICU laboratory times](https://eicu.mit.edu/eicutables/lab/),
[cross-site evaluation design](https://doi.org/10.1038/s41467-020-19551-w),
[spline transformer](https://scikit-learn.org/1.8/modules/generated/sklearn.preprocessing.SplineTransformer.html).


## Additional development study and alert policy

Five further challengers (patient-balanced, regularized and fixed tree/linear
blends) were compared with the incumbent in patient-isolated and hospital-isolated
development folds. No challenger passed the prerecorded joint performance and
sensitivity gate, so weights are unchanged. This additional development study is
separate from the fixed logistic hospital holdouts described above.

A source-calibrated stricter alert policy is available alongside standard.
It changes alert decisions only; it is not an accuracy or calibration improvement.
Selection requires >=70% source-calibration window sensitivity and a threshold
above standard. External sensitivity is not guaranteed. Existing alert outputs
remain standard. See ../reports/IMPROVEMENTS.md for the full tradeoff and limits.
