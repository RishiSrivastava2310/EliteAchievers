# Requested scope and evidence

This checklist covers the adult ICU hackathon backend. "Active" means a field
influences the model; "context" means accepted but not used in this version.

| Requested point | Delivery | Evidence / practical limit |
|---|---|---|
| Predict new AKI in the next 24h | Creatinine-defined first episode with causal inputs | Clinical/timing tests; not death prediction or guaranteed 24h lead |
| Creatinine graph changes | Measured values, slopes, change and ratio; current AKI separately | Timeline, risk history, retrospective outcome and sensitivity diagnostic |
| Creatinine and BUN | Active | Shared extraction/unit maps; examples and replay parity |
| Blood pressure and heart rate | Active | BP supplied as MAP in mmHg |
| Urine output | Active documented volume; separate complete-interval current criteria | Missing is unknown; no invented hourly rate |
| Potassium, bicarbonate, lactate | Active | Shared blood-lab maps and explicit units |
| Ventilation | Context | JSON/CSV/advanced console; not an active model feature |
| Vasopressors and diuretics | Context | Orders/exposures have incomplete administration timing |
| Nephrotoxic drugs | Context | Accepted and disclosed; not claimed as active administration features |
| Age and sex | Active | Adults >=18; recorded sex can be unknown |
| Admission type | Context | Canonical categories; not active |
| Weight and renal history | Weight supports positive-volume urine rates; baseline supports comparisons; dialysis excludes incident forecast | Late weight/history must remain timestamped |
| Accessible relevant data | 23 selected unrestricted demo tables (~42 MB), SQLite | Publisher hashes, integrity, foreign keys and source separation |
| MIMIC -> eICU evaluation | Implemented | Source model/threshold frozen; exploratory demo cohort |
| eICU -> MIMIC evaluation | Implemented | Default prefers larger eICU independently of test scores |
| Hospital holdouts | Fixed logistic baseline | Separate from deployed model; small hospitals may be insufficient |
| Manual/CSV/.bat results | Implemented | manual, manual --advanced, CSV, JSON and demo.bat |
| FastAPI handoff | Implemented | OpenAPI, search, bounded batches, history, readiness, CORS, optional key |
| No frontend | Respected | No dashboard, registration or role UI built |
| README and answer.txt | Updated | Commands, integration decisions and limitations |
| Extensive checks | Clinical, temporal, split, artifact, API, raw data and launcher checks | verify.bat --http; machine-readable reports |

## Limits that cannot be honestly completed using these demos

Clinical utility in every hospital, prevention of kidney failure/death, a fresh
untouched external validation, full research cohorts without approved access,
active drug features without reliable harmonization, prospective safety, and
a hospital's live EHR connection remain outside what this demo establishes.

The working model/backend is available. Receiving context fields is not presented
as proof they affect risk. See MODEL_CARD.md and reports/LOGIC_AUDIT.md.

[Clinical scenario tests](CLINICAL_TEST_CASES.md) explain expected outcomes and
independent reference calculations, including exact-zero urine without weight.


Additional improvement work: patient/hospital-isolated development comparisons,
fold-local patient weighting, fixed probability blends and an optional stricter
source-calibrated alert policy. No unsupported treatment field was activated.
See ../reports/IMPROVEMENTS.md for accepted/rejected changes and missed-window costs.
