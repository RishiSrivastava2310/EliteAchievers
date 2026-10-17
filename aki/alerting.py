"""Source-calibration-only alert tradeoffs; risk estimates remain unchanged."""

import hashlib
import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .artifacts import atomic_json
from .config import DATA, MODEL_PATH, REPORTS
from .train import evaluate, metric_values, predict

PROFILE_PATH = REPORTS / "alert_profiles.json"


def build_profile_specs(calibration, probabilities, default_threshold):
    if (
        not isinstance(default_threshold, (float, int))
        or not 0 <= default_threshold <= 1
    ):
        raise ValueError("Invalid default threshold")
    probabilities = np.asarray(probabilities, float)
    if len(probabilities) != len(calibration) or not np.isfinite(probabilities).all():
        raise ValueError("Invalid calibration probabilities")
    if np.any((probabilities < 0) | (probabilities > 1)):
        raise ValueError("Calibration probabilities must be between zero and one")
    profiles = {
        "standard": {
            "threshold": float(default_threshold),
            "selection": "Existing frozen source-calibration threshold; unchanged.",
            "calibration": metric_values(
                calibration.label, probabilities, default_threshold
            ),
        }
    }
    class_patients = calibration.groupby("patient_id").label.max().value_counts()
    if len(class_patients) < 2 or class_patients.min() < 5:
        return (
            profiles,
            "Fewer-alert policy unavailable: fewer than five calibration patients per outcome class.",
        )
    candidates = []
    for threshold in np.unique(probabilities):
        if threshold <= default_threshold:
            continue
        metrics = metric_values(calibration.label, probabilities, threshold)
        if metrics["sensitivity"] is not None and metrics["sensitivity"] >= 0.70:
            candidates.append((metrics["precision"] or 0, float(threshold), metrics))
    if candidates:
        _, threshold, metrics = max(candidates, key=lambda row: (row[0], row[1]))
        profiles["fewer_alerts"] = {
            "threshold": threshold,
            "selection": "Source calibration only: maximize window precision at sensitivity >=0.70, with threshold strictly above standard. Ties favor the higher threshold.",
            "calibration": metrics,
            "tradeoff": "Fewer alerts can mean more missed AKI. The 70% sensitivity floor is a demo policy on source calibration, not a guarantee externally.",
        }
        return profiles, "available"
    return profiles, "No distinct higher threshold meets the source-calibration policy."


def refresh_alert_profiles():
    bundle = joblib.load(MODEL_PATH)
    model_hash = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    metadata, features = bundle["metadata"], bundle["features"]
    frame = pd.read_csv(DATA / "features.csv.gz")
    source = metadata["training_source"]
    source_rows = frame[frame.source == source]
    groups = metadata["split_patients"]
    cal = source_rows[source_rows.patient_id.isin(groups["calibration"])]
    assert not set(cal.patient_id) & (set(groups["development"]) | set(groups["test"]))
    protocol = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "model_sha256": model_hash,
        "threshold_selection": "Source calibration only; preserve standard and compare one prespecified stricter profile with >=0.70 source-calibration window sensitivity.",
        "external_policy": "Freeze both thresholds before evaluating internal or opposite-source audit outcomes. Do not select profiles from those results.",
        "default_policy_changed": False,
        "note": "Previously inspected demo audit sets, not fresh validation.",
    }
    atomic_json(REPORTS / "alert_profile_protocol.json", protocol)
    with threadpool_limits(limits=2):
        profiles, status = build_profile_specs(
            cal,
            predict(bundle, cal[features].to_numpy(float)),
            metadata["alert_threshold"],
        )
        # Threshold choices are complete before any internal/external labels are evaluated.
        internal = source_rows[source_rows.patient_id.isin(groups["test"])]
        sets = {
            "internal": internal,
            **{
                s: frame[frame.source == s]
                for s in sorted(set(frame.source) - {source})
            },
        }
        for name, group in sets.items():
            p = predict(bundle, group[features].to_numpy(float))
            for profile in profiles.values():
                profile.setdefault("audit_evaluation", {})[name] = evaluate(
                    group, p, profile["threshold"], bootstrap=False
                )
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "model_sha256": model_hash,
        "training_source": source,
        "default_profile": "standard",
        "status": status,
        "profiles": profiles,
        "default_policy_changed": False,
        "risk_estimates_changed": False,
        "note": "Both outputs are demo alert policies on the same risk score. A stricter threshold is not a more accurate risk model. Evaluations use correlated windows and previously inspected audit sets.",
    }
    atomic_json(PROFILE_PATH, report)
    return report


@lru_cache(maxsize=2)
def _read_profiles(path, modified_ns, size):
    del modified_ns, size
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_alert_profiles(model_hash):
    try:
        stat = PROFILE_PATH.stat()
        report = _read_profiles(str(PROFILE_PATH), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError) as exc:
        raise FileNotFoundError(
            "Alert profiles unavailable; run prepare to refresh them."
        ) from exc
    if not isinstance(report, dict) or report.get("model_sha256") != model_hash:
        raise FileNotFoundError(
            "Alert profiles belong to another model; run prepare to refresh them."
        )
    profiles = report.get("profiles")
    if not isinstance(profiles, dict) or "standard" not in profiles:
        raise FileNotFoundError("Missing standard alert profile; run prepare.")
    for profile in profiles.values():
        threshold = profile.get("threshold") if isinstance(profile, dict) else None
        if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
            raise FileNotFoundError("Invalid alert-profile threshold; run prepare.")
    return report


def prediction_alert_options(probability, bundle):
    standard = bundle["metadata"]["alert_threshold"]
    result = {"standard": {"threshold": standard, "alert": probability >= standard}}
    try:
        report = read_alert_profiles(bundle["_artifact_sha256"])
        extra = report["profiles"].get("fewer_alerts")
        if extra and extra["threshold"] > standard:
            result["fewer_alerts"] = {
                "threshold": extra["threshold"],
                "alert": probability >= extra["threshold"],
                "tradeoff": extra["tradeoff"],
            }
    except (FileNotFoundError, KeyError, TypeError):
        # Missing optional policy must not stop an otherwise valid standard forecast.
        pass
    return result
