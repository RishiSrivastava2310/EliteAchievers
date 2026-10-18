"""Optional text provider is isolated from the predictive model and identifiers."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from aki.api import app
from aki.config import ROOT
from aki.schema import PredictionRequest
from aki.service import run_prediction
from aki.summaries import explain_result, summary_status


@pytest.fixture
def result():
    return run_prediction(
        PredictionRequest.model_validate_json(
            (ROOT / "examples/stable.json").read_text()
        )
    )


def response(text, finish="STOP"):
    return {
        "candidates": [
            {
                "finishReason": finish,
                "content": {"parts": [{"text": json.dumps({"summary": text})}]},
            }
        ]
    }


def test_missing_key_uses_existing_plain_summary_without_network(monkeypatch, result):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: pytest.fail("No provider call should occur")
        )
    ) as client:
        answer = explain_result(result, client=client)
    assert answer["provider"] == "local"
    assert answer["summary"] == result["clinical_summary"]["message"]


def test_provider_gets_only_computed_facts_and_key_stays_in_header(monkeypatch, result):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    seen = []
    text = "The model is below its kidney warning threshold. Continue reviewing the measured trends."

    def handle(request):
        seen.append(request)
        assert request.headers["x-goog-api-key"] == "unit-test-key"
        assert "unit-test-key" not in str(request.url)
        body = json.loads(request.content)
        facts = json.loads(body["contents"][0]["parts"][0]["text"])
        assert (
            "patient_id" not in facts and "readings" not in facts and "age" not in facts
        )
        return httpx.Response(200, json=response(text))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        answer = explain_result(result, client=client)
    assert len(seen) == 1
    assert answer["provider"] == "gemini"
    assert answer["summary"] == text
    assert result["predicted_risk_percent"] == 8.93


@pytest.mark.parametrize(
    "text",
    [
        "The risk is 99% and the kidney result is normal.",
        "The patient is safe and has no risk.",
        "Gemini says the kidneys look fine.",
        "Google generated this medical summary.",
    ],
)
def test_unsupported_numbers_reassurance_or_provider_branding_use_local_fallback(
    monkeypatch, result, text
):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response(text))
        )
    ) as client:
        answer = explain_result(result, client=client)
    assert answer["provider"] == "local"
    assert answer["reason_code"] == "unsupported_explanation"


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_failure_does_not_break_patient_explanation(
    monkeypatch, result, status
):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"error": "unit-test-key"})
        )
    ) as client:
        answer = explain_result(result, client=client)
    assert answer["provider"] == "local"
    assert "unit-test-key" not in json.dumps(answer)


def test_urgent_current_finding_cannot_disappear_from_provider_summary(
    monkeypatch, result
):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    result["clinical_summary"]["urgent_review_required"] = True
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=response("The model is below its warning threshold.")
            )
        )
    ) as client:
        answer = explain_result(result, client=client)
    assert answer["reason_code"] == "unsupported_explanation"


def test_truncated_or_malformed_response_has_readable_fallback(monkeypatch, result):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"candidates": []})
        )
    ) as client:
        answer = explain_result(result, client=client)
    assert answer["provider"] == "local"


def test_model_name_cannot_change_the_provider_host_or_path(monkeypatch, result):
    monkeypatch.setenv("GEMINI_MODEL", "../not-a-model")
    assert not summary_status()["configured"]
    assert explain_result(result)["reason_code"] == "invalid_model"


def test_summary_endpoints_require_configured_api_key_and_do_not_expose_provider_key(
    monkeypatch,
):
    monkeypatch.setenv("AKI_API_KEY", "test-api-key")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    body = json.loads((ROOT / "examples/stable.json").read_text())
    with TestClient(app) as client:
        assert client.post("/v1/summarize", json=body).status_code == 401
        assert client.get("/v1/summary-status").status_code == 401
        headers = {"X-API-Key": "test-api-key"}
        status = client.get("/v1/summary-status", headers=headers).json()
        answer = client.post("/v1/summarize", json=body, headers=headers)
    assert answer.status_code == 200
    assert answer.json()["provider"] == "local"
    assert status["configured"] is False
