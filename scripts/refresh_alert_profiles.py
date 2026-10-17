"""Refresh the source-calibrated alert tradeoff report without retraining."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aki.alerting import refresh_alert_profiles

if __name__ == "__main__":
    report = refresh_alert_profiles()
    for name, profile in report["profiles"].items():
        print(name, "threshold", round(profile["threshold"], 6))
        for target, result in profile["audit_evaluation"].items():
            print(
                target,
                result["confusion"],
                "sensitivity",
                round(result["sensitivity"], 3),
                "precision",
                round(result["precision"], 3),
            )
