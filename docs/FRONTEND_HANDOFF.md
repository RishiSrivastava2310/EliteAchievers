# Frontend developer handoff

The backend is ready for local integration. No frontend has been built.

1. Run start_api.bat. Require GET /ready to return ready=true.
2. Read /v1/model for actual features, context-only inputs, calibration, threshold,
   model version and hash.
3. Directory: /v1/stays?source=eicu&search=...&limit=25&offset=0.
4. Graph data: /v1/stays/{id}/timeline?at_hour=24.
5. One stored prediction: POST /v1/stays/{id}/predict?at_hour=24.
6. Stored batch: POST /v1/stays/predict/batch with
   {"stay_ids":[...],"at_hour":24}. It accepts 1-25 IDs, preserves valid results
   alongside per-stay errors, and scopes counts to only those requested IDs.
7. Manual JSON: POST /v1/predict. CSV: raw text/csv at /v1/predict/csv.
   Supplied batch: POST /v1/predict/batch with {"requests":[...]} (1-25 histories).
8. Past-only 6h graphs: stored /risk-history or POST /v1/predict/history.
9. /outcome is a visibly retrospective overlay; never feed it into prediction.
10. /v1/metrics supplies real research curves and comparisons. Preserve missing
    metrics and label the selected cohort/count denominator.

Minimal local request:

~~~javascript
const base = "http://127.0.0.1:8000";
const response = await fetch(base + "/v1/predict", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(patientHistory)
});
const result = await response.json();
if (!response.ok) throw new Error(result.detail ?? "Prediction failed");
~~~

Edit AKI_CORS_ORIGINS in .env before launch; the backend loads .env automatically.
Existing process environment variables take precedence over .env values.
If AKI_API_KEY is set, requests need X-API-Key. A deployed browser should use an
authenticated server proxy rather than contain a shared secret.

## Display rules

- predicted: show estimate, nominal alert and source threshold.
- Optional policy comparison: GET /v1/alert-profiles and alert_options on each
  prediction expose standard and fewer_alerts. Keep standard as the default.
  If showing the stricter policy, label it and show the increased-misses tradeoff.
  It is the same risk score; never relabel a suppressed standard warning as safe.
  Use backend alert booleans rather than comparing rounded display values.
- aki_already_observed: show current findings; future incident risk is unavailable.
- outside_new_aki_cohort: show why and retain available current findings.
- insufficient_data: show missing history; never replace null with 0% or "safe".
- input_sensitivity.review_required: display the sensitivity finding. Its ranges
  are engineering stress estimates, not clinical confidence intervals.
- Categories are demo policies, not clinical severity grades.
- Contributions are non-causal and not SHAP.
- Retain timestamps and missing periods; records are historical, not a live feed.
- Outcome measurement time, documentation time and biological onset differ.

docs/openapi.json is regenerated after training. API.md defines every field/unit.
REQUIREMENTS.md distinguishes completed features from research/clinical limits.
