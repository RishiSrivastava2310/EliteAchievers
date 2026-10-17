"""Patient-separated tuning/calibration/testing and frozen cross-source evaluation."""

import hashlib
import json
import sys
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_selection import VarianceThreshold
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedGroupKFold, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler
from threadpoolctl import threadpool_limits

from . import __version__
from .artifacts import atomic_json, atomic_model
from .config import ARTIFACTS, DATA, MODEL_PATH, REPORTS, SEED
from .features import MODEL_MEASUREMENTS
from .robustness import development_stress_cases, group_dropout, stress_statistics

META = [
    "stay_id",
    "patient_id",
    "hospital_id",
    "source",
    "at_hour",
    "label",
    "onset_hour",
    "onset_documented_hour",
]
BASE_CANDIDATES = [
    {"name": "logistic_c0.01", "kind": "logistic", "C": 0.01},
    {"name": "logistic_c0.1", "kind": "logistic", "C": 0.1},
    {"name": "logistic_c1", "kind": "logistic", "C": 1.0},
    {"name": "boosted_leaf3", "kind": "hist_gradient_boosting", "max_leaf_nodes": 3},
    {"name": "boosted_leaf7", "kind": "hist_gradient_boosting", "max_leaf_nodes": 7},
    {"name": "boosted_leaf15", "kind": "hist_gradient_boosting", "max_leaf_nodes": 15},
    {
        "name": "boosted_regularized7",
        "kind": "hist_gradient_boosting",
        "max_leaf_nodes": 7,
        "min_samples_leaf": 40,
        "l2_regularization": 10,
    },
]
CANDIDATES = [
    {**c, "name": c["name"] + "_" + representation, "feature_set": representation}
    for representation in ("full", "lean")
    for c in BASE_CANDIDATES
]
CANDIDATES += [
    {"name": f"spline_c{c}_lean", "kind": "spline", "C": c, "feature_set": "lean"}
    for c in (0.01, 0.1, 1.0)
]
CANDIDATES += [
    {
        "name": f"dropout_boosted_{representation}",
        "kind": "hist_gradient_boosting",
        "max_leaf_nodes": 7,
        "min_samples_leaf": 40,
        "l2_regularization": 10,
        "feature_set": representation,
        "group_dropout": True,
    }
    for representation in ("full", "lean")
]
CANDIDATES.append(
    {
        "name": "dropout_spline_c0.1_lean",
        "kind": "spline",
        "C": 0.1,
        "feature_set": "lean",
        "group_dropout": True,
    }
)


def select_features(features, config):
    if config.get("feature_set") != "lean":
        return features
    return [
        f
        for f in features
        if f
        in (
            "age",
            "sex_male",
            "sex_unknown",
            "icu_hours",
            "creatinine_change_48h",
            "creatinine_ratio_7d",
            "urine_output_ml_documented_24h",
        )
        or f.endswith(("_last", "_age_hours", "_slope_24h"))
    ]


def model_for(config):
    if config["kind"] == "spline":
        return make_pipeline(
            SimpleImputer(strategy="median", keep_empty_features=True),
            VarianceThreshold(),
            SplineTransformer(
                n_knots=3,
                degree=2,
                knots="uniform",
                extrapolation="constant",
                include_bias=False,
            ),
            StandardScaler(),
            LogisticRegression(C=config["C"], max_iter=2000, random_state=SEED),
        )
    if config["kind"] == "logistic":
        return make_pipeline(
            SimpleImputer(
                strategy="median", add_indicator=True, keep_empty_features=True
            ),
            StandardScaler(),
            LogisticRegression(C=config["C"], max_iter=1500, random_state=SEED),
        )
    return HistGradientBoostingClassifier(
        max_iter=120,
        learning_rate=0.06,
        max_leaf_nodes=config["max_leaf_nodes"],
        min_samples_leaf=config.get("min_samples_leaf", 20),
        l2_regularization=config.get("l2_regularization", 3),
        early_stopping=False,
        random_state=SEED,
    )


