# Backend API contract

Start start_api.bat. Base URL: http://127.0.0.1:8000. OpenAPI: /openapi.json;
interactive API documentation: /docs. No custom frontend or account registration.

## Routes

| Method | Path | Purpose |
|---|---|---|
| GET | /health | Process health (public) |
| GET | /ready | Model/database/evaluation checks; 503 when incomplete (public) |
| GET | /v1/model | Actual model features, context-only fields, threshold, provenance |
| GET | /v1/input-schema | Complete request schema, units and bounds |
| POST | /v1/predict | One patient's JSON history |
| POST | /v1/predict/csv | Raw text/csv history; optional at_hour query |
| POST | /v1/predict/history | Past-only 6h risk points from caller history |
| POST | /v1/predict/batch | 1-25 supplied requests; ordered prediction list |
| POST | /v1/stays/predict/batch | 1-25 stored IDs at one hour; per-stay errors and scoped counts |
| GET | /v1/stays | Source/search/limit/offset paginated stored stays |
| GET | /v1/stays/{id}/timeline?at_hour=12 | Available measurements at selected hour |
| POST | /v1/stays/{id}/predict?at_hour=12 | Historical stored-patient prediction |
| GET | /v1/stays/{id}/risk-history?through_hour=48 | Stored past-only risk points |
| GET | /v1/stays/{id}/outcome | Explicitly retrospective outcome overlay |
| GET | /v1/metrics | Real evaluation, curves, calibration and hospital results |
| GET | /v1/data-quality | Source extraction audit |
| GET | /v1/examples | Clearly labelled synthetic request examples |

All /v1 routes use X-API-Key when AKI_API_KEY is configured. No supplied patient
history is permanently inserted by prediction requests. Source is mimic or eicu,
stay IDs are source-prefixed, and a patient can have several ICU stays.

## JSON

~~~json
{
  "patient": {"age": 65, "sex": "male", "weight_kg": 75},
  "at_hour": 12,
  "readings": [
    {"hour": 0, "available_hour": 1, "creatinine": 0.8, "bun": 18, "map": 80},
    {"hour": 6, "available_hour": 7, "creatinine": 0.9, "bun": 24, "map": 70},
    {"hour": 12, "creatinine": 1.0, "bun": 30, "map": 62}
  ]
}
~~~

Hours are relative to ICU admission; negative hours cover pre-ICU history.
hour is measurement time. available_hour is when it became available and defaults
to hour. Both must be <= at_hour. Later corrections replace earlier versions
only when available. Future or conflicting same-time inputs are rejected.

The adult model forecasts during ICU hours 12-168. It requires a creatinine sample
within the past 24h, an available earlier comparison within 7 days of that sample,
and at least 3 measurement groups recorded in the past 24h. The 3-group minimum
is a research coverage rule. Current-criteria checks still apply outside this window.

Patient fields: age (18-110), sex (male/female/unknown), weight_kg, admission_type
(emergency/elective/urgent/other/unknown), baseline_creatinine, baseline_hour,
chronic_kidney_disease, diabetes, hypertension, heart_failure and chronic_dialysis.
Supply baseline value and timestamp together. Unknown baseline is never assumed
normal. Static patient context must already be known at admission for replay.
Use timestamped readings for a later weight or dialysis-history discovery.

## Units and missing values

| Reading field | Unit |
|---|---|
| creatinine, bun, glucose | mg/dL |
| potassium, bicarbonate, sodium, lactate | mmol/L |
| hemoglobin | g/dL |
| wbc | 10^9/L |
| map | mmHg; supply mean arterial pressure |
| heart_rate | bpm |
| spo2 | percent, e.g. 97 |
| respiratory_rate | breaths/min |
| temperature | Celsius |
| weight_kg | kg |
| urine_output_ml | documented mL |
| urine_interval_hours | Collection interval ending at hour; omit if unknown |
| fluid_input_ml | documented mL for that observation |
| ventilation, vasopressor, diuretic, nephrotoxic_drug, rrt, dialysis_history | 0 or 1 |

Unknown values are omitted or null, never invented zeros.
Clinical urine criteria require complete non-overlapping intervals. Positive-volume
normalized rates also require weight; exact timed zero output does not. Irregular
source volumes are not silently interpreted as hourly rates.
Ventilation, medication and fluid context is not a treatment recommendation.
GET /v1/model distinguishes active measurements from context-only inputs.

## CSV

Send raw CSV text as Content-Type: text/csv, not multipart upload.
Bodies (JSON or CSV) are limited to 2 MB. Histories allow 1-10,000 reading rows.
Use examples/template.csv.

~~~csv
hour,age,sex,creatinine,bun,map,heart_rate
0,65,male,0.8,18,80,80
6,65,male,0.9,24,70,85
12,65,male,1.0,30,62,90
~~~

age and hour are required. Blank cells remain unknown. Repeated patient metadata
must be consistent. One patient/stay per CSV. Unknown/duplicated columns fail.
CSV weight_kg belongs to each timestamped reading; a later weight is never
promoted to a baseline for earlier replay. JSON patient.weight_kg means an
admission-known context weight. For later weights use readings[].weight_kg.

By default at_hour is the latest available_hour. An explicit query cannot use
future rows. Error responses omit the raw patient row.

## Response

Urine windows report complete collection coverage separately from rate availability.
complete can be true while rate_ml_kg_h is null when volume is positive and weight
is unknown; volume_ml then reports the known total. Unknown coverage returns null
volume/rate. Exact zero from a longer collection can establish zero in a contained
window; positive volumes are never prorated. Overlapping intervals are unknown.

