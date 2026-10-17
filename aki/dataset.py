"""Incident observed-sample AKI outcomes; availability-safe features and censoring."""

import json
from collections import Counter

import pandas as pd

from .clinical import assess, creatinine_events
from .config import DATA, REPORTS
from .features import build_features, quality
from .storage import connect, load_stay


def observed_endpoint(patient, rows, duration):
    events = creatinine_events(patient, rows, min(duration, 8760))
    return (
        min(events, key=lambda e: (e["measurement_hour"], e["documented_hour"]))
        if events
        else None
    )


def label_window(rows, duration, hour, endpoint):
    """Return (label or None, reason). Never call an already drawn sample future AKI."""
    onset = endpoint["measurement_hour"] if endpoint else None
    rrt = [r.hour for r in rows if r.rrt == 1]
    history = [r.available_hour for r in rows if r.dialysis_history == 1]
    stop = min(rrt + history) if rrt or history else None
    if onset is not None and onset <= hour:
        return None, "aki_sample_already_collected"
    if stop is not None and stop <= hour:
        return None, "prior_rrt_or_dialysis"
    # RRT can alter creatinine; do not label a post-intervention decline as no AKI.
    if stop is not None and stop <= hour + 24 and (onset is None or stop < onset):
        return None, "rrt_before_observed_outcome"
    if onset is not None and hour < onset <= hour + 24:
        return 1, "positive"
    late_sample = any(
        r.creatinine is not None
        and hour + 18 <= r.hour <= hour + 24
        and r.available_hour <= duration
        for r in rows
    )
    if duration < hour + 24 or not late_sample:
        return None, "incomplete_followup"
    return 0, "negative"


def build_dataset():
    summaries, records = {}, []
    with connect() as con:
        ids = [r[0] for r in con.execute("SELECT stay_id FROM stays ORDER BY stay_id")]
    for index, sid in enumerate(ids):
        stay = load_stay(sid)
        counts = summaries.setdefault(stay["source"], Counter())
        counts["stays_considered"] += 1
        patient, rows = stay["patient"], stay["readings"]
        if patient.chronic_dialysis:
            counts["excluded_chronic_dialysis"] += 1
            continue
        endpoint = observed_endpoint(patient, rows, stay["duration_hours"])
        usable = 0
        for hour in range(12, int(min(168, stay["duration_hours"])) + 1, 6):
            label, reason = label_window(rows, stay["duration_hours"], hour, endpoint)
            if label is None:
                counts["censored_" + reason + "_windows"] += 1
                if reason in ("aki_sample_already_collected", "prior_rrt_or_dialysis"):
                    break
                continue
            known = [r for r in rows if r.hour <= hour and r.available_hour <= hour]
            clinical = assess(patient, known, hour)
            q = quality(patient, known, hour)
            if (
                not clinical["creatinine_comparison_available"]
                or "creatinine" not in q["latest_measurements"]
                or q["latest_measurements"]["creatinine"]["age_hours"] > 24
            ):
                counts["excluded_no_recent_comparable_creatinine_windows"] += 1
                continue
            if q["available_model_inputs"] < 3:
                counts["excluded_sparse_windows"] += 1
                continue
            if not clinical["eligible_for_new_aki_forecast"]:
                counts["excluded_prevalent_aki_or_rrt_windows"] += 1
                continue
            features, _, _ = build_features(patient, known, hour)
            records.append(
                {
                    "stay_id": sid,
                    "patient_id": stay["patient_id"],
                    "hospital_id": stay["hospital_id"],
                    "source": stay["source"],
                    "at_hour": hour,
                    "label": label,
                    "onset_hour": endpoint["measurement_hour"]
                    if endpoint
                    else float("nan"),
                    "onset_documented_hour": endpoint["documented_hour"]
                    if endpoint
                    else float("nan"),
                    **features,
                }
            )
            counts["positive_windows" if label else "negative_windows"] += 1
            usable += 1
        if usable:
            counts["included_stays"] += 1
        if (index + 1) % 200 == 0:
            print(f"  cohort: {index + 1}/{len(ids)} stays processed", flush=True)
    frame = pd.DataFrame(records)
    if frame.empty:
        raise ValueError(
            "No eligible labelled windows. Check extraction and source coverage."
        )
    frame.to_csv(DATA / "features.csv.gz", index=False, compression="gzip")
    result = {k: dict(v) for k, v in summaries.items()}
    result["definition"] = {
        "population": "Adult ICU stays; first observed creatinine-defined AKI; prior AKI/dialysis/RRT excluded",
        "prediction_times": "ICU hours 12-168, every 6h",
        "horizon_hours": 24,
        "onset": "first qualifying creatinine SAMPLE measurement time, using final available corrections; not biological onset",
        "features": "Only measurements and revisions available by prediction time",
        "documentation_time": "earliest as-of qualifying result versions; stage/value reflect latest available corrections",
        "baseline": "minimum earlier measured creatinine within 7 days of the qualifying sample",
        "minimum_inputs": "Recent creatinine, valid earlier 7-day comparison, >=3 measurement groups in preceding 24h",
        "negative_label": "full 24h ICU follow-up and a creatinine sample collected in hours 18-24 of horizon",
        "rrt": "Censor if RRT begins before a future observed AKI endpoint; exclude already collected AKI samples even if not yet reported",
        "limitations": [
            "Unknown pre-admission AKI/CKD can be misclassified",
            "Intermittent testing can miss true physiologic onset",
            "Urine intervals not inferred from irregular source charting; primary outcome is creatinine-defined",
            "Discharge, death or missing late creatinine causes censoring; informative observation remains possible",
            "No prospective or clinical validation; selected source demos are not representative",
        ],
    }
    (REPORTS / "cohort.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return frame, result
