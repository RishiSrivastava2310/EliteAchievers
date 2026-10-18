# AKI NATOR

A working React + TypeScript ICU research frontend with Tailwind CSS, Radix UI primitives, Lucide icons and Recharts. Includes role-based sign-in/sign-up, monitoring, patient records, historical replay, distinct AKI recognition and future-prediction interfaces, CSV/manual input, alerts, evaluation screens and a typed FastAPI adapter.

The interface follows the supplied AKI NATOR references: a geometric AN monogram, custom wordmark, white/teal/blue palette, two-level website navigation and a wave header with a glass replay control. Typography uses the native Apple system font where available and locally bundled Inter elsewhere. Vector brand assets are in `public/aki-nator-*.svg`; shared styles are in `src/styles/`.

Interior pages use restrained coral accents inspired by [Hunter Healthcare](https://www.awwwards.com/inspiration/ui-components-hunter-healthcare), sage for historical monitoring, blue for future risk, and explicit amber/red status labels. Patient records have section shortcuts; definitions and research protocols expand on demand. The data-quality overview is calculated from the loaded observations. These refinements live in `src/styles/features.css`.

**Research prototype. Not a medical device or clinical decision system.**

## Start on Windows

Double-click **Start-AKI-NATOR.cmd**, or run:

```powershell
.\Start-AKI-NATOR.ps1
```

Open **http://127.0.0.1:5173**. The launcher uses the project-local Node runtime when available. Otherwise install Node.js 22.12+ and reopen PowerShell.

Standard commands with Node on PATH:

```powershell
npm install
npm run dev
```

If PowerShell blocks npm.ps1, use `npm.cmd` instead of `npm`.

## Local accounts

All three predefined accounts use **AkiNator!2026**:

| Role       | Email                   | Access                                                         |
| ---------- | ----------------------- | -------------------------------------------------------------- |
| Doctor     | doctor@akinator.org     | Monitoring, replay, predictions, alerts, data quality, profile |
| Researcher | researcher@akinator.org | Doctor access plus analytics and cross-hospital validation     |
| Admin      | admin@akinator.org      | Researcher access plus API connection settings                 |

Sign-up creates a Doctor account. Passwords require ten characters, uppercase, lowercase and a number. Locally created accounts use salted PBKDF2 hashes in localStorage; sessions use sessionStorage. Seed credentials are intentionally present in frontend source for offline use. **This is demonstration authentication, not a production security boundary.** The backend must enforce real authorization. No seed accounts are advertised on the login page.

## Data modes

The default `.env` has an empty `VITE_API_BASE_URL` and loads 12 completely fictional, deterministic ICU histories. IDs start with `SYN-`. Dataset source labels identify schema scenarios, not actual MIMIC/eICU records. Every illustrative risk estimate is identified as simulated; no model is trained, calibrated or validated here. Counts are computed from loaded stays. Model performance plots remain empty without backend results.

Synthetic stays and edits are in memory and reset on reload. Export a history to retain it. Account hashes, alert reviews and the display threshold are browser-local. No telemetry, external AI calls or patient-data uploads are implemented. Use synthetic data in this workspace; restricted records belong only in an approved deployment.

## Connect the backend

Copy `.env.example` to `.env` and set:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_API_TIMEOUT_MS=8000
```

Restart Vite. Alternatively, sign in as Admin and use Settings to test and save the API URL. This signs out so the next login uses backend authentication. A saved browser setting overrides `.env`; save a blank URL in Admin settings to return to local mode. Backend failures show Retry, Settings and an explicit synthetic-mode action; there is no silent fallback. The backend needs CORS for `http://127.0.0.1:5173`. See [docs/API_CONTRACT.md](docs/API_CONTRACT.md).

## Clinical and temporal behavior

- The primary source is **AKI Project Feasibility, Workload and Plan.pdf** (all five pages). The supplementary TransportAKI Hackathon Guide was not present in the supplied workspace.
- The research task is adult ICU stays ≥24h, starting forecasts at hour 12; excludes ESRD, chronic dialysis, RRT before prediction, and AKI already observed at any earlier available point.
- Both collection timestamp and `availableAt` must be at or before the selected replay time. Future measurements cannot enter recognition, completeness or the risk view. Forecasts older than six hours are unavailable.
- Recognition uses a ≥0.3 mg/dL rise inside 48h or ≥1.5× the lowest earlier available creatinine inside seven days. The admission value is naturally used when it is the only prior value within that window. Isolated high creatinine does not establish an acute change. Without enough recent measurements, status is insufficient rather than negative. Observed status records an AKI event so far; it does not assert ongoing injury or recovery.
- Urine-output recognition requires known weight and complete, normalized collection intervals. Missing intervals are not bridged. Stage 3 includes the supplied creatinine/urine criteria; dialysis excludes prediction and is not independently used to assign a recognition stage in this frontend. Clinical adjudication remains the research team's responsibility.
- Recognition references [KDIGO 2012](https://kdigo.org/wp-content/uploads/2016/10/KDIGO-2012-AKI-Guideline-English.pdf), consistent with the feasibility document. The 2026 public-review draft is not silently substituted.
- A separate retrospective overlay displays later measurements/onset and does not change the selected-time snapshot.
- Chart points use observation timestamps, explicit gaps over 12h, and no forward filling. Completeness is the fraction of nine core types measured within 12h; it is a UI freshness convention, not validated clinical adequacy.
- A forecast horizon of 24h does not guarantee 24h warning. Contributions are rendered with the backend's named method; they are not labeled SHAP by default.
- Entering or importing readings clears illustrative forecasts for that stay. This avoids implying that local data changes ran a model.

## Clinical graphs and outcomes

The 24-hour risk history preserves supplied probability precision, marks each forecast update, and offers an explicitly labeled zoomed Y-axis for small differences. The default axis stays at 0–100%. Replaying time reveals existing forecasts; it does not run a model or require risk to rise. A simulated alert marks the first illustrative forecast at or above the configured threshold. Historical forecasts remain visible when current predictions are ineligible or unavailable, with the reason shown. Real backend values are not altered to create movement.

Serum creatinine and recorded ICU fatality have separate graphs in Patient Details and Predictions. The fatality graph is also on Overview. Both follow the selected replay hour and update when local data changes.

- The creatinine line turns red and shows **Call The Doctor** when either the ≥0.3 mg/dL/48h rise or ≥1.5×/7-day rise is observed. A smaller positive rise shows **May Need Attention** in orange, with a blue line. Orange is an interface convention, not a validated clinical threshold. Insufficient comparisons remain unavailable; earlier observed criteria remain flagged in later replay.
- Fatality is **recorded ICU deaths / completed stays with known outcomes**, not an individual mortality prediction or AKI-attributable mortality. Unknown and ongoing stays are excluded; denominator coverage is shown. Outcomes must have occurred and become available. Admission-aligned hours synchronize stays in the historical cohort.
- Synthetic sample stays include explicitly fictional discharge/death outcomes and varied lengths. Try replay hours 24, 42 and 72 to see the recorded rate change. No real mortality-model results are supplied.
- Use **Record outcomes** for manual entry or a separate outcome CSV: `stay_id,status,timestamp,available_at` (availability optional). Status is `died` or `discharged_alive`. A matching template is available in the dialog. Imports update existing fictional stays atomically; invalid IDs, dates, duplicates, or outcomes preceding measurements are rejected. Entry is local synthetic mode only; backends supply optional `Patient.outcome`.

## CSV history

Use Patient Directory → Add synthetic stay → CSV history, or Add readings in an existing record. Download a template from that dialog. Required columns: `timestamp,measurement,value`. Optional: `available_at,interval_hours`. Use ISO timestamps with timezone. Measurement names are `creatinine,bun,urineOutput,map,heartRate,spo2,potassium,bicarbonate,lactate`; units appear in the interface and API contract. CSV is a simple unquoted numeric/time format, limited to 2 MB. Conflicting or duplicate stay IDs and readings outside a stay's timeline are rejected.

## Verify and build

```powershell
npm test
npm run test:e2e
npm run build
npm run preview
```

The previous launcher filenames and predefined sign-in credentials remain supported for compatibility.

Browser tests use installed Windows Chrome (override `CHROME_PATH` if needed), so no browser download is required. Tests cover authentication, roles, navigation, responsive views, patient selection, replay, future-outcome isolation, CSV/manual input, alerts, empty analytics and explicit API error handling. Unit tests cover temporal filtering, eligibility, recognition windows and CSV rejection cases.

## Structure

`src/lib` contains shared types, the centralized API client, synthetic fixtures, temporal/clinical logic, CSV parsing and workspace state. `src/components` contains reusable UI, charts, the shell, patient table and data entry. `src/pages` contains the route-level screens. `tests` contains clinical/CSV unit tests and browser workflow tests. No backend, dataset access or ML training is included.