- predicted: numeric predicted_risk (0-1) and predicted_risk_percent (0-100).
- aki_already_observed: future new-AKI risk is null; show current criteria.
- outside_new_aki_cohort: dialysis/RRT or unsupported prediction time; risk is null.
- insufficient_data: insufficient recent history/coverage; risk is null.

alert uses the frozen source calibration threshold. low/moderate/high are demo
policies, not clinical cutoffs. Never render null as 0% or "safe".
model_contributions are non-additive median-replacement probability differences;
they are neither SHAP nor proven patient-specific causes.

input_sensitivity is null without a forecast. Otherwise it tests the latest
creatinine +/-0.04 mg/dL and removal of one measured optional group, rebuilding
features. Unscorable variants are skipped. Clinical-boundary sensitivity is
reported separately. ranges gives minimum/maximum estimates, threshold crossing
and maximum percentage-point change.

These are engineering stress scenarios, not laboratory error specifications,
confidence intervals or bounds on true risk. review_required is true for a
threshold crossing, current-AKI boundary, or >=10 percentage-point estimate
change. That review rule is a demo policy. Nominal alerts/evaluation still use
the reported source threshold.

## History, batch and outcome

POST /v1/predict/history takes the normal request and returns 6h points from
ICU hour 12 through min(at_hour,168). Each point hides later readings/revisions
and a later supplied baseline. No future outcome enters inputs.

POST /v1/predict/batch takes {"requests": [<normal request>, ...]}.
It returns an ordered list. One invalid request rejects the entire batch with 422.

Keep /outcome explicitly retrospective. first_qualifying_sample.measurement_hour
defines the forecast endpoint. first_documented_creatinine_aki separately records
the earliest as-of criterion recognition for a currently qualifying sample. A
still-abnormal correction preserves that earlier documented_hour; its latest
value became known at latest_result_available_hour. Neither timestamp establishes
biological injury onset or an actual doctor's recognition time.

## Integration configuration

~~~bat
set AKI_CORS_ORIGINS=http://localhost:3000,http://localhost:5173
set AKI_API_KEY=your-local-integration-key
start_api.bat
~~~

CORS is disabled unless configured. X-API-Key is allowed in configured preflight
requests. With no key, the local demo works without credentials.
This shared key is not role-based user authentication. Keep a deployed secret
out of publicly served browser code; use a server proxy or real user authentication
for public deployment. /health and /ready expose no patient rows.

Errors: 401 configured-key failure, 404 unknown stay, 413 oversized body,
415 incorrect CSV content type, 422 invalid/missing/future input, 503 unavailable
model or incomplete readiness. Read /ready before presenting the backend as usable.


## Optional alert tradeoff

GET /v1/alert-profiles returns source-calibration thresholds and aggregate audit
results; it uses the same API-key requirement as other /v1 routes.
Predicted responses add alert_options.standard and, when supported,
alert_options.fewer_alerts, each containing threshold and alert. The stricter
option includes its tradeoff text: fewer alerts may miss more AKI.
The existing alert, alert_threshold and risk_category still use standard.

Thresholds are frozen using source calibration only. The stricter policy targets
>=70% calibration-window sensitivity, not a clinical or external guarantee.
Use returned alert booleans; scores are rounded for display. Non-predicted
responses have an empty alert_options. Missing/stale optional policy artifacts
leave standard forecasting available; the profile endpoint then returns 503.
prepare/train refreshes policies. See ../reports/IMPROVEMENTS.md for actual
false-alert and missed-window counts, not a claim of a more accurate risk score.


## Plain-language clinical summary

Every prediction includes clinical_summary: headline, kidney_headline, message,
review_required, urgent_review_required and current_findings.
The summary explains the result in plain language, including earlier injury,
dialysis history and missing information. A below-threshold forecast never
labels the overall patient condition normal.

The latest available potassium result >=6.0 mmol/L adds an urgent-review finding
with its value, unit, sample time, entry time and age. It asks the ICU team to
review the result; it does not prescribe treatment or assert an old value remains
high. A newer sample or available correction replaces the earlier finding.
This review flag is separate from the future kidney-warning alert and its
optional stricter policy. The rule references UK Kidney Association 2023,
guidelines 14.1/14.2; it is not a full monitor for all dangerous ICU conditions.

History points retain the summary using only that point's available readings.
Stored-batch counts may include urgent_reviews, separate from future-risk alerts.
See ../reports/PRODUCT_VALIDATION.md for patient-case evidence.


## Plain explanation endpoint

POST /v1/summarize accepts the same patient-history body as /v1/predict.
It computes the model result, then returns summary, headline and structured facts.
Provider details and reason_code are backend metadata; display only the plain
summary/headline/facts. Do not display provider names or API settings in the app.
GET /v1/summary-status reports configured/model without exposing a key.

GEMINI_API_KEY and GEMINI_MODEL configure the optional provider in .env.
The current default is gemini-3.5-flash-lite; model names are configurable.
The API key is sent in a header to Google's fixed API host, never a URL.
Only computed facts go to the provider, with no patient IDs or raw history.
Regular prediction endpoints never make provider calls. Missing keys, timeouts,
invalid replies or provider errors return a local plain-language explanation.
Exact numeric risk, clinical findings and alert decisions always come from the
backend model/rules. Generated prose does not replace those fields.
