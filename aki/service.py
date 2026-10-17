"""Shared prediction service: API/CLI results are identical."""

import hashlib
import io
import json
import math
import pickle
from functools import lru_cache

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from . import __version__
from .alerting import prediction_alert_options
from .clinical import assess
from .config import MODEL_PATH, REPORTS
from .features import MODEL_MEASUREMENTS, build_features, quality
from .robustness import input_variants, scorable_features
from .schema import RANGES, Patient, PredictionRequest
from .train import predict


@lru_cache(maxsize=2)
def _load_model_snapshot(path_string, modified_ns, size):
    del modified_ns, size
    try:
        from pathlib import Path

        payload = Path(path_string).read_bytes()
        bundle = joblib.load(io.BytesIO(payload))
        if bundle["metadata"]["model_version"] != __version__:
            raise ValueError("Model version differs from code; run prepare --force")
        if (
            not bundle["features"]
            or len(bundle["features"]) != bundle["estimator"].n_features_in_
        ):
            raise ValueError("Model feature shape is inconsistent; rerun prepare")
        bundle["_artifact_sha256"] = hashlib.sha256(payload).hexdigest()
        return bundle
    except (
        OSError,
        ValueError,
        KeyError,
        AttributeError,
        TypeError,
        IndexError,
        ModuleNotFoundError,
        EOFError,
        pickle.UnpicklingError,
    ) as exc:
        raise FileNotFoundError(f"Model unavailable: {exc}") from exc


def load_model():
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(
            "Model not trained yet. Run setup.bat or python -m aki prepare."
        )
    stat = MODEL_PATH.stat()
    return _load_model_snapshot(
        str(MODEL_PATH.resolve()), stat.st_mtime_ns, stat.st_size
    )


load_model.cache_clear = _load_model_snapshot.cache_clear


def model_info():
    bundle = load_model()
    metadata = {k: v for k, v in bundle["metadata"].items() if k != "split_patients"}
    criteria = {
        "weight_kg",
        "urine_interval_hours",
        "rrt",
        "dialysis_history",
        "chronic_dialysis",
    }
    active = {*MODEL_MEASUREMENTS, "age", "sex", "baseline_creatinine", "baseline_hour"}
    accepted = set(RANGES) | set(Patient.model_fields) | {"urine_interval_hours"}
    context = sorted(accepted - criteria - active)
    return {
        **metadata,
        "context_only_inputs": context,
        "input_usage": {
            "active_model_inputs": sorted(active),
            "criteria_or_eligibility_inputs": sorted(criteria),
            "context_only_inputs": context,
            "timing_fields": ["hour", "available_hour", "at_hour"],
        },
        "feature_count": len(bundle["features"]),
        "feature_names": bundle["features"],
        "model_sha256": bundle["_artifact_sha256"],
    }


def contributions(bundle, x, probability):
    groups = [*MODEL_MEASUREMENTS, "age", "sex", "icu_hours"]
    perturbed = []
    names = []
    for group in groups:
        indexes = [
            i
            for i, name in enumerate(bundle["features"])
            if name == group or name.startswith(group + "_")
        ]
        measured_indexes = [
            i for i in indexes if not bundle["features"][i].endswith("_age_hours")
        ]
        if not measured_indexes or not any(
            math.isfinite(x[i]) for i in measured_indexes
        ):
            continue
        row = x.copy()
        for index in indexes:
            row[index] = bundle["reference_medians"][bundle["features"][index]]
        perturbed.append(row)
        names.append(group)
    if not perturbed:
        return []
    probabilities = predict(bundle, np.asarray(perturbed, float))
    values = [
        {
            "measurement": name,
            "contribution_percentage_points": round((probability - float(p)) * 100, 3),
            "direction": "increases_model_risk"
            if probability > p
            else "decreases_model_risk",
        }
        for name, p in zip(names, probabilities)
    ]
    return sorted(
        values, key=lambda row: abs(row["contribution_percentage_points"]), reverse=True
    )[:5]


def sensitivity_diagnostic(bundle, patient, readings, at_hour, probability):
    variants, descriptors = [], []
    skipped = 0
    clinical_boundary = False
    for kind, name, rows in input_variants(patient, readings, at_hour):
        features = scorable_features(patient, rows, at_hour)
        if features is None:
            skipped += 1
            if (
                kind == "creatinine"
                and not assess(patient, rows, at_hour)["eligible_for_new_aki_forecast"]
            ):
                clinical_boundary = True
            continue
        variants.append([features.get(f, np.nan) for f in bundle["features"]])
        descriptors.append((kind, name))
    estimates = predict(bundle, np.asarray(variants, float)) if variants else []
    threshold = bundle["metadata"]["alert_threshold"]
    bounds = {}
    for kind in ("creatinine", "missing_group"):
        values = [
            probability,
            *[float(p) for (k, _), p in zip(descriptors, estimates) if k == kind],
        ]
        low, high = min(values), max(values)
        bounds[kind] = {
            "minimum_risk_percent": round(low * 100, 2),
            "maximum_risk_percent": round(high * 100, 2),
            "crosses_alert_threshold": low < threshold <= high,
            "maximum_change_percentage_points": round(
                max(abs(v - probability) for v in values) * 100, 2
            ),
        }
    threshold_sensitive = any(v["crosses_alert_threshold"] for v in bounds.values())
    large_change = any(
        v["maximum_change_percentage_points"] >= 10 for v in bounds.values()
    )
    review = clinical_boundary or threshold_sensitive or large_change
    return {
        "status": "sensitive"
        if review
        else "threshold_consistent_under_tested_changes",
        "threshold_sensitive": threshold_sensitive,
        "large_score_change": large_change,
        "large_change_policy_percentage_points": 10,
        "review_required": review,
        "creatinine_stress_mg_dl": 0.04,
        "clinical_boundary_sensitive": clinical_boundary,
        "tested_variants": len(variants),
        "unscorable_variants": skipped,
        "ranges": bounds,
        "meaning": "Input-sensitivity diagnostic only: latest creatinine +/-0.04 mg/dL or one measured group removed. Ranges are not confidence intervals or bounds on true clinical risk.",
    }