def grouped_split(frame, source=None):
    frozen_path = REPORTS / "frozen_patient_splits.json"
    if source and frozen_path.exists():
        groups = json.loads(frozen_path.read_text(encoding="utf-8"))[source]
        held = set(groups["calibration"]) | set(groups["test"])
        masks = [
            ~frame.patient_id.isin(held),
            frame.patient_id.isin(groups["calibration"]),
            frame.patient_id.isin(groups["test"]),
        ]
        parts = [frame[mask].copy() for mask in masks]
        if any(p.label.nunique() < 2 for p in parts):
            raise ValueError(
                "A frozen patient partition has insufficient outcome classes"
            )
        return parts
    patients = frame.groupby("patient_id").label.max()
    if patients.nunique() < 2 or patients.value_counts().min() < 4:
        raise ValueError(
            "Need at least four positive and four negative patients for separated development/calibration/test sets"
        )
    train_ids, held_ids = train_test_split(
        patients.index, test_size=0.30, random_state=SEED, stratify=patients
    )
    held = patients.loc[held_ids]
    cal_ids, test_ids = train_test_split(
        held.index,
        test_size=0.5,
        random_state=SEED,
        stratify=held if held.value_counts().min() >= 2 else None,
    )
    partitions = [
        frame[frame.patient_id.isin(ids)].copy()
        for ids in (train_ids, cal_ids, test_ids)
    ]
    groups = [set(p.patient_id) for p in partitions]
    if any(groups[i] & groups[j] for i in range(3) for j in range(i)):
        raise AssertionError("Patient overlap between partitions")
    if any(p.label.nunique() < 2 for p in partitions):
        raise ValueError("A patient-separated partition has only one outcome class")
    return partitions


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def predict(bundle, x):
    raw = bundle["estimator"].predict_proba(x)[:, 1]
    return (
        bundle["calibrator"].predict_proba(logit(raw))[:, 1]
        if bundle.get("calibrator") is not None
        else raw
    )


def fit_monotone_calibrator(raw, y):
    candidate = LogisticRegression(C=1.0, random_state=SEED).fit(logit(raw), y)
    if candidate.coef_[0, 0] <= 0:
        return (
            None,
            "Calibration unsupported: non-positive slope on calibration patients; retaining raw model probabilities",
        )
    return (
        candidate,
        "Monotone sigmoid fitted on patient-disjoint source calibration subset",
    )


def metric_values(y, p, threshold):
    y = np.asarray(y, dtype=int)
    p = np.asarray(p, dtype=float)
    alert = p >= threshold
    tp = int(np.sum(alert & (y == 1)))
    fp = int(np.sum(alert & (y == 0)))
    fn = int(np.sum(~alert & (y == 1)))
    tn = int(np.sum(~alert & (y == 0)))
    return {
        "windows": len(y),
        "positive_windows": int(y.sum()),
        "prevalence": float(y.mean()) if len(y) else None,
        "auroc": float(roc_auc_score(y, p)) if len(set(y)) > 1 else None,
        "auprc": float(average_precision_score(y, p)) if y.sum() else None,
        "brier_score": float(brier_score_loss(y, p)) if len(y) else None,
        "sensitivity": tp / (tp + fn) if tp + fn else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "specificity": tn / (tn + fp) if tn + fp else None,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "alert_threshold": float(threshold),
    }


