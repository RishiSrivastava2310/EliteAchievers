import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aki.api import app
from aki.config import MODEL_PATH, REPORTS, ROOT
from aki.csvio import parse_csv
from aki.schema import PredictionRequest
from aki.service import run_prediction
from aki.storage import initialize, list_stays, load_stay
from aki.train import grouped_split


def test_csv_requires_metadata_and_rejects_multiple_patients():
    with pytest.raises(ValueError, match="age"):
        parse_csv("hour,creatinine\n0,0.8\n")
    with pytest.raises(ValueError, match="multiple"):
        parse_csv("hour,age,patient_id,creatinine\n0,60,A,0.8\n6,60,B,0.9\n")


def test_csv_missing_cells_remain_unknown():
    request = parse_csv("hour,age,creatinine,bun\n0,60,.8,\n12,60,.9,20\n")
    assert request.readings[0].bun is None
    assert request.at_hour == 12


def test_csv_duplicate_headers_and_nonfinite_values_fail():
    with pytest.raises(ValueError, match="Duplicate"):
        parse_csv("hour,age,creatinine,creatinine\n0,60,.8,.9\n")
    with pytest.raises(ValueError):
        parse_csv("hour,age,creatinine\n0,60,NaN\n")


def test_multiple_stays_from_one_patient_never_cross_partitions():
    frame = pd.DataFrame(
        [
            {"patient_id": f"p{i}", "stay_id": f"s{i}-{j}", "label": i % 2}
            for i in range(50)
            for j in range(3)
        ]
    )
    a, b, c = grouped_split(frame)
    assert not (
        set(a.patient_id) & set(b.patient_id)
        or set(a.patient_id) & set(c.patient_id)
        or set(b.patient_id) & set(c.patient_id)
    )
    assert sum(len(x) for x in (a, b, c)) == len(frame)


def test_sqlite_queries_are_parameterized(tmp_path):
    path = tmp_path / "test.sqlite3"
    initialize(path)
    assert list_stays("mimic' OR 1=1 --", path=path)["total"] == 0
    with pytest.raises(KeyError):
        load_stay("' OR 1=1 --", path=path)


def test_health_schema_and_invalid_requests_work_without_patient_records():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/v1/input-schema")
        assert response.status_code == 200
        assert response.json()["units"]["creatinine"] == "mg/dL"
        assert client.post("/v1/predict", json={}).status_code == 422
        assert client.get("/v1/stays/missing/timeline?at_hour=12").status_code == 404
        assert (
            client.post(
                "/v1/predict/csv",
                content="abc",
                headers={"Content-Type": "application/json"},
            ).status_code
            == 415
        )


@pytest.mark.skipif(
    not MODEL_PATH.exists(), reason="Run prepare before integration tests"
)
def test_api_and_service_produce_identical_genuine_model_predictions():
    body = json.loads((ROOT / "examples/stable.json").read_text(encoding="utf-8"))
    expected = run_prediction(PredictionRequest.model_validate(body))
    with TestClient(app) as client:
        response = client.post("/v1/predict", json=body)
        assert response.status_code == 200
        assert response.json() == expected
        assert expected["status"] == "predicted"
        assert 0 <= expected["predicted_risk"] <= 1


@pytest.mark.skipif(
    not MODEL_PATH.exists(), reason="Run prepare before integration tests"
)
def test_existing_aki_is_not_presented_as_future_risk():
    body = json.loads((ROOT / "examples/existing_aki.json").read_text(encoding="utf-8"))
    with TestClient(app) as client:
        result = client.post("/v1/predict", json=body).json()
        assert result["status"] == "aki_already_observed"
        assert result["predicted_risk"] is None


@pytest.mark.skipif(
    not MODEL_PATH.exists(), reason="Run prepare before integration tests"
)
def test_insufficient_history_abstains():
    body = {
        "patient": {"age": 60},
        "at_hour": 12,
        "readings": [{"hour": 12, "creatinine": 0.8}],
    }
    with TestClient(app) as client:
        response = client.post("/v1/predict", json=body)
        assert response.status_code == 200
        assert response.json()["status"] == "insufficient_data"
        assert response.json()["predicted_risk"] is None


