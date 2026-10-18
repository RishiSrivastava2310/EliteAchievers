"""Checks for source-only improvement work and honest alert tradeoffs."""

import copy
import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aki import alerting
from aki.api import app
from aki.config import ROOT
from aki.improvement import (
    development_only,
    isolated_folds,
    patient_weights,
    qualification_gate,
)
from aki.schema import PredictionRequest
from aki.service import load_model, run_prediction


def cohort():
    records = [
        {
            "patient_id": f"p{h}-{p}",
            "hospital_id": f"h{h}",
            "label": p % 2,
            "source": "eicu",
        }
        for h in range(6)
        for p in range(6)
    ]
    # One patient has stays at different hospitals.
    records.append({**records[0], "hospital_id": "h5"})
    return pd.DataFrame(records)


@pytest.mark.parametrize("kind", ["patient", "hospital"])
def test_folds_keep_repeated_patients_out_of_fitting_data(kind):
    frame = cohort()
    folds = isolated_folds(frame, kind)
    held_indices = []
    for a, b in folds:
        fit, held = frame.iloc[a], frame.iloc[b]
        assert not set(fit.patient_id) & set(held.patient_id)
        if kind == "hospital":
            assert not set(fit.hospital_id) & set(held.hospital_id)
        held_indices.extend(b)
    assert sorted(held_indices) == list(range(len(frame)))


def test_development_filter_excludes_calibration_test_and_opposite_source():
    frame = cohort()
    extra = frame.iloc[[0]].copy()
    extra.source = "mimic"
    frame = pd.concat([frame, extra], ignore_index=True)
    ids = list(frame.patient_id.unique())
    metadata = {
        "training_source": "eicu",
        "split_patients": {
            "development": ids[2:],
            "calibration": [ids[0]],
            "test": [ids[1]],
        },
    }
    selected = development_only(frame, metadata)
    assert set(selected.source) == {"eicu"}
    assert set(selected.patient_id) == set(ids[2:])
    metadata["split_patients"]["development"].append(ids[0])
    with pytest.raises(ValueError, match="overlap"):
        development_only(frame, metadata)


def test_inverse_window_weights_give_equal_total_patient_influence():
    frame = pd.DataFrame({"patient_id": ["long"] * 20 + ["short"] * 2 + ["once"]})
    weights = patient_weights(frame)
    totals = pd.Series(weights).groupby(frame.patient_id).sum()
    assert totals.nunique() == 1
    assert weights.mean() == pytest.approx(1)


def score_candidate():
    value = {
        "selection_score": 0.5,
        "auprc": 0.6,
        "brier": 0.15,
        "creatinine_p95_delta": 0.1,
    }
    return {
        "scores": {
            kind: {"mean": value.copy(), "folds": [value.copy() for _ in range(3)]}
            for kind in ("patient", "hospital")
        }
    }


@pytest.mark.parametrize(
    "failure", ["none", "auprc", "brier", "stress", "folds", "gain"]
)
def test_candidate_needs_all_prerecorded_qualification_conditions(failure):
    baseline = score_candidate()
    challenger = copy.deepcopy(baseline)
    for family in challenger["scores"].values():
        family["mean"]["selection_score"] += 0.03
        family["mean"]["auprc"] += 0.03
        for fold in family["folds"]:
            fold["selection_score"] += 0.03
    hospital = challenger["scores"]["hospital"]
    if failure == "auprc":
        hospital["mean"]["auprc"] -= 0.1
    elif failure == "brier":
        hospital["mean"]["brier"] += 0.02
    elif failure == "stress":
        hospital["mean"]["creatinine_p95_delta"] += 0.05
    elif failure == "folds":
        for fold in hospital["folds"]:
            fold["selection_score"] -= 0.1
    elif failure == "gain":
        for family in challenger["scores"].values():
            family["mean"]["selection_score"] -= 0.03
    assert qualification_gate(challenger, baseline)["eligible"] is (failure == "none")


