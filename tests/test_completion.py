"""Requirements and regression checks for the completed backend integration."""

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aki.api import app
from aki.artifacts import atomic_json, atomic_model
from aki.clinical import assess, urine_window
from aki.config import ROOT
from aki.robustness import development_stress_cases, group_dropout, input_variants
from aki.schema import Patient, PredictionRequest, Reading
from aki.service import load_model, run_prediction
from aki.train import model_for


def request_body():
    return json.loads((ROOT / "examples/stable.json").read_text(encoding="utf-8"))


def test_optional_api_key_guards_all_patient_and_model_routes(monkeypatch):
    monkeypatch.setenv("AKI_API_KEY", "test-only-key")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").json()["authentication"] == "shared_api_key"
        for path in ("/v1/model", "/v1/stays", "/v1/metrics", "/v1/input-schema"):
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"X-API-Key": "wrong"}).status_code == 401
            assert (
                client.get(path, headers={"X-API-Key": "test-only-key"}).status_code
                == 200
            )
        assert client.post("/v1/predict", json=request_body()).status_code == 401
        response = client.post(
            "/v1/predict", json=request_body(), headers={"X-API-Key": "test-only-key"}
        )
        assert response.status_code == 200
        assert "test-only-key" not in response.text


def test_openapi_has_key_scheme_and_new_contract_routes():
    schema = app.openapi()
    assert (
        schema["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"
    )
    for path in ("/ready", "/v1/predict/history", "/v1/predict/batch"):
        assert path in schema["paths"]


def test_key_disabled_remains_usable_for_local_demo(monkeypatch):
    monkeypatch.delenv("AKI_API_KEY", raising=False)
    with TestClient(app) as client:
        assert client.get("/v1/model").status_code == 200


def test_request_body_limit_checks_json_and_streamed_csv():
    with TestClient(app) as client:
        assert (
            client.post(
                "/v1/predict",
                content=b" " * 2_000_001,
                headers={"Content-Type": "application/json"},
            ).status_code
            == 413
        )

        def stream():
            yield b"hour,age,creatinine\n"
            yield b" " * 2_000_001

        response = client.post(
            "/v1/predict/csv", content=stream(), headers={"Content-Type": "text/csv"}
        )
        assert response.status_code == 413


def test_batch_matches_individual_predictions_and_has_bounded_size():
    body = request_body()
    with TestClient(app) as client:
        individual = client.post("/v1/predict", json=body).json()
        response = client.post("/v1/predict/batch", json={"requests": [body, body]})
        assert response.status_code == 200
        assert response.json() == [individual, individual]
        assert (
            client.post("/v1/predict/batch", json={"requests": []}).status_code == 422
        )
        assert (
            client.post("/v1/predict/batch", json={"requests": [body] * 26}).status_code
            == 422
        )


def test_caller_history_agrees_with_past_prediction_when_future_values_exist():
    body = request_body()
    body["at_hour"] = 24
    body["readings"].append(
        {"hour": 24, "available_hour": 24, "creatinine": 1.3, "bun": 40, "map": 60}
    )
    with TestClient(app) as client:
        response = client.post("/v1/predict/history", json=body)
        assert response.status_code == 200
        points = response.json()["items"]
        first = next(x for x in points if x["at_hour"] == 12)
        expected = client.post("/v1/predict", json=request_body()).json()
        assert first["predicted_risk"] == expected["predicted_risk"]
        assert points[-1]["status"] == "aki_already_observed"


def test_future_supplied_baseline_is_hidden_from_earlier_replay_points():
    body = request_body()
    body["at_hour"] = 24
    body["patient"].update({"baseline_hour": 20, "baseline_creatinine": 0.4})
    with TestClient(app) as client:
        points = client.post("/v1/predict/history", json=body).json()["items"]
        first = next(x for x in points if x["at_hour"] == 12)
        expected = client.post("/v1/predict", json=request_body()).json()
        assert first["status"] == "predicted"
        assert first["predicted_risk"] == expected["predicted_risk"]


def test_short_stay_history_does_not_include_results_entered_after_icu_exit(
    monkeypatch,
):
    from aki import api

    monkeypatch.setattr(
        api,
        "get_stay",
        lambda *_: {
            "duration_hours": 6,
            "patient": Patient(age=60),
            "readings": [Reading(hour=5, available_hour=10, creatinine=0.8)],
        },
    )
    with TestClient(app) as client:
        response = client.get("/v1/stays/test/risk-history?through_hour=12")
        assert response.status_code == 200
        assert response.json()["items"] == []


def test_readiness_checks_model_report_and_database():
    with TestClient(app) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["ready"]
        assert all(c["ok"] for c in response.json()["checks"].values())


@pytest.mark.parametrize("payload", [b"", b"not-a-joblib", b"\x80\x04}"])
def test_corrupt_model_returns_actionable_unavailable_status(
    tmp_path, monkeypatch, payload
):
    from aki import service

    path = tmp_path / "model.joblib"
    path.write_bytes(payload)
    monkeypatch.setattr(service, "MODEL_PATH", path)
    with TestClient(app) as client:
        response = client.post("/v1/predict", json=request_body())
        assert response.status_code == 503
        assert "Model unavailable" in response.json()["detail"]


def test_readiness_rejects_mismatched_evaluation_hash(tmp_path, monkeypatch):
    from aki import diagnostics

    (tmp_path / "evaluation.json").write_text(json.dumps({"model_sha256": "wrong"}))
    monkeypatch.setattr(diagnostics, "REPORTS", tmp_path)
    with TestClient(app) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert not response.json()["checks"]["evaluation"]["ok"]


def test_model_cache_reloads_after_atomic_artifact_replacement(tmp_path, monkeypatch):
    from aki import service

    path = tmp_path / "model.joblib"
    original = load_model()
    atomic_model(path, original)
    monkeypatch.setattr(service, "MODEL_PATH", path)
    first = service.model_info()["model_sha256"]
    changed = {
        **original,
        "metadata": {**original["metadata"], "cache_reload_probe": "updated"},
    }
    atomic_model(path, changed)
    second = service.model_info()
    assert first != second["model_sha256"]
    assert second["cache_reload_probe"] == "updated"


def test_atomic_json_preserves_old_artifact_on_serialization_failure(tmp_path):
    path = tmp_path / "report.json"
    atomic_json(path, {"version": 1})
    with pytest.raises(ValueError):
        atomic_json(path, {"bad": float("nan")})
    assert json.loads(path.read_text()) == {"version": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_model_preserves_old_artifact_on_failed_dump(tmp_path, monkeypatch):
    from aki import artifacts

    path = tmp_path / "model.joblib"
    path.write_bytes(b"previous model")

    def fail(bundle, target):
        target.write_bytes(b"partial replacement")
        raise OSError("Simulated interrupted write")

    monkeypatch.setattr(artifacts.joblib, "dump", fail)
    with pytest.raises(OSError):
        atomic_model(path, {})
    assert path.read_bytes() == b"previous model"
    assert list(tmp_path.iterdir()) == [path]


def test_group_dropout_keeps_creatinine_and_original_training_rows():
    features = [
        "creatinine_last",
        "bun_last",
        "bun_age_hours",
        "map_last",
        "map_age_hours",
    ]
    x = np.tile([0.8, 20, 0, 80, 0], (100, 1))
    y = np.arange(100) % 2
    ax, ay = group_dropout(x, y, features, enabled=True)
    assert np.array_equal(ax[:100], x)
    assert np.array_equal(ay, np.concatenate([y, y]))
    assert np.all(ax[:, 0] == 0.8)
    assert np.isnan(ax[100:]).any()
    assert not np.isnan(x).any()
    assert np.array_equal(
        ax, group_dropout(x, y, features, enabled=True)[0], equal_nan=True
    )


def test_spline_model_handles_constant_and_all_missing_features():
    x = np.column_stack([np.linspace(0, 1, 40), np.zeros(40), np.full(40, np.nan)])
    y = np.arange(40) % 2
    model = model_for({"kind": "spline", "C": 0.01}).fit(x, y)
    p = model.predict_proba(x)[:, 1]
    assert np.isfinite(p).all()
    assert ((p >= 0) & (p <= 1)).all()


def test_stress_preparation_reads_only_supplied_development_patients(monkeypatch):
    from aki import storage

    requested = []
    body = PredictionRequest.model_validate(request_body())

    def fake_load(sid, hour):
        requested.append(sid)
        return {"patient": body.patient, "readings": body.readings}

    monkeypatch.setattr(storage, "load_stay", fake_load)
    frame = pd.DataFrame(
        {
            "patient_id": ["dev-a", "dev-b"],
            "stay_id": ["stay-a", "stay-b"],
            "at_hour": [12, 12],
        }
    )
    stress = development_stress_cases(frame)
    assert set(requested) <= {"stay-a", "stay-b"}
    assert set(stress.patient_id) == {"dev-a", "dev-b"}
    assert set(stress.base_index) <= set(frame.index)


def test_stress_generation_does_not_mutate_input():
    body = PredictionRequest.model_validate(request_body())
    original = body.model_dump()
    variants = list(input_variants(body.patient, body.readings, body.at_hour))
    assert variants
    assert body.model_dump() == original


def test_sensitivity_range_contains_nominal_risk_and_is_explicitly_not_confidence():
    result = run_prediction(PredictionRequest.model_validate(request_body()))
    sensitivity = result["input_sensitivity"]
    assert sensitivity["tested_variants"] > 0
    assert "not confidence intervals" in sensitivity["meaning"]
    for limits in sensitivity["ranges"].values():
        assert (
            limits["minimum_risk_percent"]
            <= result["predicted_risk_percent"]
            <= limits["maximum_risk_percent"]
        )


def test_near_current_aki_boundary_is_flagged_without_relabelling_original_input():
    body = request_body()
    body["readings"][-1]["creatinine"] = 1.08
    result = run_prediction(PredictionRequest.model_validate(body))
    assert result["status"] == "predicted"
    assert not result["clinical_assessment"]["creatinine_aki_observed"]
    assert result["input_sensitivity"]["clinical_boundary_sensitive"]
    assert result["input_sensitivity"]["review_required"]


def test_corrected_unknown_urine_interval_removes_old_invented_coverage():
    rows = [
        Reading(hour=6, urine_output_ml=0, urine_interval_hours=6),
        Reading(hour=6, available_hour=8, urine_output_ml=0),
    ]
    patient = Patient(age=60, weight_kg=70)
    assert urine_window(patient, rows, 6, 6)["complete"]
    assert not urine_window(patient, rows, 6, 6, knowledge_hour=8)["complete"]
    assert not assess(patient, rows, 8)["urine_aki_observed"]


def test_conflicting_urine_intervals_fail_even_when_volumes_are_identical():
    with pytest.raises(ValidationError, match="Conflicting urine collection intervals"):
        PredictionRequest(
            patient=Patient(age=60),
            at_hour=6,
            readings=[
                Reading(hour=6, urine_output_ml=0, urine_interval_hours=6),
                Reading(hour=6, urine_output_ml=0, urine_interval_hours=3),
            ],
        )


@pytest.mark.parametrize(
    "flag", ["ventilation", "vasopressor", "diuretic", "nephrotoxic_drug"]
)
def test_context_only_drug_and_ventilation_flags_are_accepted_and_disclosed(flag):
    body = request_body()
    body["readings"][-1][flag] = 1
    result = run_prediction(PredictionRequest.model_validate(body))
    info = load_model()["metadata"]
    assert flag in info["context_only_inputs"]
    baseline = run_prediction(PredictionRequest.model_validate(request_body()))
    assert result["predicted_risk"] == baseline["predicted_risk"]


def test_csv_weight_at_later_hour_is_not_a_baseline_weight_for_replay():
    from aki.csvio import parse_csv

    text = "hour,age,weight_kg,urine_output_ml,urine_interval_hours\n"
    text += "".join(f"{hour},60,,20,1\n" for hour in range(1, 7))
    text += "12,60,70,,\n"
    body = parse_csv(text)
    assert body.patient.weight_kg is None
    result = assess(body.patient, body.readings, 6)
    assert result["urine_6h"]["complete"]
    assert result["urine_6h"]["rate_ml_kg_h"] is None
    assert result["urine_stage"] is None


def test_csv_validation_does_not_echo_patient_row_or_id():
    text = "hour,age,patient_id,creatinine\n0,17,private-patient-id,.8\n"
    with TestClient(app) as client:
        response = client.post(
            "/v1/predict/csv", content=text, headers={"Content-Type": "text/csv"}
        )
        assert response.status_code == 422
        assert "private-patient-id" not in response.text
        assert "input_value" not in response.text


def test_invalid_download_source_cannot_overwrite_manifest(tmp_path, monkeypatch):
    import aki.download as downloader

    monkeypatch.setattr(downloader, "DATA", tmp_path)
    manifest = tmp_path / "download_manifest.json"
    manifest.write_text('{"files": [{"source": "mimic"}]}')
    before = manifest.read_bytes()
    with pytest.raises(ValueError, match="Unknown source"):
        downloader.download("mistyped")
    assert manifest.read_bytes() == before


def test_single_source_download_preserves_other_source_manifest(tmp_path, monkeypatch):
    import hashlib

    import aki.download as downloader

    payload = b"verified table"
    checksum = hashlib.sha256(payload).hexdigest()
    manifest = tmp_path / "download_manifest.json"
    manifest.write_text(
        json.dumps(
            {"files": [{"source": "mimic", "file": "old.csv.gz", "sha256": "retained"}]}
        )
    )
    monkeypatch.setattr(downloader, "DATA", tmp_path)
    monkeypatch.setattr(downloader, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        downloader,
        "SOURCES",
        {"eicu": {"base": "https://example.test/", "files": ["small.csv.gz"]}},
    )

    def fake_fetch(url):
        if url.endswith("SHA256SUMS.txt"):
            return f"{checksum}  small.csv.gz\n".encode()
        if url.endswith("LICENSE.txt"):
            return b"test license"
        return payload

    monkeypatch.setattr(downloader, "fetch", fake_fetch)
    result = downloader.download("eicu")
    assert {r["source"] for r in result["files"]} == {"mimic", "eicu"}
    assert result["files"][0]["sha256"] == "retained"


def test_patient_directory_search_is_literal_and_parameterized():
    with TestClient(app) as client:
        response = client.get("/v1/stays", params={"search": "eicu-2361839"})
        assert response.status_code == 200
        assert any(x["stay_id"] == "eicu-2361839" for x in response.json()["items"])
        for query in ("' OR 1=1 --", "%", "_"):
            result = client.get("/v1/stays", params={"search": query}).json()
            assert result["total"] == 0


def test_stored_patient_batch_preserves_valid_results_and_scopes_counts():
    body = {"stay_ids": ["eicu-2361839", "missing"], "at_hour": 150}
    with TestClient(app) as client:
        response = client.post("/v1/stays/predict/batch", json=body)
        assert response.status_code == 200
        result = response.json()
        assert result["requested_stays"] == 2
        assert result["items"][0]["prediction"]["status"] == "predicted"
        assert result["items"][1]["error"]["status_code"] == 404
        assert result["counts"]["unavailable"] == 1
        assert "Requested stay IDs" in result["count_scope"]
        assert (
            client.post(
                "/v1/stays/predict/batch", json={"stay_ids": ["x", "x"], "at_hour": 12}
            ).status_code
            == 422
        )


def test_every_accepted_patient_measurement_is_classified_in_model_metadata():
    from aki.schema import RANGES
    from aki.service import model_info

    usage = model_info()["input_usage"]
    active = set(usage["active_model_inputs"])
    criteria = set(usage["criteria_or_eligibility_inputs"])
    context = set(usage["context_only_inputs"])
    assert not (active & context or active & criteria or criteria & context)
    assert (
        set(RANGES) | set(Patient.model_fields) | {"urine_interval_hours"}
        == active | criteria | context
    )
    assert {"sodium", "glucose", "hemoglobin", "wbc"} <= context