def evaluate(frame, probability, threshold, bootstrap=True):
    result = metric_values(frame.label, probability, threshold)
    result.update(
        {
            "patients": int(frame.patient_id.nunique()),
            "stays": int(frame.stay_id.nunique()),
            "hospitals": int(frame.hospital_id.nunique()),
        }
    )
    if len(frame) and frame.label.nunique() > 1:
        fpr, tpr, _ = roc_curve(frame.label, probability, drop_intermediate=True)
        precision, recall, _ = precision_recall_curve(
            frame.label, probability, drop_intermediate=True
        )

        def sample(a, limit=80):
            idx = np.unique(np.linspace(0, len(a) - 1, min(limit, len(a))).astype(int))
            return a[idx].tolist()

        # Paired sampling preserves corresponding curve coordinates.
        idx = np.unique(np.linspace(0, len(fpr) - 1, min(80, len(fpr))).astype(int))
        ridx = np.unique(
            np.linspace(0, len(recall) - 1, min(80, len(recall))).astype(int)
        )
        result["roc_curve"] = {"fpr": fpr[idx].tolist(), "tpr": tpr[idx].tolist()}
        result["precision_recall_curve"] = {
            "precision": precision[ridx].tolist(),
            "recall": recall[ridx].tolist(),
        }
    bins = []
    p = np.asarray(probability)
    for low in np.linspace(0, 0.9, 10):
        mask = (p >= low) & (p < (low + 0.1) if low < 0.89 else p <= 1)
        if mask.any():
            bins.append(
                {
                    "count": int(mask.sum()),
                    "mean_predicted": float(p[mask].mean()),
                    "observed_fraction": float(frame.label.to_numpy()[mask].mean()),
                }
            )
    result["calibration_bins"] = bins
    # Predictions every 6h: burden denominator is sampled prediction-window time,
    # explicitly not all ICU time. No false claim of prospective alerts/patient-day.
    result["alerts_per_100_evaluated_windows"] = (
        float(np.mean(p >= threshold) * 100) if len(p) else None
    )
    leads, documented_leads = [], []
    lead_frame = frame[["stay_id", "label", "at_hour", "onset_hour"]].copy()
    lead_frame["onset_documented_hour"] = frame.get(
        "onset_documented_hour", frame.onset_hour
    )
    lead_frame["probability"] = p
    evaluable_events = 0
    for _, g in lead_frame.groupby("stay_id"):
        if not (g.label == 1).any():
            continue
        evaluable_events += 1
        alerts = g[(g.probability >= threshold) & (g.label == 1)].sort_values("at_hour")
        if not alerts.empty:
            first = alerts.iloc[0]
            leads.append(float(first.onset_hour - first.at_hour))
            documented_leads.append(float(first.onset_documented_hour - first.at_hour))
    result["evaluable_aki_stays"] = evaluable_events
    result["detected_aki_stays"] = len(leads)
    result["event_sensitivity"] = (
        len(leads) / evaluable_events if evaluable_events else None
    )
    result["median_sample_lead_hours"] = float(np.median(leads)) if leads else None
    result["detected_stays_with_documented_lead_time"] = len(leads)
    result["median_documented_lead_hours"] = (
        float(np.median(documented_leads)) if leads else None
    )
    result["fraction_evaluable_events_warned_at_least_hours"] = {
        str(h): sum(v >= h for v in leads) / evaluable_events
        if evaluable_events
        else None
        for h in (6, 12, 18, 24)
    }
    result["lead_time_note"] = (
        "Sample time is first observed qualifying measurement, not biological onset; "
        "lead summaries conditional on detection. Event denominator includes only stays "
        "with an eligible positive prediction window; no full-24h warning guarantee."
    )
    if bootstrap:
        result["patient_bootstrap_95ci"] = bootstrap_intervals(frame, p, threshold)
        result["subgroups"] = {}
        for name, mask in {
            "recorded_male": frame.sex_male == 1,
            "recorded_female": (frame.sex_male == 0) & (frame.sex_unknown == 0),
            "age_65_plus": frame.age >= 65,
            "age_under_65": frame.age < 65,
        }.items():
            sub = frame[mask]
            if len(sub):
                result["subgroups"][name] = {
                    "patients": int(sub.patient_id.nunique()),
                    **metric_values(sub.label, p[np.asarray(mask)], threshold),
                    "note": "Exploratory; small subgroups do not establish fairness",
                }
    return result


