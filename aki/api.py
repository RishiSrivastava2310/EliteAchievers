"""FastAPI JSON backend; no custom frontend."""

import json
import os
from collections import Counter
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .config import MODEL_PATH, ROOT
from .csvio import parse_csv
from .diagnostics import readiness
from .http_security import BodyLimitMiddleware, require_api_key
from .schema import (
    RANGES,
    UNITS,
    BatchPredictionRequest,
    PredictionRequest,
    PredictionResponse,
    StoredBatchRequest,
    StoredPredictionResponse,
)
from .service import evaluation, model_info, prediction_history, run_prediction
from .storage import audits, initialize, list_stays, load_stay


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(
    title="AKI Early Warning API",
    version=__version__,
    description="Research demo: 24-hour new-AKI prediction, current criteria checks, and source replay.",
    lifespan=lifespan,
)
app.add_middleware(BodyLimitMiddleware)
protected = APIRouter(dependencies=[Depends(require_api_key)])
origins = [
    v.strip() for v in os.environ.get("AKI_CORS_ORIGINS", "").split(",") if v.strip()
]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Do not echo patient input, non-finite JSON values or exception objects.
    detail = [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(FileNotFoundError)
async def unavailable(request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "model_available": MODEL_PATH.exists(),
        "mode": "research_demo",
        "authentication": "shared_api_key"
        if os.environ.get("AKI_API_KEY")
        else "local_demo_no_auth",
    }


@protected.get("/v1/model")
def get_model():
    return model_info()


@protected.get("/v1/alert-profiles")
def get_alert_profiles():
    from .alerting import read_alert_profiles

    return read_alert_profiles(model_info()["model_sha256"])


@protected.get("/v1/summary-status")
def get_summary_status():
    from .summaries import summary_status

    return summary_status()


@protected.post("/v1/summarize")
def summarize_prediction(body: PredictionRequest):
    from .summaries import explain_result

    return explain_result(run_prediction(body))


@protected.get("/v1/input-schema")
def input_schema():
    return {
        "request_schema": PredictionRequest.model_json_schema(),
        "units": UNITS,
        "ranges": RANGES,
        "time_basis": "Hours relative to ICU admission; negatives are pre-ICU history",
        "missing_values": "Omit a measurement or use null. Never use zero for missing.",
        "primary_endpoint": "Creatinine-defined AKI; complete urine intervals support separate current-criteria checks",
    }


@protected.post("/v1/predict", response_model=PredictionResponse)
def predict_json(body: PredictionRequest):
    return run_prediction(body)


@protected.post("/v1/predict/csv", response_model=PredictionResponse)
async def predict_csv(
    request: Request, at_hour: float | None = Query(default=None, ge=0, le=8760)
):
    if request.headers.get("content-type", "").split(";")[0].strip() not in (
        "text/csv",
        "text/plain",
    ):
        raise HTTPException(415, "Send CSV text with Content-Type: text/csv")
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > 2_000_000:
            raise HTTPException(413, "CSV exceeds 2 MB")
    try:
        body = parse_csv(payload.decode("utf-8-sig"), at_hour)
    except (ValueError, UnicodeError) as exc:
        details = (
            "; ".join(error["msg"] for error in exc.errors())
            if hasattr(exc, "errors")
            else str(exc)
        )
        raise HTTPException(422, details) from exc
    # Run CPU work off the event loop.
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(run_prediction, body)


@protected.get("/v1/stays")
def stays(
    source: str | None = Query(default=None, pattern="^(mimic|eicu)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, min_length=1, max_length=80),
):
    return list_stays(source, limit, offset, search=search)


def get_stay(stay_id, at_hour=None):
    try:
        return load_stay(stay_id, at_hour)
    except KeyError as exc:
        raise HTTPException(404, "Stay not found") from exc


@protected.get("/v1/stays/{stay_id}/timeline")
def timeline(stay_id: str, at_hour: float = Query(ge=0, le=8760)):
    stay = get_stay(stay_id, at_hour)
    if at_hour > stay["duration_hours"]:
        raise HTTPException(422, "Selected hour is beyond ICU stay")
    return {
        **{k: v for k, v in stay.items() if k not in ("patient", "readings")},
        "patient": stay["patient"].model_dump(),
        "at_hour": at_hour,
        "readings": [r.model_dump(exclude_none=True) for r in stay["readings"]],
        "notice": "Historical demo data, not a live ICU feed",
    }


@protected.get("/v1/stays/{stay_id}/outcome")
def outcome(stay_id: str):
    from .clinical import creatinine_events
    from .dataset import observed_endpoint

    stay = get_stay(stay_id)
    events = creatinine_events(
        stay["patient"], stay["readings"], stay["duration_hours"]
    )
    return {
        "stay_id": stay_id,
        "retrospective_only": True,
        "first_documented_creatinine_aki": events[0] if events else None,
        "first_qualifying_sample": observed_endpoint(
            stay["patient"], stay["readings"], stay["duration_hours"]
        ),
        "forecast_endpoint_time": "measurement_hour of first_qualifying_sample",
        "note": "Future outcome overlay only; never included in prediction-time inputs",
    }


@protected.post("/v1/stays/{stay_id}/predict", response_model=StoredPredictionResponse)
def predict_stay(stay_id: str, at_hour: float = Query(ge=0, le=8760)):
    stay = get_stay(stay_id, at_hour)
    if at_hour > stay["duration_hours"]:
        raise HTTPException(422, "Selected hour is beyond ICU stay")
    if not stay["readings"]:
        raise HTTPException(422, "No observations available by selected hour")
    request = PredictionRequest(
        patient=stay["patient"], at_hour=at_hour, readings=stay["readings"]
    )
    return {"stay_id": stay_id, "source": stay["source"], **run_prediction(request)}


@protected.get("/v1/stays/{stay_id}/risk-history")
def risk_history(stay_id: str, through_hour: float = Query(default=48, ge=12, le=168)):
    stay = get_stay(stay_id, through_hour)
    end = min(through_hour, stay["duration_hours"])
    known = [r for r in stay["readings"] if r.hour <= end and r.available_hour <= end]
    if not known:
        return {
            "stay_id": stay_id,
            "through_hour": end,
            "prediction_interval_hours": 6,
            "items": [],
            "notice": "No observations available by selected hour",
        }
    body = PredictionRequest(patient=stay["patient"], at_hour=end, readings=known)
    return {"stay_id": stay_id, **prediction_history(body)}


@protected.get("/v1/metrics")
def metrics():
    return evaluation()


@protected.get("/v1/data-quality")
def data_quality():
    return audits()


@protected.get("/v1/examples")
def examples():
    return {
        "cases": {
            name: json.loads(
                (ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8")
            )
            for name in ("stable", "concerning_trend", "existing_aki")
        },
        "provenance": "Synthetic input scenarios; predictions come from the real-data demo model",
    }


@app.get("/ready")
def ready():
    report = readiness()
    return JSONResponse(status_code=200 if report["ready"] else 503, content=report)


@protected.post("/v1/predict/history")
def predict_history(body: PredictionRequest):
    return prediction_history(body)


@protected.post("/v1/predict/batch", response_model=list[PredictionResponse])
def predict_batch(body: BatchPredictionRequest):
    return [run_prediction(request) for request in body.requests]


@protected.post("/v1/stays/predict/batch")
def predict_stored_batch(body: StoredBatchRequest):
    items, counts = [], Counter()
    for stay_id in body.stay_ids:
        try:
            prediction = predict_stay(stay_id, body.at_hour)
            items.append({"stay_id": stay_id, "prediction": prediction, "error": None})
            counts[prediction["status"]] += 1
            if prediction["alert"]:
                counts["alerts"] += 1
            if prediction["clinical_summary"]["urgent_review_required"]:
                counts["urgent_reviews"] += 1
        except HTTPException as exc:
            if exc.status_code not in (404, 422):
                raise
            items.append(
                {
                    "stay_id": stay_id,
                    "prediction": None,
                    "error": {"status_code": exc.status_code, "detail": exc.detail},
                }
            )
            counts["unavailable"] += 1
    return {
        "at_hour": body.at_hour,
        "requested_stays": len(body.stay_ids),
        "items": items,
        "counts": dict(counts),
        "count_scope": "Requested stay IDs at this selected hour only; not all ICU patients",
    }


app.include_router(protected)


def export_openapi():
    target = ROOT / "docs" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
