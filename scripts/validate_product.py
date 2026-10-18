"""Produce a short product-validation case report from genuine backend responses."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aki.artifacts import atomic_json
from aki.schema import PredictionRequest
from aki.service import model_info, run_prediction


def main():
    stable = json.loads((ROOT / "examples/stable.json").read_text())
    concerning = json.loads((ROOT / "examples/concerning_trend.json").read_text())
    high_potassium = json.loads(json.dumps(stable))
    high_potassium["readings"][-1]["potassium"] = 6.7
    cases = [
        ("Steady kidney readings", stable, "predicted", False, False),
        (
            "Rising pattern triggers an early warning",
            concerning,
            "predicted",
            True,
            False,
        ),
        (
            "Normal-looking value with a meaningful acute rise",
            {
                "patient": {"age": 60},
                "at_hour": 12,
                "readings": [
                    {"hour": 0, "creatinine": 0.6},
                    {"hour": 12, "creatinine": 0.9},
                ],
            },
            "aki_already_observed",
            False,
            False,
        ),
        (
            "More history requested when previous creatinine is absent",
            {
                "patient": {"age": 60},
                "at_hour": 12,
                "readings": [
                    {"hour": 12, "creatinine": 0.8, "map": 80, "heart_rate": 80}
                ],
            },
            "insufficient_data",
            False,
            False,
        ),
        (
            "Confirmed zero urine is recognized without body weight",
            {
                "patient": {"age": 60},
                "at_hour": 12,
                "readings": [
                    {"hour": 12, "urine_output_ml": 0, "urine_interval_hours": 12}
                ],
            },
            "aki_already_observed",
            False,
            False,
        ),
        (
            "High potassium is shown alongside the kidney forecast",
            high_potassium,
            "predicted",
            None,
            True,
        ),
        (
            "Current finding remains visible when no risk can be calculated",
            {
                "patient": {"age": 60},
                "at_hour": 12,
                "readings": [{"hour": 12, "creatinine": 0.8, "potassium": 6.7}],
            },
            "insufficient_data",
            False,
            True,
        ),
        (
            "Dialysis history is routed to the appropriate status",
            {
                "patient": {"age": 60, "chronic_dialysis": True},
                "at_hour": 12,
                "readings": [{"hour": 12, "creatinine": 4.2}],
            },
            "outside_new_aki_cohort",
            False,
            False,
        ),
    ]
    results = []
    for title, body, expected_status, expected_alert, expected_urgent in cases:
        result = run_prediction(PredictionRequest.model_validate(body))
        assert result["status"] == expected_status, title
        assert expected_alert is None or result["alert"] is expected_alert, title
        assert (
            result["clinical_summary"]["urgent_review_required"] is expected_urgent
        ), title
        if result["status"] != "predicted":
            assert result["predicted_risk"] is None, title
        results.append(
            {
                "case": title,
                "passed": True,
                "status": result["status"],
                "early_kidney_warning": result["alert"],
                "urgent_current_finding": expected_urgent,
                "risk_percent": result["predicted_risk_percent"],
                "headline": result["clinical_summary"]["headline"],
            }
        )
        print("PASS:", title)
    info = model_info()
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "model_sha256": info["model_sha256"],
        "input_provenance": "Synthetic clinical-use scenarios; predictions use the trained demo model.",
        "cases_passed": len(results),
        "cases": results,
        "claim_supported": "Backend behavior in the listed patient scenarios, with separate future-risk and current-finding outputs.",
    }
    atomic_json(ROOT / "reports/product_validation.json", report)
    lines = [
        "# Product validation",
        "",
        f"**{len(results)}/{len(results)} patient-use scenarios passed.**",
        "These checks use the trained model and real backend, with clearly labelled illustrative inputs.",
        "",
        "| Patient scenario | Result |",
        "|---|---|",
        *[f"| {r['case']} | PASS: {r['headline']} |" for r in results],
        "",
        "The system produces an early kidney warning, recognizes existing kidney",
        "injury, asks for missing history, handles dialysis exclusions and keeps",
        "important current potassium results visible beside the forecast.",
        "",
        "Run verify.bat --http to repeat regression, data, patient-case and live API checks.",
        "See product_validation.json for machine-readable evidence and IMPROVEMENTS.md",
        "for the measured alert-policy comparison. These patient-case checks validate",
        "the stated product behavior; clinical outcome performance is reported separately.",
    ]
    (ROOT / "reports/PRODUCT_VALIDATION.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
