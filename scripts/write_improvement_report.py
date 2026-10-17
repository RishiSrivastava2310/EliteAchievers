"""Summarize the bounded model study and the explicit alert tradeoff."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aki.alerting import read_alert_profiles
from aki.artifacts import atomic_json
from aki.service import model_info
from aki.storage import connect


def main():
    info = model_info()
    profiles = read_alert_profiles(info["model_sha256"])
    study_path = ROOT / "reports/improvement_study.json"
    study = json.loads(study_path.read_text()) if study_path.exists() else {}
    current_study = study.get("model_sha256") == info["model_sha256"]
    with connect() as con:
        admission = pd.read_sql_query(
            "SELECT source,json_extract(patient_json,'$.admission_type') AS admission_type,count(*) AS stays FROM stays GROUP BY source,admission_type",
            con,
        ).to_dict("records")
        context = pd.read_sql_query(
            "SELECT s.source,o.variable,count(*) AS rows,count(DISTINCT o.stay_id) AS stays FROM observations o JOIN stays s ON s.stay_id=o.stay_id WHERE variable IN ('ventilation','vasopressor','diuretic','nephrotoxic_drug') GROUP BY s.source,o.variable",
            con,
        ).to_dict("records")
    reasons = {
        "medication": "eICU orders and infusion records are currently merged into one flag, unlike MIMIC administration sources. Orders are not proof of administration. Missing entries are not confirmed non-exposure.",
        "ventilation": "Positive procedure/treatment mentions lack a harmonized current on/off interval and verified absence. A past mention is not proof of ventilation at prediction time.",
        "admission_type": "eICU unitadmitsource is a location (ED/floor/OR), whereas MIMIC admission_type describes admission urgency. Current categories are incomplete and not equivalent.",
    }
    atomic_json(
        ROOT / "reports/input_support_audit.json",
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "model_sha256": info["model_sha256"],
            "admission_counts": admission,
            "context_counts": context,
            "decisions": reasons,
            "context_fields_activated": False,
            "note": "Counts describe documentation, not confirmed absence or current treatment.",
        },
    )
    rows = []
    if current_study:
        for candidate in study["candidates"]:
            patient = candidate["scores"]["patient"]["mean"]
            hospital = candidate["scores"]["hospital"]["mean"]
            score = (patient["selection_score"] + hospital["selection_score"]) / 2
            rows.append(
                f"| {candidate['config']['name']} | {patient['auprc']:.3f} | {hospital['auprc']:.3f} | {score:.3f} |"
            )
    alert_rows = []
    for name, profile in profiles["profiles"].items():
        for target, metrics in profile["audit_evaluation"].items():
            confusion = metrics["confusion"]
            alert_rows.append(
                f"| {name} | {target} | {profile['threshold']:.2%} | {confusion['tp']} | {confusion['fp']} | {confusion['fn']} | {metrics['sensitivity']:.1%} | {metrics['precision']:.1%} |"
            )
    decision = (
        f"Qualified challenger: {study['qualified_candidate'] or 'none; retain the incumbent'}."
        if current_study
        else "No current-model qualification study is available; rerun qualify_improvements.py."
    )
    text = f"""# Improvement study and alert tradeoff

The deployed risk model and standard alert policy are unchanged. Five additional
challengers were compared with the incumbent using source development patients
only. This study is current for the deployed artifact: **{current_study}**.
{decision}

## Bounded model comparison

Three folds isolate patients; three additional folds isolate hospitals and purge
every held-hospital patient's other stays from fitting data. The current study
uses {study.get("development_patients", "unavailable")} development patients,
{study.get("development_hospitals", "unavailable")} hospitals and
{study.get("development_windows", "unavailable")} correlated windows.
These are previously used development data, not an untouched external evaluation.

| Configuration | Patient-fold AUPRC | Hospital-fold AUPRC | Combined selection score |
|---|---:|---:|---:|
{chr(10).join(rows)}

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
{chr(10).join(alert_rows)}

These are repeated prediction windows, not unique patients or alarms in a live
workflow. Fewer alerts can miss more AKI. Previously inspected audit outcomes
remain exploratory; profile comparison does not establish prospective utility.
Missing/stale optional profiles fall back to the standard forecast, while the
profile-report endpoint returns 503 until profiles are refreshed.

## Inputs left as context after source review

- Medication: {reasons["medication"]}
- Ventilation: {reasons["ventilation"]}
- Admission: {reasons["admission_type"]}

Documentation counts are retained in input_support_audit.json. Activating these
flags without fixing their meaning and timing would add unsupported certainty.
A future administration adapter needs separate provenance, confirmed start/stop
knowledge and unknown-versus-absent handling before development-only evaluation.

References: [official eICU medication semantics](https://eicu.mit.edu/eicutables/medication/),
[eICU patient/admission columns](https://eicu.mit.edu/eicutables/patient/),
[group-isolated validation](https://scikit-learn.org/1.8/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html),
[boosted-tree sample weights](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html).

Reproduce with .venv\\Scripts\\python.exe scripts\\qualify_improvements.py.
Refresh policies without retraining with scripts\\refresh_alert_profiles.py;
prepare/train also refreshes them automatically. Run verify.bat --http for regression
and live API checks. Larger approved cohorts, clinician-reviewed labels and
prospective evaluation remain necessary to establish clinical reliability.
"""
    (ROOT / "reports/IMPROVEMENTS.md").write_text(text, encoding="utf-8")
    print("Improvement report and input-support audit refreshed.")


if __name__ == "__main__":
    main()
