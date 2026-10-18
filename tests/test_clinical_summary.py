"""Clinician-use scenarios: the kidney forecast must not hide current facts."""

import json

import pytest
from fastapi.testclient import TestClient

from aki.api import app
from aki.clinical import assess
from aki.clinical_summary import summarize
from aki.config import ROOT
from aki.schema import Patient, PredictionRequest, Reading
from aki.service import prediction_history, run_prediction


def forecast():
    return {
        "status": "predicted",
        "alert": False,
        "predicted_risk_percent": 1.0,
        "clinical_assessment": assess(
            Patient(age=60),
            [Reading(hour=0, creatinine=0.8), Reading(hour=12, creatinine=0.8)],
            12,
        ),
        "input_sensitivity": None,
    }


@pytest.mark.parametrize(
    "potassium,urgent", [(5.9, False), (6, True), (6.4, True), (6.5, True)]
)
def test_current_potassium_review_is_independent_of_low_future_kidney_score(
    potassium, urgent
):
    result = summarize(forecast(), [Reading(hour=12, potassium=potassium)], 12)
    assert result["urgent_review_required"] is urgent
    if urgent:
        assert result["headline"] == "High potassium needs urgent review"
        assert result["current_findings"][0]["value"] == potassium
        assert result["current_findings"][0]["measurement_hour"] == 12


def test_delayed_critical_result_is_hidden_until_available():
    rows = [Reading(hour=10, available_hour=14, potassium=6.7)]
    assert not summarize(forecast(), rows, 12)["urgent_review_required"]
    assert summarize(forecast(), rows, 14)["urgent_review_required"]


def test_available_correction_removes_retracted_potassium_finding():
    rows = [
        Reading(hour=6, potassium=6.7),
        Reading(hour=6, available_hour=14, potassium=4.2),
    ]
    assert summarize(forecast(), rows, 12)["urgent_review_required"]
    assert not summarize(forecast(), rows, 14)["urgent_review_required"]


def test_delayed_older_high_potassium_cannot_override_newer_normal_sample():
    rows = [
        Reading(hour=0, available_hour=12, potassium=6.7),
        Reading(hour=6, available_hour=8, potassium=4.2),
    ]
    assert not summarize(forecast(), rows, 12)["urgent_review_required"]


def test_old_latest_high_result_keeps_age_and_does_not_claim_it_is_current():
    result = summarize(forecast(), [Reading(hour=0, potassium=6.7)], 48)
    finding = result["current_findings"][0]
    assert finding["age_hours"] == 48
    assert "does not prove the level is still high" in finding["message"]


def test_missing_potassium_is_unknown_without_inventing_an_abnormal_value():
    result = summarize(forecast(), [Reading(hour=12, bun=20)], 12)
    assert not result["urgent_review_required"]
    assert result["current_findings"] == []
    assert "Missing information is not a normal result" in result["meaning"]


def test_no_early_warning_does_not_label_the_patient_normal():
    result = summarize(forecast(), [], 12)
    assert result["headline"] == "Below the kidney warning threshold"
    assert "overall condition" in result["message"]


@pytest.mark.parametrize("chronic_dialysis", [False, True])
def test_urgent_current_finding_survives_abstained_prediction(chronic_dialysis):
    body = PredictionRequest(
        patient=Patient(age=60, chronic_dialysis=chronic_dialysis),
        at_hour=12,
        readings=[Reading(hour=12, creatinine=0.8, potassium=6.7)],
    )
    result = run_prediction(body)
    assert result["predicted_risk"] is None
    assert result["clinical_summary"]["urgent_review_required"]
    assert result["clinical_summary"]["current_findings"][0]["value"] == 6.7


def test_earlier_aki_is_not_mislabelled_as_new_current_aki_in_plain_summary():
    body = PredictionRequest(
        patient=Patient(age=60),
        at_hour=24,
        readings=[
            Reading(hour=0, creatinine=0.8),
            Reading(hour=6, creatinine=1.2),
            Reading(hour=24, creatinine=0.8),
        ],
    )
    result = run_prediction(body)
    assert result["status"] == "aki_already_observed"
    assert result["clinical_summary"]["headline"] == "Earlier kidney injury is recorded"


def test_history_summary_never_uses_future_potassium_result():
    body = json.loads((ROOT / "examples/stable.json").read_text())
    body["at_hour"] = 24
    body["readings"].append({"hour": 20, "available_hour": 24, "potassium": 6.7})
    history = prediction_history(PredictionRequest.model_validate(body))
    assert not history["items"][0]["clinical_summary"]["urgent_review_required"]
    assert history["items"][-1]["clinical_summary"]["urgent_review_required"]
    assert history["items"][-1]["review_required"]


def test_unknown_history_point_requests_data_without_inventing_findings():
    body = PredictionRequest(
        patient=Patient(age=60), at_hour=24, readings=[Reading(hour=24, creatinine=0.8)]
    )
    point = prediction_history(body)["items"][0]
    assert point["status"] == "insufficient_data"
    assert point["review_required"]
    assert not point["clinical_summary"]["urgent_review_required"]


def test_json_csv_and_batch_preserve_urgent_current_finding(monkeypatch):
    monkeypatch.delenv("AKI_API_KEY", raising=False)
    body = {
        "patient": {"age": 60},
        "at_hour": 12,
        "readings": [{"hour": 12, "creatinine": 0.8, "potassium": 6.7}],
    }
    csv = "hour,age,creatinine,potassium\n12,60,0.8,6.7\n"
    with TestClient(app) as client:
        json_result = client.post("/v1/predict", json=body).json()
        csv_result = client.post(
            "/v1/predict/csv", content=csv, headers={"Content-Type": "text/csv"}
        ).json()
        batch = client.post("/v1/predict/batch", json={"requests": [body]}).json()
    assert json_result == csv_result == batch[0]
    assert json_result["clinical_summary"]["urgent_review_required"]
