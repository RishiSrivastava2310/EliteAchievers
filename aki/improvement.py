"""Bounded development-only challengers, with patient and hospital isolation."""

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.model_selection import StratifiedGroupKFold

from .config import SEED
from .robustness import stress_statistics
from .train import fit_candidate, model_for


def patient_weights(frame):
    """Equal total weight per patient, using this fitting partition only."""
    counts = frame.patient_id.map(frame.patient_id.value_counts()).to_numpy(float)
    weights = 1 / counts
    return weights / weights.mean()


def development_only(frame, metadata):
    groups = metadata["split_patients"]
    development = set(groups["development"])
    forbidden = set(groups["calibration"]) | set(groups["test"])
    if development & forbidden:
        raise ValueError("Development patient IDs overlap calibration/test")
    selected = frame[
        (frame.source == metadata["training_source"])
        & frame.patient_id.isin(development)
    ].copy()
    if selected.empty or selected.label.nunique() != 2:
        raise ValueError("Insufficient development outcomes")
    return selected


def isolated_folds(frame, kind, folds=3):
    group = "patient_id" if kind == "patient" else "hospital_id"
    if kind not in ("patient", "hospital"):
        raise ValueError("Unknown isolation kind")
    if frame[group].nunique() < folds:
        raise ValueError("Insufficient independent groups")
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=SEED)
    result = []
    for a, b in splitter.split(frame, frame.label, frame[group]):
        # A patient with stays in several hospitals cannot remain in fitting data
        # when any of their stays belongs to a held-out hospital.
        held_patients = set(frame.iloc[b].patient_id)
        a = a[~frame.iloc[a].patient_id.isin(held_patients).to_numpy()]
        fit, held = frame.iloc[a], frame.iloc[b]
        if fit.label.nunique() != 2 or held.label.nunique() != 2:
            raise ValueError("An isolated fold lacks one outcome class")
        assert not set(fit.patient_id) & set(held.patient_id)
        if kind == "hospital":
            assert not set(fit.hospital_id) & set(held.hospital_id)
        result.append((a, b))
    return result


class AveragedClassifier:
    """A fixed probability blend; weights are never fitted to held-out outcomes."""

    def __init__(self, tree_config, tree_fraction):
        self.tree_config = tree_config
        self.tree_fraction = tree_fraction

    def fit(self, x, y):
        self.tree_ = model_for(self.tree_config).fit(x, y)
        self.linear_ = model_for({"kind": "logistic", "C": 0.1}).fit(x, y)
        self.n_features_in_ = x.shape[1]
        self.classes_ = np.array([0, 1])
        return self

    def predict_proba(self, x):
        return self.tree_fraction * self.tree_.predict_proba(x) + (
            1 - self.tree_fraction
        ) * self.linear_.predict_proba(x)


def challenger_configs(incumbent):
    if incumbent["kind"] != "hist_gradient_boosting":
        raise ValueError("This bounded study requires a boosted-tree incumbent")
    regularized = {**incumbent, "min_samples_leaf": 40, "l2_regularization": 10}
    return [
        {"name": "incumbent", "estimator": incumbent},
        {"name": "patient_balanced", "estimator": incumbent, "patient_balanced": True},
        {"name": "regularized", "estimator": regularized},
        {
            "name": "patient_balanced_regularized",
            "estimator": regularized,
            "patient_balanced": True,
        },
        {"name": "blend_75_tree", "estimator": incumbent, "tree_fraction": 0.75},
        {"name": "blend_50_tree", "estimator": incumbent, "tree_fraction": 0.5},
    ]


def fit_challenger(config, frame, features):
    x, y = frame[features].to_numpy(float), frame.label.to_numpy()
    if "tree_fraction" in config:
        return AveragedClassifier(config["estimator"], config["tree_fraction"]).fit(
            x, y
        )
    if config.get("patient_balanced"):
        estimator = model_for(config["estimator"])
        estimator.fit(x, y, sample_weight=patient_weights(frame))
        return estimator
    return fit_candidate(config["estimator"], x, y, features)


