"""Run one bounded development-only improvement study; never overwrite a model."""

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aki.artifacts import atomic_json
from aki.config import DATA, MODEL_PATH, REPORTS
from aki.improvement import challenger_configs, development_only, qualify_development
from aki.robustness import development_stress_cases


def main():
    model_hash = hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()
    bundle = joblib.load(MODEL_PATH)
    configs = challenger_configs(bundle["metadata"]["selected_algorithm"])
    protocol = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "model_sha256": model_hash,
        "source": bundle["metadata"]["training_source"],
        "features_sha256": hashlib.sha256(
            (DATA / "features.csv.gz").read_bytes()
        ).hexdigest(),
        "candidates": configs,
        "partition_policy": "Only incumbent source development patients; no calibration, test, or opposite-source outcomes are used.",
        "validation": "3 patient-isolated folds and 3 hospital-isolated folds; purge all held-hospital patient IDs from each fitting fold.",
        "selection_score": "AUPRC - 0.5*creatinine-stress-p95 - 0.25*missing-group-stress-p95, averaged equally across the two fold families.",
        "qualification_gate": "Mean score gain >=.01, no family AUPRC drop >.01, no Brier increase >.005, no creatinine-stress increase >.02, improve >=4/6 fold scores.",
        "deployment": "Do not replace production automatically; record an eligible challenger for concrete review.",
        "limit": "Bounded exploratory comparison on previously used development data; not fresh external validation. No context-only predictor is silently activated.",
    }
    # Persist choices before reading development outcomes or fitting challengers.
    atomic_json(REPORTS / "improvement_protocol.json", protocol)
    data = development_only(pd.read_csv(DATA / "features.csv.gz"), bundle["metadata"])
    with threadpool_limits(limits=2):
        stress = development_stress_cases(data)
        if stress.empty:
            raise ValueError("No development stress cases")
        result = qualify_development(data, bundle["features"], configs, stress)
    assert hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() == model_hash
    result.update(
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "model_sha256": model_hash,
            "source": bundle["metadata"]["training_source"],
            "development_patients": int(data.patient_id.nunique()),
            "development_hospitals": int(data.hospital_id.nunique()),
            "development_windows": len(data),
            "protocol": "reports/improvement_protocol.json",
        }
    )
    atomic_json(REPORTS / "improvement_study.json", result)
    print(
        "Qualified challenger:",
        result["qualified_candidate"] or "none; preserve incumbent",
    )


if __name__ == "__main__":
    main()