def bootstrap_intervals(frame, probability, threshold, repetitions=200):
    ids = frame.patient_id.to_numpy()
    unique = np.unique(ids)
    blocks = [np.flatnonzero(ids == pid) for pid in unique]
    rng = np.random.default_rng(SEED)
    metrics = {
        k: [] for k in ("auroc", "auprc", "brier_score", "sensitivity", "precision")
    }
    y = frame.label.to_numpy()
    p = np.asarray(probability)
    for _ in range(repetitions):
        sample = np.concatenate(
            [blocks[i] for i in rng.integers(0, len(blocks), len(blocks))]
        )
        if len(np.unique(y[sample])) < 2:
            continue
        values = metric_values(y[sample], p[sample], threshold)
        for key, items in metrics.items():
            if values[key] is not None:
                items.append(values[key])
    return {
        "method": "Percentile patient-block bootstrap, preserves repeated windows; exploratory",
        "resamples": repetitions,
        "intervals": {
            key: {
                "low": float(np.quantile(values, 0.025)),
                "high": float(np.quantile(values, 0.975)),
                "valid_resamples": len(values),
            }
            for key, values in metrics.items()
            if values
        },
    }


def choose_threshold(y, p):
    # Calibration-only selection; fixed before internal/external tests.
    options = sorted(set(np.asarray(p).round(6)))
    valid = []
    for threshold in options:
        m = metric_values(y, p, threshold)
        if m["sensitivity"] is not None and m["sensitivity"] >= 0.80:
            valid.append((m["precision"] or 0, threshold))
    return float(max(valid)[1]) if valid else 0.5


def fit_candidate(config, x, y, features):
    augmented_x, augmented_y = group_dropout(
        x, y, features, config.get("group_dropout", False)
    )
    estimator = model_for(config)
    estimator.fit(augmented_x, augmented_y)
    return estimator


def tune(train, features):
    x = train[features].to_numpy(dtype=float)
    y = train.label.to_numpy()
    labels = train.groupby("patient_id").label.max()
    folds = min(3, int(labels.value_counts().min()))
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=SEED)
    splits = list(splitter.split(x, y, train.patient_id))
    stress = development_stress_cases(train)
    if stress.empty:
        raise ValueError("No development stress scenarios; cannot assess robustness")
    scores = []
    for config in CANDIDATES:
        selected = select_features(features, config)
        x = train[selected].to_numpy(dtype=float)
        fold_scores = []
        for a, b in splits:
            if len(set(y[a])) < 2 or len(set(y[b])) < 2:
                continue
            estimator = fit_candidate(config, x[a], y[a], selected)
            p = estimator.predict_proba(x[b])[:, 1]
            held_stress = stress[stress.base_index.isin(train.index[b])]
            robustness = stress_statistics(
                held_stress,
                selected,
                lambda z, estimator=estimator: estimator.predict_proba(z)[:, 1],
                dict(zip(train.index[b], p)),
            )
            auprc = float(average_precision_score(y[b], p))
            score = (
                auprc
                - 0.5 * robustness["creatinine_p95_delta"]
                - 0.25 * robustness["missing_group_p95_delta"]
            )
            fold_scores.append(
                {
                    "auprc": auprc,
                    "brier_score": float(brier_score_loss(y[b], p)),
                    "robustness": robustness,
                    "selection_score": score,
                }
            )
        if fold_scores:
            scores.append(
                {
                    "config": config,
                    "mean_auprc": float(np.mean([v["auprc"] for v in fold_scores])),
                    "mean_brier": float(
                        np.mean([v["brier_score"] for v in fold_scores])
                    ),
                    "selection_score": float(
                        np.mean([v["selection_score"] for v in fold_scores])
                    ),
                    "folds": fold_scores,
                }
            )
        print(
            "  candidate",
            config["name"],
            scores[-1]["selection_score"] if fold_scores else "insufficient classes",
            flush=True,
        )
    if not scores:
        raise ValueError("No valid grouped CV folds")
    scores.sort(key=lambda v: (v["selection_score"], -v["mean_brier"]), reverse=True)
    return scores[0]["config"], scores


