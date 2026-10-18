# AKI Early Warning

An AI-powered ICU early-warning system designed to predict acute kidney injury
up to 24 hours ahead, giving doctors more time to intervene across hospital settings.

This project provides the model, data extraction, SQLite database, FastAPI backend
and Windows console demo. The frontend belongs to the separate developer.

## Run

Requires Python 3.11+ on Windows.

For a judge-friendly walkthrough, run **show_graphs.bat**. It opens kidney-reading
and risk graphs, a timeline, an observed warning-to-injury interval, and a simple
explanation. The graph report works offline and stays separate from the product
frontend.

- **show_graphs.bat**: open graphs and plain explanations for 15 varied real patient stories. Use **Next patient** in the report, or **show_graphs.bat next** from the terminal.
- **demo.bat**: print predictions, real retrospective examples and evaluation.
- **run.bat**: menu for manual inputs, CSV, stored stays and results.
- **start_api.bat**: API at <http://127.0.0.1:8000>; documentation at /docs.
- **doctor.bat**: check model, database and evaluation readiness.
- **verify.bat --http**: tests, offline audit and a temporary real HTTP server.
- Fresh machine: run **setup.bat**. It installs tested pinned dependencies,
  downloads only selected unrestricted demo tables and builds the model/database.
  Subsequent inference works offline.

~~~bat
run.bat manual
run.bat manual --advanced
run.bat csv examples\template.csv --output reports\my_prediction.json
run.bat json examples\concerning_trend.json
run.bat stays --source eicu
run.bat results
run.bat doctor
~~~

## Behavior

The model uses creatinine/BUN trends, blood pressure (MAP), heart rate, potassium,
bicarbonate, lactate, other shared vitals, documented urine volumes and demographics.
It separates future risk, existing AKI, dialysis exclusion and insufficient data.
Plain-language summaries keep important current potassium results visible beside
the future-risk estimate.
Responses include missing/stale inputs, model contributions and input-sensitivity
diagnostics. An optional stricter alert policy shows the fewer-alerts/more-misses
tradeoff alongside the standard warning. Urine criteria need complete collection intervals; positive-volume
rates also need weight. Confirmed zero output does not need weight.

Ventilation, drug exposures and admission context are accepted explicitly as
context-only inputs. They are not silently claimed as active prediction features.

## Data and checks

Uses real [MIMIC-IV demo](https://physionet.org/content/mimic-iv-demo/2.2/)
and [eICU demo](https://physionet.org/content/eicu-crd-demo/2.0.1/) records.
No full-data credentials are needed. Downloads are publisher-hash verified.
Training uses patient-separated development, calibration and audit partitions,
with development-only tuning that penalizes input sensitivity. Source models
are evaluated in both dataset directions; hospital holdouts use a fixed baseline.

Examples include a successful warning, a missed early window and a false alert.
Synthetic input examples are labelled. All results are exploratory: audit patients
were previously inspected, and cross-hospital clinical utility is not established.

## Developer handoff

[API contract](docs/API.md) | [OpenAPI JSON](docs/openapi.json) |
[Integration guide](docs/FRONTEND_HANDOFF.md) | [Requirements coverage](docs/REQUIREMENTS.md) |
[Model card](docs/MODEL_CARD.md) | [Data notes](docs/DATA.md) |
[Product validation](reports/PRODUCT_VALIDATION.md) | [Clinical test cases](docs/CLINICAL_TEST_CASES.md) | [Current audit](reports/LOGIC_AUDIT.md) | [Results](reports/RESULTS.md) |
[Improvement study](reports/IMPROVEMENTS.md) | [Product decisions](answer.txt)

GET /ready confirms usable artifacts. Core routes include /v1/predict,
/v1/predict/csv, /v1/predict/batch, /v1/predict/history and stored-stay replay.
CORS and an optional shared API key are configured through environment variables.
There is no custom frontend or account system.

Run **run.bat train** to retrain the extracted cohort. It refreshes model results,
examples and the API contract. **run.bat prepare --force** rebuilds from raw tables;
add --skip-download to use the cached source files.

Research demonstration: a next-24h forecast does not establish a full 24h warning.

Optional AI explanations are configured server-side with GEMINI_API_KEY and
GEMINI_MODEL in .env. Restart the API after changing settings. Graphs and risk
scores remain available with no provider key. The provider name never appears
in the graph report. See docs/GRAPH_DEMO.md for the one-minute walkthrough.

---

### Git Commands

- To push changes

```
git status
git add .
git commit -m "message"
git push
```

- Git pull changes

```
git pull
```