def run_prediction(request: PredictionRequest):
    bundle = load_model()
    patient, readings, t = request.patient, request.readings, request.at_hour
    clinical = assess(patient, readings, t)
    completeness = quality(patient, readings, t)
    if (
        "urine_output_ml" in completeness["latest_measurements"]
        and clinical["urine_stage"] is None
    ):
        completeness["warnings"].append(
            "Current urine-output criteria are unknown: complete collection intervals are required; positive-volume rates also require an available weight."
        )
    features, _series, _urine = build_features(patient, readings, t)
    result = {
        "at_hour": t,
        "target": "new creatinine-defined AKI within the next 24 hours",
        "horizon_hours": 24,
        "status": None,
        "predicted_risk": None,
        "predicted_risk_percent": None,
        "risk_category": None,
        "alert": False,
        "alert_options": {},
        "alert_threshold": bundle["metadata"]["alert_threshold"],
        "clinical_assessment": clinical,
        "data_quality": completeness,
        "model_contributions": [],
        "input_sensitivity": None,
        "model": {
            "version": bundle["metadata"]["model_version"],
            "training_source": bundle["metadata"]["training_source"],
            "data_scope": bundle["metadata"]["data_scope"],
            "algorithm": bundle["metadata"]["selected_algorithm"]["name"],
            "validation_status": bundle["metadata"]["status"],
            "calibration": bundle["metadata"]["calibration"],
            "explanation_method": bundle["metadata"]["explanation_method"],
        },
        "notice": "Research demo risk estimate; not a validated clinical probability or treatment recommendation.",
        "lead_time_note": "A next-24h forecast does not establish 24h of advance warning.",
    }
    if not clinical["eligible_for_new_aki_forecast"]:
        result["status"] = (
            "outside_new_aki_cohort"
            if clinical["dialysis_history_observed"] or clinical["rrt_observed"]
            else "aki_already_observed"
        )
        return result
    if not 12 <= t <= 168:
        result["status"] = "outside_new_aki_cohort"
        result["data_quality"]["warnings"].append(
            "The initial model is trained for ICU hours 12-168 only"
        )
        return result
    if (
        not clinical["creatinine_comparison_available"]
        or "creatinine" not in completeness["latest_measurements"]
        or completeness["latest_measurements"]["creatinine"]["age_hours"] > 24
        or completeness["available_model_inputs"] < 3
    ):
        result["status"] = "insufficient_data"
        result["data_quality"]["warnings"].append(
            "Requires recent creatinine, an earlier 7-day comparison, and at least 3 measurement groups in the past 24h"
        )
        return result
    x = np.asarray([features.get(name, np.nan) for name in bundle["features"]], float)
    with threadpool_limits(limits=2):
        probability = float(predict(bundle, x.reshape(1, -1))[0])
        result["model_contributions"] = contributions(bundle, x, probability)
        result["input_sensitivity"] = sensitivity_diagnostic(
            bundle, patient, readings, t, probability
        )
    threshold = bundle["metadata"]["alert_threshold"]
    if result["input_sensitivity"]["review_required"]:
        result["data_quality"]["warnings"].append(
            "Prediction is sensitive to small input changes or missing measurements; review the sensitivity diagnostic."
        )
    result.update(
        {
            "status": "predicted",
            "predicted_risk": round(probability, 6),
            "predicted_risk_percent": round(probability * 100, 2),
            "alert": probability >= threshold,
            "alert_options": prediction_alert_options(probability, bundle),
            "risk_category": "high"
            if probability >= threshold
            else "moderate"
            if probability >= threshold / 2
            else "low",
        }
    )
    return result


def evaluation():
    path = REPORTS / "evaluation.json"
    if not path.exists():
        raise FileNotFoundError("Evaluation report not created yet")
    return json.loads(path.read_text(encoding="utf-8"))


def prediction_history(body):
    results = []
    for hour in range(12, int(min(body.at_hour, 168)) + 1, 6):
        known = [
            r for r in body.readings if r.hour <= hour and r.available_hour <= hour
        ]
        if not known:
            results.append(
                {
                    "at_hour": hour,
                    "status": "insufficient_data",
                    "predicted_risk": None,
                    "predicted_risk_percent": None,
                    "alert": False,
                    "risk_category": None,
                    "review_required": False,
                }
            )
            continue
        patient = body.patient
        if patient.baseline_hour is not None and patient.baseline_hour > hour:
            patient = patient.model_copy(
                update={"baseline_creatinine": None, "baseline_hour": None}
            )
        result = run_prediction(
            PredictionRequest(patient=patient, at_hour=hour, readings=known)
        )
        results.append(
            {
                **{
                    k: result[k]
                    for k in (
                        "at_hour",
                        "status",
                        "predicted_risk",
                        "predicted_risk_percent",
                        "risk_category",
                        "alert",
                    )
                },
                "review_required": bool(
                    result["input_sensitivity"]
                    and result["input_sensitivity"]["review_required"]
                ),
            }
        )
    return {
        "through_hour": min(body.at_hour, 168),
        "prediction_interval_hours": 6,
        "items": results,
        "notice": "Each point uses only information available at its own hour; no future outcome is included.",
    }
