"""Local readiness and reproducible environment diagnostics without patient data."""

import importlib.metadata
import json
import platform
import sqlite3

from . import __version__
from .config import DB_PATH, MODEL_PATH, REPORTS


def readiness():
    from .service import load_model, model_info

    checks = {}
    try:
        bundle = load_model()
        info = model_info()
        checks["model"] = {
            "ok": True,
            "version": bundle["metadata"]["model_version"],
            "sha256": info["model_sha256"],
        }
    except (OSError, ValueError, KeyError) as exc:
        checks["model"] = {"ok": False, "reason": str(exc)}
    try:
        if not DB_PATH.is_file():
            raise FileNotFoundError("Database missing; run setup.bat")
        with sqlite3.connect(DB_PATH) as con:
            valid = con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            sources = {
                r[0]: r[1]
                for r in con.execute(
                    "SELECT source, count(*) FROM stays GROUP BY source"
                )
            }
        checks["database"] = {
            "ok": valid and {"mimic", "eicu"}.issubset(sources),
            "sources": sources,
        }
    except (OSError, sqlite3.Error) as exc:
        checks["database"] = {"ok": False, "reason": str(exc)}
    try:
        report = json.loads((REPORTS / "evaluation.json").read_text(encoding="utf-8"))
        matching = (
            checks["model"]["ok"]
            and report["model_sha256"] == checks["model"]["sha256"]
        )
        checks["evaluation"] = {
            "ok": bool(matching),
            "reason": "Model/report hashes match"
            if matching
            else "Model/report mismatch; rerun prepare",
        }
    except (OSError, ValueError, KeyError) as exc:
        checks["evaluation"] = {"ok": False, "reason": str(exc)}
    return {
        "ready": all(c["ok"] for c in checks.values()),
        "version": __version__,
        "checks": checks,
    }


def doctor_report():
    packages = {}
    for name in (
        "fastapi",
        "uvicorn",
        "pydantic",
        "numpy",
        "pandas",
        "scikit-learn",
        "joblib",
    ):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not installed"
    status = readiness()
    return {
        "python": platform.python_version(),
        "platform": platform.system(),
        "packages": packages,
        **status,
        "model_file_present": MODEL_PATH.is_file(),
        "next_step": "Run demo.bat or start_api.bat"
        if status["ready"]
        else "Run setup.bat; see individual checks",
    }
