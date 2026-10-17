"""Refresh disclosed retrospective illustrations from frozen internal audit patients."""

import pandas as pd

from .artifacts import atomic_json
from .config import ROOT
from .schema import PredictionRequest
from .service import model_info, run_prediction
from .storage import load_stay


def refresh_cases():
    model = model_info()
    threshold = model["alert_threshold"]
    source = model["training_source"]
    release = "eicu-crd-demo/2.0.1" if source == "eicu" else "mimic-iv-demo/2.2"
    frame = pd.read_csv(
        ROOT / f"reports/{source}_internal_predictions.csv"
    ).sort_values(["stay_id", "at_hour"])
    # Preserve the originally selected success if it remains eligible and detected.
    preferred = frame[(frame.stay_id == "eicu-2361839") & (frame.at_hour == 150)]
    success = preferred[
        (preferred.label == 1) & (preferred.predicted_risk >= threshold)
    ]
    if success.empty:
        success = frame[
            (frame.label == 1)
            & (frame.predicted_risk >= threshold)
            & (frame.onset_hour - frame.at_hour >= 18)
        ]
    cases = {
        "real_patient": (
            success,
            "Preserved prior successful illustration when still eligible; otherwise first detected positive with >=18h sample lead. Selected using outcomes, not representative.",
        ),
        "missed_case": (
            frame[(frame.label == 1) & (frame.predicted_risk < threshold)],
            "First positive window without an alert, sorted by stay/time. This is a missed EARLY WINDOW, not necessarily a completely missed AKI episode; a later alert may occur.",
        ),
        "false_alert": (
            frame[(frame.label == 0) & (frame.predicted_risk >= threshold)],
            "First false-positive evaluated window sorted by stay/time. Full follow-up and late creatinine support no observed qualifying AKI within this horizon.",
        ),
    }
    results = []
    manifest = {"model_sha256": model["model_sha256"], "cases": {}}
    for name, (selected, policy) in cases.items():
        if selected.empty:
            manifest["cases"][name] = {
                "available": False,
                "reason": "No qualifying illustration in this model's internal audit predictions",
            }
            continue
        row = selected.iloc[0]
        stay = load_stay(row.stay_id, float(row.at_hour))
        body = PredictionRequest(
            patient=stay["patient"],
            at_hour=float(row.at_hour),
            readings=stay["readings"],
        )
        result = run_prediction(body)
        if result["status"] != "predicted":
            raise AssertionError(
                "Selected training window is not reproducible at inference"
            )
        outcome = {
            "observed_aki_within_24h": bool(row.label),
            "creatinine_aki_measurement_hour": float(row.onset_hour)
            if pd.notna(row.onset_hour)
            else None,
            "creatinine_aki_documented_hour": float(row.onset_documented_hour)
            if pd.notna(row.onset_documented_hour)
            else None,
            "hours_after_prediction": float(row.onset_hour - row.at_hour)
            if pd.notna(row.onset_hour)
            else None,
        }
        provenance = {
            "source": release,
            "source_url": f"https://physionet.org/content/{release}/",
            "license": "Open Data Commons Open Database License 1.0",
            "stay_id": row.stay_id,
            "patient_id": row.patient_id,
            "at_hour": float(row.at_hour),
            "partition": f"Preserved patient-disjoint {source} internal audit set, previously inspected",
            "selection": policy,
            "retrospective_outcome": outcome,
            "request_file": f"examples/{name}.json",
            "note": "Future outcome is separate from, and never included in, prediction inputs. An illustration is not an overall performance estimate.",
            "model_sha256": model["model_sha256"],
        }
        for path, value in (
            (ROOT / f"examples/{name}.json", body.model_dump(exclude_none=True)),
            (ROOT / f"examples/{name}_provenance.json", provenance),
            (ROOT / f"reports/{name}_prediction.json", result),
        ):
            atomic_json(path, value)
        manifest["cases"][name] = {"available": True}
        results.append(
            {
                "case": name,
                "stay_id": row.stay_id,
                "at_hour": float(row.at_hour),
                "risk_percent": result["predicted_risk_percent"],
                "alert": result["alert"],
                **outcome,
            }
        )
    atomic_json(ROOT / "examples/case_manifest.json", manifest)
    return results
