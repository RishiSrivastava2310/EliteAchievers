"""Offline semantic/data/model audit. Does not tune or change the trained model."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aki.dataset import label_window, observed_endpoint
from aki.features import build_features
from aki.schema import PredictionRequest
from aki.service import model_info, run_prediction
from aki.storage import connect, load_stay
from aki.train import META


def load_case(name):
    return PredictionRequest.model_validate_json(
        (ROOT / f"examples/{name}.json").read_text(encoding="utf-8")
    )


def sensitivity_audit():
    body = load_case("stable").model_dump(exclude_none=True)
    grid, ablation = [], []
    for value in (0.6, 0.7, 0.8, 0.81, 0.85, 0.9, 0.95, 1.0, 1.09, 1.1):
        altered = json.loads(json.dumps(body))
        altered["readings"][-1]["creatinine"] = value
        result = run_prediction(PredictionRequest.model_validate(altered))
        grid.append(
            {
                "last_creatinine": value,
                "status": result["status"],
                "risk_percent": result["predicted_risk_percent"],
                "alert": result["alert"],
            }
        )
    from aki.features import MODEL_MEASUREMENTS

    for name in MODEL_MEASUREMENTS:
        altered = json.loads(json.dumps(body))
        for row in altered["readings"]:
            row.pop(name, None)
        result = run_prediction(PredictionRequest.model_validate(altered))
        ablation.append(
            {
                "omitted_measurement": name,
                "status": result["status"],
                "risk_percent": result["predicted_risk_percent"],
                "alert": result["alert"],
            }
        )
    report = {
        "purpose": "Post-fit illustrative check, not causal or clinical validation. Candidate selection used separate development-patient stress scenarios in completion_protocol.json.",
        "creatinine_grid": grid,
        "missing_input_ablation": ablation,
        "finding": "Borderline alerts can change after small measurement changes or missing inputs. This is an unresolved robustness limitation, not a passed clinical safety test.",
    }
    (ROOT / "reports/sensitivity_audit.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    return report


def main():
    model = model_info()
    evaluation = json.loads((ROOT / "reports/evaluation.json").read_text())
    assert evaluation["model_sha256"] == model["model_sha256"]
    with connect() as con:
        assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert not con.execute("PRAGMA foreign_key_check").fetchall()
        invalid_times = con.execute(
            "SELECT count(*) FROM observations WHERE available_hour < hour"
        ).fetchone()[0]
        assert invalid_times == 0
        observations = con.execute("SELECT count(*) FROM observations").fetchone()[0]
    manifest = json.loads((ROOT / "data/download_manifest.json").read_text())
    for entry in manifest["files"]:
        raw = ROOT / "data/raw" / entry["source"] / entry["file"]
        assert raw.stat().st_size == entry["bytes"]
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == entry["sha256"]
    frame = pd.read_csv(ROOT / "data/features.csv.gz")
    assert not (set(META) & set(evaluation["feature_names"]))
    assert (
        frame.loc[frame.label == 1, "onset_hour"]
        > frame.loc[frame.label == 1, "at_hour"]
    ).all()
    parity = []
    for source, group in frame.groupby("source"):
        for _, row in group.sample(n=min(10, len(group)), random_state=42).iterrows():
            stay = load_stay(row.stay_id)
            endpoint = observed_endpoint(
                stay["patient"], stay["readings"], stay["duration_hours"]
            )
            label, _ = label_window(
                stay["readings"], stay["duration_hours"], row.at_hour, endpoint
            )
            assert label == row.label
            features, _, _ = build_features(
                stay["patient"], stay["readings"], row.at_hour
            )
            for name, value in features.items():
                assert np.isclose(value, row[name], equal_nan=True), (row.stay_id, name)
            parity.append(
                {
                    "source": source,
                    "stay_id": row.stay_id,
                    "at_hour": float(row.at_hour),
                }
            )

    scenarios = {}
    for name in (
        "stable",
        "concerning_trend",
        "existing_aki",
        "real_patient",
        "missed_case",
        "false_alert",
    ):
        result = run_prediction(load_case(name))
        scenarios[name] = {
            k: result[k] for k in ("status", "predicted_risk_percent", "alert")
        }
        provenance_path = ROOT / f"examples/{name}_provenance.json"
        if provenance_path.exists():
            provenance = json.loads(provenance_path.read_text())
            assert provenance["model_sha256"] == model["model_sha256"]
    assert (
        scenarios["stable"]["predicted_risk_percent"]
        < scenarios["concerning_trend"]["predicted_risk_percent"]
    )
    assert not scenarios["stable"]["alert"] and scenarios["concerning_trend"]["alert"]
    assert scenarios["existing_aki"]["status"] == "aki_already_observed"
    assert scenarios["real_patient"]["alert"]
    assert not scenarios["missed_case"]["alert"]
    assert scenarios["false_alert"]["alert"]

    sparse = PredictionRequest.model_validate(
        {
            "patient": {"age": 60},
            "at_hour": 12,
            "readings": [
                {"hour": 0, "creatinine": 0.8},
                {"hour": 12, "creatinine": 0.9, "map": 80},
            ],
        }
    )
    assert run_prediction(sparse)["status"] == "insufficient_data"

    # Context flags are accepted, but must not silently influence this model.
    baseline = load_case("stable")
    altered = baseline.model_copy(deep=True)
    altered.readings[-1].ventilation = 1
    altered.readings[-1].vasopressor = 1
    altered.readings[-1].nephrotoxic_drug = 1
    assert (
        run_prediction(baseline)["predicted_risk"]
        == run_prediction(altered)["predicted_risk"]
    )
    sensitivity_audit()
    report = {
        "status": "passed",
        "checked_at": datetime.now(UTC).isoformat(),
        "model_sha256": model["model_sha256"],
        "features_sha256": hashlib.sha256(
            (ROOT / "data/features.csv.gz").read_bytes()
        ).hexdigest(),
        "sqlite_integrity": "passed",
        "foreign_keys": "passed",
        "raw_publisher_hashes_verified": len(manifest["files"]),
        "observation_count": observations,
        "invalid_availability_times": invalid_times,
        "sampled_raw_to_feature_and_label_parity": parity,
        "scenarios": scenarios,
        "sparse_input_abstention": "passed",
        "context_only_flags_do_not_affect_risk": "passed",
        "unresolved_robustness_findings": "reports/sensitivity_audit.json",
        "note": "Functional assertions pass. Borderline alert sensitivity remains unresolved; neither this audit nor the test suite is clinical validation.",
    }
    (ROOT / "reports/verification.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(
        f"Offline audit passed: {observations:,} observations, {len(parity)} replay/label comparisons, 6 model scenarios."
    )


if __name__ == "__main__":
    main()
