"""Exercise a real localhost Uvicorn server, then shut it down cleanly."""

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


AUTH_HEADERS = {}


def call(base, path, body=None, content_type="application/json", headers=None):
    payload = (
        None
        if body is None
        else (json.dumps(body).encode() if not isinstance(body, str) else body.encode())
    )
    with urlopen(
        Request(
            base + path,
            data=payload,
            headers={
                "Content-Type": content_type,
                **(AUTH_HEADERS if headers is None else headers),
            },
        ),
        timeout=15,
    ) as response:
        return response.status, json.load(response)


def main():
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = (reports / "http_smoke.log").open("w", encoding="utf-8")
    test_key = secrets.token_urlsafe(24)
    AUTH_HEADERS["X-API-Key"] = test_key
    environment = {
        **os.environ,
        "AKI_API_KEY": test_key,
        "AKI_CORS_ORIGINS": "http://localhost:5173",
        "GEMINI_API_KEY": "",
    }
    use_launcher = "--launcher" in sys.argv
    command = (
        ["cmd.exe", "/d", "/c", "start_api.bat", "--port", str(port)]
        if use_launcher
        else [
            sys.executable,
            "-m",
            "uvicorn",
            "aki.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ]
    )
    proc = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=log,
        stderr=log,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("Uvicorn stopped; see reports/http_smoke.log")
            try:
                status, health = call(base, "/health")
                if health["model_available"]:
                    break
            except (URLError, OSError):
                time.sleep(0.25)
        else:
            raise RuntimeError("API did not become ready")
        status, ready = call(base, "/ready")
        assert status == 200 and ready["ready"]
        try:
            call(base, "/v1/stays", headers={})
            raise AssertionError("Protected route accepted a missing key")
        except HTTPError as exc:
            assert exc.code == 401
        with urlopen(
            Request(
                base + "/v1/predict",
                method="OPTIONS",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type,x-api-key",
                },
            ),
            timeout=15,
        ) as response:
            assert response.status == 200
            assert (
                response.headers["Access-Control-Allow-Origin"]
                == "http://localhost:5173"
            )
        body = json.loads((ROOT / "examples/stable.json").read_text(encoding="utf-8"))
        status, prediction = call(base, "/v1/predict", body)
        assert status == 200 and prediction["status"] == "predicted"
        (reports / "http_prediction.json").write_text(
            json.dumps(prediction, indent=2), encoding="utf-8"
        )
        assert prediction["input_sensitivity"]["tested_variants"] > 0
        assert prediction["clinical_summary"]["headline"]
        critical_body = json.loads(json.dumps(body))
        critical_body["readings"][-1]["potassium"] = 6.7
        status, critical = call(base, "/v1/predict", critical_body)
        assert status == 200 and critical["clinical_summary"]["urgent_review_required"]
        assert critical["clinical_summary"]["current_findings"][0]["value"] == 6.7
        status, batch = call(base, "/v1/predict/batch", {"requests": [body, body]})
        assert status == 200 and batch == [prediction, prediction]
        status, supplied_history = call(base, "/v1/predict/history", body)
        assert (
            status == 200
            and supplied_history["items"][-1]["predicted_risk"]
            == prediction["predicted_risk"]
        )
        status, csv_prediction = call(
            base,
            "/v1/predict/csv",
            (ROOT / "examples/template.csv").read_text(encoding="utf-8"),
            "text/csv",
        )
        assert status == 200 and csv_prediction["status"] == "predicted"
        status, explanation = call(base, "/v1/summarize", body)
        assert status == 200 and explanation["summary"]
        assert explanation["provider"] == "local"
        status, summary_settings = call(base, "/v1/summary-status")
        assert status == 200 and not summary_settings["configured"]
        status, model = call(base, "/v1/model")
        assert status == 200
        status, profiles = call(base, "/v1/alert-profiles")
        assert status == 200 and profiles["model_sha256"] == model["model_sha256"]
        assert profiles["default_profile"] == "standard"
        assert prediction["alert_options"]["standard"]["alert"] == prediction["alert"]
        if "fewer_alerts" in prediction["alert_options"]:
            assert (
                prediction["alert_options"]["fewer_alerts"]["threshold"]
                > prediction["alert_threshold"]
            )
        status, _metrics = call(base, "/v1/metrics")
        assert status == 200
        status, stays = call(base, "/v1/stays?source=mimic&limit=5")
        assert stays["total"] > 0
        import pandas as pd

        first = pd.read_csv(ROOT / "data/features.csv.gz").iloc[0]
        status, timeline = call(
            base, f"/v1/stays/{first.stay_id}/timeline?at_hour={first.at_hour}"
        )
        assert all(
            r["hour"] <= first.at_hour and r["available_hour"] <= first.at_hour
            for r in timeline["readings"]
        )
        status, replay = call(
            base, f"/v1/stays/{first.stay_id}/predict?at_hour={first.at_hour}", {}
        )
        assert status == 200 and replay["status"] == "predicted"
        status, stored_batch = call(
            base,
            "/v1/stays/predict/batch",
            {
                "stay_ids": [str(first.stay_id), "missing"],
                "at_hour": float(first.at_hour),
            },
        )
        assert (
            status == 200
            and stored_batch["items"][0]["prediction"]["status"] == "predicted"
        )
        assert stored_batch["items"][1]["error"]["status_code"] == 404
        status, search = call(base, "/v1/stays?search=" + str(first.stay_id))
        assert status == 200 and search["total"] >= 1
        status, outcome = call(base, f"/v1/stays/{first.stay_id}/outcome")
        assert status == 200 and outcome["retrospective_only"]
        assert "first_qualifying_sample" in outcome
        status, history = call(
            base,
            f"/v1/stays/{first.stay_id}/risk-history?through_hour={min(48, first.at_hour)}",
        )
        assert status == 200 and all(
            item["at_hour"] <= first.at_hour for item in history["items"]
        )
        future = {
            **body,
            "readings": [*body["readings"], {"hour": 24, "creatinine": 5}],
        }
        try:
            call(base, "/v1/predict", future)
            raise AssertionError("Future data was accepted")
        except HTTPError as exc:
            assert exc.code == 422
        results = {
            "status": "passed",
            "health": health,
            "readiness": "passed",
            "optional_api_key": "passed",
            "frontend_cors_preflight": "passed",
            "batch_prediction": "passed",
            "stored_batch_prediction": "passed",
            "patient_search": "passed",
            "launch_mode": "start_api.bat" if use_launcher else "uvicorn module",
            "caller_history": "passed",
            "input_sensitivity": "passed",
            "alert_profile_tradeoff": "passed",
            "plain_clinical_summary_and_current_potassium": "passed",
            "plain_explanation_endpoint": "passed",
            "json_prediction": "passed",
            "csv_prediction": "passed",
            "stored_replay": "passed",
            "risk_history": "passed",
            "retrospective_outcome": "passed",
            "future_input_rejection": "passed",
            "model_sha256": model["model_sha256"],
            "training_source": model["training_source"],
            "estimated_example_risk_percent": prediction["predicted_risk_percent"],
        }
        report_name = "http_launcher_smoke.json" if use_launcher else "http_smoke.json"
        (reports / report_name).write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )
        print(json.dumps(results, indent=2))
    finally:
        if use_launcher and os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()


if __name__ == "__main__":
    main()