def calibration():
    return pd.DataFrame(
        {
            "patient_id": [f"p{i}" for i in range(10)],
            "label": [0] * 5 + [1] * 5,
        }
    )


def test_fewer_alert_threshold_uses_exact_source_probabilities_and_stated_floor():
    probabilities = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    profiles, status = alerting.build_profile_specs(calibration(), probabilities, 0.25)
    assert status == "available"
    assert profiles["standard"]["threshold"] == 0.25
    assert profiles["fewer_alerts"]["threshold"] == 0.7
    assert profiles["fewer_alerts"]["calibration"]["sensitivity"] == 0.8
    assert profiles["fewer_alerts"]["calibration"]["precision"] == 1


def test_many_repeated_windows_do_not_invent_calibration_patient_support():
    frame = calibration()
    frame.loc[frame.label == 1, "patient_id"] = "same-patient"
    profiles, status = alerting.build_profile_specs(frame, np.linspace(0, 1, 10), 0.25)
    assert set(profiles) == {"standard"}
    assert "five" in status


@pytest.mark.parametrize("bad", [[float("nan")] * 10, [-0.1] * 10, [1.1] * 10, [0.1]])
def test_invalid_calibration_probabilities_are_rejected(bad):
    with pytest.raises(ValueError, match="probabilit"):
        alerting.build_profile_specs(calibration(), bad, 0.25)


@pytest.mark.parametrize(
    "report",
    [
        {"model_sha256": "old", "profiles": {"standard": {"threshold": 0.2}}},
        {"model_sha256": "current", "profiles": {}},
        {"model_sha256": "current", "profiles": {"standard": {"threshold": 2}}},
        {"model_sha256": "current", "profiles": {"standard": None}},
        [],
    ],
)
def test_stale_or_invalid_optional_policy_cannot_disable_standard_forecast(
    report, tmp_path, monkeypatch
):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(report))
    monkeypatch.setattr(alerting, "PROFILE_PATH", path)
    with pytest.raises(FileNotFoundError):
        alerting.read_alert_profiles("current")
    options = alerting.prediction_alert_options(
        0.3, {"metadata": {"alert_threshold": 0.2}, "_artifact_sha256": "current"}
    )
    assert options == {"standard": {"threshold": 0.2, "alert": True}}


def test_actual_policy_is_a_subset_of_standard_alerts_on_every_tested_score():
    bundle = load_model()
    report = alerting.read_alert_profiles(bundle["_artifact_sha256"])
    assert report["risk_estimates_changed"] is False
    assert report["default_policy_changed"] is False
    for probability in np.linspace(0, 1, 101):
        options = alerting.prediction_alert_options(float(probability), bundle)
        if "fewer_alerts" in options:
            assert not options["fewer_alerts"]["alert"] or options["standard"]["alert"]


def test_api_exposes_both_policies_and_protects_report(monkeypatch):
    body = json.loads((ROOT / "examples/stable.json").read_text())
    expected = run_prediction(PredictionRequest.model_validate(body))
    monkeypatch.setenv("AKI_API_KEY", "profile-test-key")
    with TestClient(app) as client:
        assert client.get("/v1/alert-profiles").status_code == 401
        headers = {"X-API-Key": "profile-test-key"}
        report = client.get("/v1/alert-profiles", headers=headers)
        assert report.status_code == 200
        assert report.json()["default_profile"] == "standard"
        prediction = client.post("/v1/predict", json=body, headers=headers)
        assert prediction.status_code == 200
        assert prediction.json() == expected
        assert expected["alert_options"]["standard"]["alert"] == expected["alert"]


def test_abstained_predictions_have_no_applicable_optional_alert():
    body = PredictionRequest.model_validate_json(
        (ROOT / "examples/existing_aki.json").read_text()
    )
    result = run_prediction(body)
    assert result["predicted_risk"] is None
    assert result["alert_options"] == {}
