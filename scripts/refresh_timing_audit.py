"""Refresh corrected recognition-time metadata using frozen models, without tuning."""

import csv
import gzip
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aki.artifacts import atomic_json
from aki.config import ARTIFACTS, DATA, MODEL_PATH, REPORTS
from aki.dataset import observed_endpoint
from aki.storage import connect, load_stay
from aki.train import META, evaluate, model_for, predict


def main():
    path = DATA / "features.csv.gz"
    original = pd.read_csv(path)
    with connect() as con:
        ids = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT stay_id FROM (SELECT stay_id,hour FROM observations WHERE variable='creatinine' GROUP BY stay_id,hour HAVING count(*)>1)"
            )
        ]
    changes = {}
    for sid in ids:
        rows = original[original.stay_id == sid]
        if rows.empty:
            continue
        stay = load_stay(sid)
        endpoint = observed_endpoint(
            stay["patient"], stay["readings"], stay["duration_hours"]
        )
        if endpoint is None:
            assert rows.onset_hour.isna().all()
            continue
        assert np.allclose(
            rows.onset_hour, endpoint["measurement_hour"], atol=1e-10, rtol=0
        )
        old = float(rows.onset_documented_hour.iloc[0])
        new = endpoint["documented_hour"]
        if abs(old - new) > 1e-10:
            changes[sid] = {
                "old_documented_hour": old,
                "new_documented_hour": new,
                "affected_windows": len(rows),
            }
    if not changes:
        print(
            "No pending recognition-time metadata changes; model inputs remain unchanged."
        )
        return
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        records = list(csv.reader(stream))
    columns = records[0]
    sid_index, documented_index = (
        columns.index("stay_id"),
        columns.index("onset_documented_hour"),
    )
    for row in records[1:]:
        if row[sid_index] in changes:
            row[documented_index] = repr(changes[row[sid_index]]["new_documented_hour"])
    with NamedTemporaryFile(dir=DATA, suffix=".timing.csv.gz", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerows(records)
        frame = pd.read_csv(temporary)
        pd.testing.assert_frame_equal(
            original.drop(columns="onset_documented_hour"),
            frame.drop(columns="onset_documented_hour"),
            check_exact=True,
        )
        report = json.loads((REPORTS / "evaluation.json").read_text())
        features = report["feature_names"]
        affected_hospitals = set(frame[frame.stay_id.isin(changes)].hospital_id)
        with threadpool_limits(limits=2):
            for source, direction in report["directions"].items():
                if "metadata" not in direction:
                    continue
                bundle = joblib.load(ARTIFACTS / f"{source}_model.joblib")
                threshold = bundle["metadata"]["alert_threshold"]
                selected = bundle["features"]
                test_ids = bundle["metadata"]["split_patients"]["test"]
                test = frame[(frame.source == source) & frame.patient_id.isin(test_ids)]
                probabilities = predict(bundle, test[selected].to_numpy(float))
                nominal = evaluate(test, probabilities, threshold)
                nominal["patient_overlap_with_development_or_calibration"] = 0
                for key in (
                    "auroc",
                    "auprc",
                    "brier_score",
                    "confusion",
                    "sensitivity",
                    "precision",
                    "median_sample_lead_hours",
                ):
                    assert nominal[key] == direction["internal_test"][key], (
                        source,
                        key,
                    )
                direction["internal_test"] = nominal
                out = test[META].copy()
                out["predicted_risk"] = probabilities
                out.to_csv(REPORTS / f"{source}_internal_predictions.csv", index=False)
                for target, prior in direction["external_tests"].items():
                    other = frame[frame.source == target]
                    updated = evaluate(
                        other,
                        predict(bundle, other[selected].to_numpy(float)),
                        threshold,
                    )
                    for key in (
                        "auroc",
                        "auprc",
                        "brier_score",
                        "confusion",
                        "sensitivity",
                        "precision",
                        "median_sample_lead_hours",
                    ):
                        assert updated[key] == prior[key], (source, target, key)
                    direction["external_tests"][target] = updated
            eicu = frame[frame.source == "eicu"]
            for holdout in report["leave_hospital_out"]["results"]:
                if (
                    holdout["hospital"] not in affected_hospitals
                    or holdout["status"] != "evaluated"
                ):
                    continue
                test = eicu[eicu.hospital_id == holdout["hospital"]]
                train = eicu[
                    (eicu.hospital_id != holdout["hospital"])
                    & (~eicu.patient_id.isin(test.patient_id))
                ]
                estimator = model_for({"kind": "logistic", "C": 0.1})
                estimator.fit(train[features].to_numpy(float), train.label)
                metrics = evaluate(
                    test,
                    estimator.predict_proba(test[features].to_numpy(float))[:, 1],
                    0.5,
                    bootstrap=False,
                )
                metrics["patient_overlap_with_training"] = 0
                holdout["metrics"] = metrics
        temporary.replace(path)
        report["features_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        report["recognition_timing_audit"] = {
            "updated_at": datetime.now(UTC).isoformat(),
            "changed_stays": changes,
            "model_inputs_labels_and_sample_times_unchanged": True,
            "model_weights_unchanged": True,
            "model_sha256": hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
            "meaning": "First recognition preserves earliest as-of qualifying versions; current stage/value still reflect latest corrected results.",
        }
        atomic_json(REPORTS / "evaluation.json", report)
        atomic_json(
            REPORTS / "expert_timing_changes.json",
            {
                "revised_stays_checked": len(ids),
                **report["recognition_timing_audit"],
            },
        )
        cohort_path = REPORTS / "cohort.json"
        cohort = json.loads(cohort_path.read_text())
        cohort["definition"]["documentation_time"] = report["recognition_timing_audit"][
            "meaning"
        ]
        atomic_json(cohort_path, cohort)
    finally:
        if temporary.exists():
            temporary.unlink()
    from aki.cli import finalize_training

    finalize_training(report)
    print(
        f"Updated recognition metadata for {len(changes)} stays; predictors, labels, sample leads and model weights are unchanged."
    )


if __name__ == "__main__":
    main()
