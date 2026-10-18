"""Optional Gemini explanations of computed facts; never an AKI predictor."""

import json
import os
import re

import httpx

from . import config  # noqa: F401

# Shared config initializes the project .env.

DEFAULT_MODEL = "gemini-3.5-flash-lite"
SYSTEM = (
    "Explain an ICU kidney-warning result to a nontechnical demonstration audience "
    "in two or three short sentences, at most 75 words. Use only the supplied facts. "
    "No numbers: the application shows exact numbers separately. Do not name AI providers, APIs or setup. Do not diagnose, "
    "prescribe treatment, invent future outcomes, claim a patient is safe, or claim "
    "the model prevents injury. If urgent_current_review is true, explicitly say "
    "'urgent' and ask for clinical review regardless of the kidney-warning flag. "
    "A model warning is a prediction, not confirmed injury. Return JSON with one "
    "string property named summary."
)


def settings():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key.lower() in ("your_key_here", "paste_your_key_here", "your_gemini_api_key"):
        key = ""
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", model):
        raise ValueError("Invalid Gemini model identifier")
    return key, model


def summary_status():
    try:
        key, model = settings()
        return {
            "configured": bool(key),
            "model": model,
            "purpose": "Plain-language explanation only",
        }
    except ValueError:
        return {"configured": False, "model": None, "purpose": "Invalid model setting"}


def summary_facts(result):
    q = result["data_quality"]["latest_measurements"]
    return {
        "status": result["status"],
        "kidney_warning": result["alert"],
        "urgent_current_review": result["clinical_summary"]["urgent_review_required"],
        "risk_percent": result["predicted_risk_percent"],
        "creatinine_injury_observed": result["clinical_assessment"][
            "creatinine_aki_observed"
        ],
        "urine_injury_observed": result["clinical_assessment"]["urine_aki_observed"],
        "latest_creatinine": result["clinical_assessment"]["latest_creatinine"],
        "observed_reference_creatinine": result["clinical_assessment"][
            "observed_reference_creatinine"
        ],
        "reference_is_known_healthy_baseline": False,
        "recent_bun": q.get("bun", {}).get("value"),
        "recent_blood_pressure_map": q.get("map", {}).get("value"),
        "missing_measurements": result["data_quality"]["missing_inputs"],
    }


def explain_result(result, *, client=None):
    facts = summary_facts(result)
    clinical = result["clinical_summary"]
    fallback = clinical["message"]
    if clinical["current_findings"]:
        fallback = (
            " ".join(f["message"] for f in clinical["current_findings"])
            + " "
            + fallback
        )
    response = {
        "summary": fallback,
        "provider": "local",
        "headline": clinical["headline"],
        "facts": facts,
        "reason_code": "missing_key",
    }
    try:
        key, model = settings()
    except ValueError:
        return {**response, "reason_code": "invalid_model"}
    if not key:
        return response
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [
            {"role": "user", "parts": [{"text": json.dumps(facts, allow_nan=False)}]}
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
                "additionalProperties": False,
            },
        },
    }
    owned = client is None
    client = httpx.Client(timeout=12, follow_redirects=False) if owned else client
    try:
        received = client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json=payload,
        )
        received.raise_for_status()
        candidate = received.json()["candidates"][0]
        if candidate.get("finishReason") != "STOP":
            return {**response, "reason_code": "incomplete_response"}
        text = "".join(
            part.get("text", "")
            for part in candidate["content"]["parts"]
            if not part.get("thought")
        )
        value = json.loads(text)["summary"].strip()
        # Exact figures always come from the backend. Reject invented digits,
        # guarantees and disappearance of an urgent review instruction.
        if (
            not 10 <= len(value) <= 1000
            or len(value.split()) > 90
            or re.search(
                r"\d|\bsafe\b|\bguarantee\w*\b|\bno risk\b|gemini|google|api key",
                value,
                re.IGNORECASE,
            )
            or (facts["urgent_current_review"] and "urgent" not in value.lower())
        ):
            return {**response, "reason_code": "unsupported_explanation"}
        return {
            **response,
            "summary": value,
            "provider": "gemini",
            "model": model,
            "reason_code": None,
        }
    except httpx.TimeoutException:
        return {**response, "reason_code": "timeout"}
    except httpx.HTTPError:
        return {**response, "reason_code": "provider_unavailable"}
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return {**response, "reason_code": "invalid_response"}
    finally:
        if owned:
            client.close()
