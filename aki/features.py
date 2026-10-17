"""One feature builder shared by training, CSV, terminal and API inference."""

import numpy as np

from .clinical import creatinine_history, known_readings, urine_window
from .schema import UNITS, Reading

# Robust core model deliberately omits incompletely harmonized drug/ventilation flags.
# They remain accepted, stored and displayed; no silent claim they influence this model.
MODEL_VARIABLES = [
    "creatinine",
    "bun",
    "potassium",
    "bicarbonate",
    "lactate",
    "map",
    "heart_rate",
    "spo2",
    "respiratory_rate",
    "temperature",
]

MODEL_MEASUREMENTS = [*MODEL_VARIABLES, "urine_output_ml"]


def build_features(patient, readings, at_hour):
    known = known_readings(readings, at_hour)
    if (
        patient.baseline_creatinine is not None
        and patient.baseline_hour <= at_hour
        and not any(
            r.hour == patient.baseline_hour and r.creatinine is not None for r in known
        )
    ):
        known.append(
            Reading(hour=patient.baseline_hour, creatinine=patient.baseline_creatinine)
        )
    f = {
        "age": patient.age,
        "sex_male": float(patient.sex == "male"),
        "sex_unknown": float(patient.sex == "unknown"),
        "icu_hours": min(at_hour, 168.0),
    }
    series = {}
    for name in MODEL_VARIABLES:
        points = sorted(
            {
                r.hour: getattr(r, name)
                for r in known
                if getattr(r, name) is not None and at_hour - 24 <= r.hour <= at_hour
            }.items()
        )
        series[name] = points
        f[name + "_last"] = points[-1][1] if points else np.nan
        f[name + "_age_hours"] = at_hour - points[-1][0] if points else 48.0
        for window in (6, 24):
            recent = [(t, v) for t, v in points if t >= at_hour - window]
            vals = [v for t, v in recent]
            f[f"{name}_min_{window}h"] = min(vals) if vals else np.nan
            f[f"{name}_max_{window}h"] = max(vals) if vals else np.nan
            f[f"{name}_mean_{window}h"] = float(np.mean(vals)) if vals else np.nan
            # Count is retained for quality, not model input: site ordering practices differ.
            if len({t for t, v in recent}) >= 2:
                times = np.array([t for t, v in recent], dtype=float)
                values = np.array(vals, dtype=float)
                f[f"{name}_slope_{window}h"] = float(
                    np.polyfit(times - times[0], values, 1)[0]
                )
            else:
                f[f"{name}_slope_{window}h"] = np.nan
    history = creatinine_history(patient, known, at_hour)
    latest = series["creatinine"]
    ref48 = [
        v for t, a, v in history if latest and latest[-1][0] - 48 <= t < latest[-1][0]
    ]
    ref7 = [
        v for t, a, v in history if latest and latest[-1][0] - 168 <= t < latest[-1][0]
    ]
    f["creatinine_change_48h"] = (
        latest[-1][1] - min(ref48) if latest and ref48 else np.nan
    )
    f["creatinine_ratio_7d"] = latest[-1][1] / min(ref7) if latest and ref7 else np.nan
    # Documented volume supports the model, without pretending an irregular
    # charted volume is a complete physiologic urine-output rate.
    urine_points = sorted(
        {
            r.hour: r.urine_output_ml
            for r in known
            if r.urine_output_ml is not None and at_hour - 24 <= r.hour <= at_hour
        }.items()
    )
    for window in (6, 24):
        values = [v for t, v in urine_points if at_hour - window < t <= at_hour]
        f[f"urine_output_ml_documented_{window}h"] = sum(values) if values else np.nan
    f["urine_output_ml_age_hours"] = (
        at_hour - urine_points[-1][0] if urine_points else 48.0
    )
    # Coverage-aware urine rates are used separately for current-criteria checks.
    urine = urine_window(patient, known, at_hour, 6)
    return f, series, urine


def quality(patient, readings, at_hour):
    known = known_readings(readings, at_hour)
    latest = {}
    for name in MODEL_MEASUREMENTS:
        points = [r for r in known if getattr(r, name) is not None]
        if points:
            row = max(points, key=lambda r: (r.hour, r.available_hour))
            latest[name] = {
                "value": getattr(row, name),
                "hour": row.hour,
                "age_hours": round(at_hour - row.hour, 3),
                "unit": UNITS[name],
            }
    recent = {name for name, row in latest.items() if row["age_hours"] <= 24}
    missing = [name for name in MODEL_MEASUREMENTS if name not in recent]
    stale = [
        name
        for name, row in latest.items()
        if row["age_hours"]
        > (
            6
            if name in ("map", "heart_rate", "spo2", "respiratory_rate", "temperature")
            else 24
        )
    ]
    warnings = []
    if "creatinine" not in latest or latest["creatinine"]["age_hours"] > 24:
        warnings.append("No creatinine result available in the past 24 hours")
    history = creatinine_history(patient, known, at_hour)
    latest_creatinine = max(history, key=lambda x: x[0]) if history else None
    if not any(
        latest_creatinine and latest_creatinine[0] - 168 <= t < latest_creatinine[0]
        for t, a, v in history
    ):
        warnings.append(
            "No earlier creatinine within 7 days of latest sample; existing AKI may be missed"
        )
    if missing:
        warnings.append("Missing inputs in past 24h: " + ", ".join(missing))
    if stale:
        warnings.append("Old measurements: " + ", ".join(stale))
    return {
        "available_model_inputs": len(recent),
        "coverage_window_hours": 24,
        "total_model_inputs": len(MODEL_MEASUREMENTS),
        "missing_inputs": missing,
        "stale_inputs": stale,
        "latest_measurements": latest,
        "warnings": warnings,
    }