def source_train(frame, source, features):
    data = frame[frame.source == source]
    train, cal, test = grouped_split(data, source)
    print(
        f"Training {source}: {len(train)} development / {len(cal)} calibration / {len(test)} test windows",
        flush=True,
    )
    config, tuning = tune(train, features)
    features = select_features(features, config)
    estimator = fit_candidate(
        config, train[features].to_numpy(float), train.label.to_numpy(), features
    )
    raw = estimator.predict_proba(cal[features].to_numpy(float))[:, 1]
    class_patients = cal.groupby("patient_id").label.max().value_counts()
    if len(class_patients) < 2 or class_patients.min() < 5:
        calibrator, calibration_status = (
            None,
            "Calibration unsupported: fewer than five patients per outcome class; retaining raw probabilities",
        )
    else:
        calibrator, calibration_status = fit_monotone_calibrator(
            raw, cal.label.to_numpy()
        )
    medians = {}
    for name in features:
        finite = train[name].dropna()
        medians[name] = float(finite.median()) if len(finite) else 0.0
    bundle = {
        "estimator": estimator,
        "calibrator": calibrator,
        "features": features,
        "reference_medians": medians,
    }
    pcal = predict(bundle, cal[features].to_numpy(float))
    threshold = choose_threshold(cal.label, pcal)
    metadata = {
        "model_version": __version__,
        "trained_at": datetime.now(UTC).isoformat(),
        "training_source": source,
        "software_versions": {
            "python": sys.version.split()[0],
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "data_scope": "official unrestricted demo samples",
        "target": "first qualifying creatinine sample meeting KDIGO-2012 within next 24h",
        "minimum_recent_measurement_groups": 3,
        "endpoint_time": "sample collection/measurement, not result entry or biological onset",
        "holdout_status": "Preserved baseline patient IDs; previously inspected audit holdouts, not fresh validation",
        "horizon_hours": 24,
        "prediction_interval_hours": 6,
        "supported_prediction_hours": {"min": 12, "max": 168},
        "selected_algorithm": config,
        "selection_criterion": "Development grouped CV: AUPRC - 0.5*creatinine stress p95 risk delta - 0.25*missing-group p95 risk delta",
        "completion_protocol": "reports/completion_protocol.json",
        "augmentation": "Optional group-dropout derived copies inside training folds only; not independent patients"
        if config.get("group_dropout")
        else "none",
        "sensitivity_diagnostic": "Latest creatinine +/-0.04 mg/dL and removal of one optional measurement group; engineering stress, not a clinical confidence interval",
        "status": "research_demo_not_clinically_validated",
        "calibration": calibration_status,
        "alert_threshold": threshold,
        "threshold_selection": "source calibration: maximize precision at sensitivity >=0.80",
        "supported_measurements": MODEL_MEASUREMENTS,
        "context_only_inputs": [
            "weight_kg",
            "fluid_input_ml",
            "ventilation",
            "vasopressor",
            "diuretic",
            "nephrotoxic_drug",
            "admission_type",
            "comorbidities",
        ],
        "explanation_method": "Replace one feature group with development-set medians; report probability difference. Non-additive and non-causal; not SHAP.",
        "split_patients": {
            name: sorted(part.patient_id.unique().tolist())
            for name, part in [
                ("development", train),
                ("calibration", cal),
                ("test", test),
            ]
        },
        "split_window_counts": {
            name: len(part)
            for name, part in [
                ("development", train),
                ("calibration", cal),
                ("test", test),
            ]
        },
        "limitations": [
            "Small, selected demo cohorts",
            "No prospective clinical validation",
            "Documented urine volumes have unknown collection coverage and are not urine rates",
            "Observed creatinine baseline may miss pre-existing AKI",
            "Outcome visibility depends on laboratory testing",
            "24h horizon does not guarantee 24h lead time",
            "No established transportability beyond evaluated samples",
        ],
    }
    bundle["metadata"] = metadata
    internal = evaluate(
        test, predict(bundle, test[features].to_numpy(float)), threshold
    )
    internal["patient_overlap_with_development_or_calibration"] = 0
    external = {}
    for target in sorted(set(frame.source) - {source}):
        other = frame[frame.source == target]
        external[target] = evaluate(
            other, predict(bundle, other[features].to_numpy(float)), threshold
        )
    atomic_model(ARTIFACTS / f"{source}_model.joblib", bundle)
    out = test[META].copy()
    out["predicted_risk"] = predict(bundle, test[features].to_numpy(float))
    out.to_csv(REPORTS / f"{source}_internal_predictions.csv", index=False)
    return bundle, {
        "tuning": tuning,
        "internal_test": internal,
        "external_tests": external,
        "metadata": metadata,
    }


def hospital_validation(frame, features):
    e = frame[frame.source == "eicu"]
    hospitals = sorted(e.hospital_id.unique())
    results = []
    # A fixed lightweight baseline, not tuned on held-out hospital outcomes.
    for hospital in hospitals:
        test = e[e.hospital_id == hospital]
        # A patient appearing at held-out hospital is removed from all training rows.
        train = e[(e.hospital_id != hospital) & (~e.patient_id.isin(test.patient_id))]
        if train.label.nunique() < 2 or len(train) < 30 or len(test) < 10:
            results.append(
                {
                    "hospital": hospital,
                    "status": "insufficient labelled data",
                    "windows": len(test),
                }
            )
            continue
        estimator = model_for({"kind": "logistic", "C": 0.1})
        estimator.fit(train[features].to_numpy(float), train.label)
        p = estimator.predict_proba(test[features].to_numpy(float))[:, 1]
        metrics = evaluate(test, p, 0.5, bootstrap=False)
        metrics["patient_overlap_with_training"] = 0
        results.append(
            {"hospital": hospital, "status": "evaluated", "metrics": metrics}
        )
    return {
        "method": "leave-one-hospital-out fixed logistic baseline",
        "note": "Different from the selected deployed source model; threshold fixed at 0.5, no target calibration",
        "results": results,
    }


def train_all():
    frame = pd.read_csv(DATA / "features.csv.gz")
    features = sorted(set(frame.columns) - set(META))
    report = {
        "scope": "Exploratory demo-sample audit; reused preserved patient holdouts, not fresh validation",
        "audit_protocol": "reports/completion_protocol.json",
        "baseline_archive": "reports/baseline_v0_1",
        "seed": SEED,
        "feature_names": features,
        "directions": {},
    }
    report["feature_missing_fraction_by_source"] = {
        source: {name: float(group[name].isna().mean()) for name in features}
        for source, group in frame.groupby("source")
    }
    report["features_sha256"] = hashlib.sha256(
        (DATA / "features.csv.gz").read_bytes()
    ).hexdigest()
    bundles = {}
    with threadpool_limits(limits=2):
        for source in ("eicu", "mimic"):
            try:
                bundle, result = source_train(frame, source, features)
                bundles[source] = bundle
                report["directions"][source] = result
            except ValueError as exc:
                report["directions"][source] = {
                    "status": "insufficient data",
                    "reason": str(exc),
                }
                print(f"Skipping {source}: {exc}", flush=True)
        report["leave_hospital_out"] = hospital_validation(frame, features)
    if not bundles:
        raise ValueError("Neither demo cohort supports training. See cohort report.")
    deployed = bundles.get("eicu", next(iter(bundles.values())))
    atomic_model(MODEL_PATH, deployed)
    report["deployed_model_source"] = deployed["metadata"]["training_source"]
    report["model_sha256"] = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    atomic_json(REPORTS / "evaluation.json", report)
    print(f"Saved model to {MODEL_PATH}", flush=True)
    return report