def qualify_development(frame, features, configs, stress):
    splits = {kind: isolated_folds(frame, kind) for kind in ("patient", "hospital")}
    audits = {}
    for kind, folds in splits.items():
        audits[kind] = [
            {
                "fit_patients": sorted(frame.iloc[a].patient_id.unique().tolist()),
                "held_patients": sorted(frame.iloc[b].patient_id.unique().tolist()),
                "fit_hospitals": sorted(frame.iloc[a].hospital_id.unique().tolist()),
                "held_hospitals": sorted(frame.iloc[b].hospital_id.unique().tolist()),
                "fit_windows": len(a),
                "held_windows": len(b),
            }
            for a, b in folds
        ]
    candidates = []
    for config in configs:
        scores = {}
        for kind, folds in splits.items():
            values = []
            for a, b in folds:
                estimator = fit_challenger(config, frame.iloc[a], features)
                held = frame.iloc[b]
                probability = estimator.predict_proba(held[features].to_numpy(float))[
                    :, 1
                ]
                variants = stress[stress.base_index.isin(held.index)]
                sensitivity = stress_statistics(
                    variants,
                    features,
                    lambda z, estimator=estimator: estimator.predict_proba(z)[:, 1],
                    dict(zip(held.index, probability)),
                )
                auprc = float(average_precision_score(held.label, probability))
                values.append(
                    {
                        "auprc": auprc,
                        "brier": float(brier_score_loss(held.label, probability)),
                        "creatinine_p95_delta": sensitivity["creatinine_p95_delta"],
                        "missing_group_p95_delta": sensitivity[
                            "missing_group_p95_delta"
                        ],
                        "selection_score": auprc
                        - 0.5 * sensitivity["creatinine_p95_delta"]
                        - 0.25 * sensitivity["missing_group_p95_delta"],
                    }
                )
            scores[kind] = {
                "mean": {
                    key: float(np.mean([v[key] for v in values])) for key in values[0]
                },
                "folds": values,
            }
        candidate = {"config": config, "scores": scores}
        candidates.append(candidate)
        print(
            config["name"],
            {
                kind: round(value["mean"]["selection_score"], 4)
                for kind, value in scores.items()
            },
            flush=True,
        )
    for candidate in candidates:
        candidate["qualification"] = qualification_gate(candidate, candidates[0])
    eligible = [c for c in candidates[1:] if c["qualification"]["eligible"]]
    winner = max(
        eligible,
        key=lambda c: np.mean(
            [v["mean"]["selection_score"] for v in c["scores"].values()]
        ),
        default=None,
    )
    return {
        "fold_isolation": audits,
        "candidates": candidates,
        "qualified_candidate": winner["config"]["name"] if winner else None,
        "production_model_changed": False,
        "meaning": "Development diagnostics only; no calibration, test or external outcomes used for this decision. Hospital folds validate refitted configurations, not the deployed fitted model.",
    }


def qualification_gate(candidate, baseline):
    differences = [
        candidate["scores"][kind]["mean"]["selection_score"]
        - baseline["scores"][kind]["mean"]["selection_score"]
        for kind in ("patient", "hospital")
    ]
    conditions = {
        "mean_score_gain_at_least_0_01": float(np.mean(differences)) >= 0.01,
        "no_group_auprc_drop_over_0_01": all(
            candidate["scores"][kind]["mean"]["auprc"]
            >= baseline["scores"][kind]["mean"]["auprc"] - 0.01
            for kind in ("patient", "hospital")
        ),
        "no_group_brier_increase_over_0_005": all(
            candidate["scores"][kind]["mean"]["brier"]
            <= baseline["scores"][kind]["mean"]["brier"] + 0.005
            for kind in ("patient", "hospital")
        ),
        "no_creatinine_stress_increase_over_0_02": all(
            candidate["scores"][kind]["mean"]["creatinine_p95_delta"]
            <= baseline["scores"][kind]["mean"]["creatinine_p95_delta"] + 0.02
            for kind in ("patient", "hospital")
        ),
        "score_improves_in_at_least_four_of_six_folds": sum(
            a["selection_score"] > b["selection_score"]
            for kind in ("patient", "hospital")
            for a, b in zip(
                candidate["scores"][kind]["folds"],
                baseline["scores"][kind]["folds"],
            )
        )
        >= 4,
    }
    return {
        "eligible": all(conditions.values()),
        "conditions": conditions,
        "mean_selection_score_gain": float(np.mean(differences)),
    }
