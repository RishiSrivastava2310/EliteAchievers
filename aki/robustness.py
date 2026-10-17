"""Rebuild real-time features under explicit engineering stress assumptions."""

import numpy as np
import pandas as pd

from .clinical import assess, known_readings
from .config import SEED
from .features import MODEL_MEASUREMENTS, build_features, quality

CREATININE_STRESS_MG_DL = 0.04


def input_variants(patient, readings, at_hour):
    known = known_readings(readings, at_hour)
    labs = [r for r in known if r.creatinine is not None]
    if labs:
        latest = max(labs, key=lambda r: (r.hour, r.available_hour))
        for delta in (-CREATININE_STRESS_MG_DL, CREATININE_STRESS_MG_DL):
            value = latest.creatinine + delta
            if not 0.1 <= value <= 30:
                continue
            rows = [
                r.model_copy(update={"creatinine": value}) if r is latest else r
                for r in known
            ]
            yield "creatinine", f"latest_creatinine_{delta:+.2f}_mg_dl", rows
    for name in MODEL_MEASUREMENTS:
        if name == "creatinine" or not any(
            getattr(r, name) is not None and r.hour >= at_hour - 24 for r in known
        ):
            continue
        changes = {name: None}
        if name == "urine_output_ml":
            changes["urine_interval_hours"] = None
        yield (
            "missing_group",
            f"omit_{name}",
            [r.model_copy(update=changes) for r in known],
        )


def scorable_features(patient, readings, at_hour):
    clinical = assess(patient, readings, at_hour)
    q = quality(patient, readings, at_hour)
    if (
        not clinical["eligible_for_new_aki_forecast"]
        or not clinical["creatinine_comparison_available"]
        or q["available_model_inputs"] < 3
        or "creatinine" not in q["latest_measurements"]
        or q["latest_measurements"]["creatinine"]["age_hours"] > 24
    ):
        return None
    return build_features(patient, readings, at_hour)[0]


def development_stress_cases(frame, limit=90):
    """Only supplied development patients are read, one window per sampled patient."""
    from .storage import load_stay

    selected = (
        frame.sample(frac=1, random_state=SEED)
        .drop_duplicates("patient_id")
        .head(limit)
    )
    records = []
    for index, row in selected.iterrows():
        stay = load_stay(row.stay_id, float(row.at_hour))
        for kind, name, readings in input_variants(
            stay["patient"], stay["readings"], row.at_hour
        ):
            features = scorable_features(stay["patient"], readings, row.at_hour)
            if features is not None:
                records.append(
                    {
                        "base_index": index,
                        "patient_id": row.patient_id,
                        "stress_kind": kind,
                        "scenario": name,
                        **features,
                    }
                )
    return pd.DataFrame(records)


def stress_statistics(stress, features, predict_fn, base_probabilities):
    if stress.empty:
        return {
            "creatinine_p95_delta": 0.0,
            "missing_group_p95_delta": 0.0,
            "variants": 0,
        }
    p = predict_fn(stress[features].to_numpy(float))
    base = np.array([base_probabilities[int(i)] for i in stress.base_index])
    delta = np.abs(p - base)
    result = {"variants": len(stress)}
    for kind in ("creatinine", "missing_group"):
        values = delta[stress.stress_kind.to_numpy() == kind]
        result[kind + "_p95_delta"] = (
            float(np.quantile(values, 0.95)) if len(values) else 0.0
        )
    return result


def group_dropout(x, y, features, enabled=False):
    """Derived training copies only; never applied to calibration/test labels."""
    if not enabled:
        return x, y
    rng = np.random.default_rng(SEED)
    altered = np.array(x, copy=True)
    groups = [name for name in MODEL_MEASUREMENTS if name != "creatinine"]
    indexes = {
        g: [
            (i, name.endswith("_age_hours"))
            for i, name in enumerate(features)
            if name.startswith(g + "_")
        ]
        for g in groups
    }
    for row in range(len(altered)):
        if rng.random() >= 0.5:
            continue
        group = groups[int(rng.integers(0, len(groups)))]
        for i, is_age in indexes[group]:
            altered[row, i] = 48.0 if is_age else np.nan
    return np.concatenate([x, altered]), np.concatenate([y, y])