@pytest.mark.skipif(
    not MODEL_PATH.exists(), reason="Run prepare before integration tests"
)
def test_csv_endpoint_matches_json_input():
    csv = (ROOT / "examples/template.csv").read_text(encoding="utf-8")
    expected = run_prediction(parse_csv(csv))
    with TestClient(app) as client:
        response = client.post(
            "/v1/predict/csv", content=csv, headers={"Content-Type": "text/csv"}
        )
        assert response.status_code == 200
        assert response.json() == expected


@pytest.mark.skipif(
    not MODEL_PATH.exists(), reason="Run prepare before integration tests"
)
def test_evaluation_is_real_source_separated_and_free_of_patient_overlap():
    report = json.loads((REPORTS / "evaluation.json").read_text(encoding="utf-8"))
    for source, direction in report["directions"].items():
        if "metadata" not in direction:
            continue
        groups = direction["metadata"]["split_patients"]
        a, b, c = [set(groups[k]) for k in ("development", "calibration", "test")]
        assert not (a & b or a & c or b & c)
        for target, metrics in direction["external_tests"].items():
            assert target != source
            assert metrics["patients"] > 0


def test_calibration_does_not_reverse_model_risk_order():
    import numpy as np

    from aki.train import fit_monotone_calibrator

    raw = np.array([0.05, 0.1, 0.2, 0.8, 0.9, 0.95])
    fitted, status = fit_monotone_calibrator(raw, np.array([1, 1, 1, 0, 0, 0]))
    assert fitted is None
    assert "unsupported" in status.lower()


@pytest.mark.skipif(
    not MODEL_PATH.exists(), reason="Run prepare before integration tests"
)
def test_missing_measurement_is_not_presented_as_a_measured_contribution():
    body = json.loads((ROOT / "examples/stable.json").read_text(encoding="utf-8"))
    result = run_prediction(PredictionRequest.model_validate(body))
    assert "urine_output_ml" not in {
        r["measurement"] for r in result["model_contributions"]
    }


def test_nonfinite_json_is_rejected_without_a_server_error():
    with TestClient(app) as client:
        response = client.post(
            "/v1/predict",
            content='{"patient":{"age":60},"at_hour":12,"readings":[{"hour":0,"creatinine":NaN}]}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert "detail" in response.json()


@pytest.mark.skipif(
    not MODEL_PATH.exists(), reason="Run prepare before integration tests"
)
@pytest.mark.parametrize("source", ["mimic", "eicu"])
def test_saved_training_features_match_replayed_inference(source):
    import numpy as np

    from aki.service import load_model
    from aki.train import predict

    bundle = load_model()
    frame = pd.read_csv(ROOT / "data/features.csv.gz")
    for _, row in frame[frame.source == source].sample(n=3, random_state=42).iterrows():
        stay = load_stay(row.stay_id, float(row.at_hour))
        request = PredictionRequest(
            patient=stay["patient"],
            at_hour=float(row.at_hour),
            readings=stay["readings"],
        )
        inferred = run_prediction(request)
        expected = float(
            predict(
                bundle,
                np.array([[row[name] for name in bundle["features"]]], dtype=float),
            )[0]
        )
        assert inferred["status"] == "predicted"
        assert abs(inferred["predicted_risk"] - expected) < 1e-6


def test_extraction_audit_counts_unique_dialysis_stays_not_diagnosis_matches(tmp_path):
    from aki.extract import Writer
    from aki.schema import Patient
    from aki.storage import connect

    path = tmp_path / "audit.sqlite3"
    initialize(path)
    with connect(path) as con:
        writer = Writer(con, "mimic")
        writer.stay("s1", "p1", "h1", 48, Patient(age=60, chronic_dialysis=True), {})
        writer.stay("s2", "p2", "h1", 48, Patient(age=60), {})
        writer.counts["known_chronic_dialysis"] = 3
        report = writer.finish()
        assert report["known_chronic_dialysis"] == 1
        assert report["known_chronic_dialysis_evidence_matches"] == 3
