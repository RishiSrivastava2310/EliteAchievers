"""Plain-language clinical facts, kept separate from the future-risk model."""

from .clinical import known_readings

POTASSIUM_GUIDELINE = "https://www.ukkidney.org/sites/default/files/FINAL%20VERSION%20-%20UKKA%20CLINICAL%20PRACTICE%20GUIDELINE%20-%20MANAGEMENT%20OF%20HYPERKALAEMIA%20IN%20ADULTS%20-%20191223.pdf"


def summarize(result, readings, at_hour):
    clinical, status = result["clinical_assessment"], result["status"]
    if status == "predicted":
        headline = (
            "Early kidney warning"
            if result["alert"]
            else "Below the kidney warning threshold"
        )
        message = (
            f"Estimated chance of a first new kidney injury in the next 24 hours: "
            f"{result['predicted_risk_percent']:.2f}%. "
            "This describes future kidney risk; it does not label the patient's overall condition."
        )
    elif status == "aki_already_observed":
        latest_stage = clinical["latest_creatinine_stage"]
        if latest_stage or clinical["urine_stage"]:
            headline = "Kidney injury found in the available readings"
            message = "Review the kidney findings already recorded. A first-new-injury forecast is not shown."
        else:
            headline = "Earlier kidney injury is recorded"
            message = "The latest readings do not repeat the earlier kidney-injury rule. A first-new-injury forecast is not shown."
    elif status == "outside_new_aki_cohort":
        headline = "This prediction does not apply"
        message = (
            "Dialysis is recorded in this history. The model predicts a first new kidney injury."
            if clinical["rrt_observed"] or clinical["dialysis_history_observed"]
            else "This model supports ICU hours 12 to 168. Review the current readings separately."
        )
    else:
        headline = "More information is needed"
        message = "A recent creatinine result, an earlier comparison and enough other measurements are needed to calculate risk."

    # Use the latest measurement time and the latest available correction at that
    # measurement time. An older delayed result cannot override a newer sample.
    labs = [r for r in known_readings(readings, at_hour) if r.potassium is not None]
    findings = []
    if labs:
        latest = max(labs, key=lambda row: (row.hour, row.available_hour))
        if latest.potassium >= 6.0:
            severity = "very high" if latest.potassium >= 6.5 else "high"
            age = at_hour - latest.hour
            findings.append(
                {
                    "code": "high_potassium",
                    "priority": "urgent_review",
                    "measurement": "potassium",
                    "value": latest.potassium,
                    "unit": "mmol/L",
                    "measurement_hour": latest.hour,
                    "available_hour": latest.available_hour,
                    "age_hours": round(age, 3),
                    "message": (
                        f"The latest reported potassium is {severity}: {latest.potassium:g} mmol/L "
                        f"(sample {age:g} hours ago). Ask the ICU team to review it urgently. "
                        "No newer potassium is supplied; this does not prove the level is still high."
                    ),
                    "source": POTASSIUM_GUIDELINE,
                }
            )
    urgent = bool(findings)
    kidney_headline = headline
    if urgent:
        headline = "High potassium needs urgent review"
    return {
        "headline": headline,
        "kidney_headline": kidney_headline,
        "message": message,
        "urgent_review_required": urgent,
        "review_required": urgent
        or result["alert"]
        or status != "predicted"
        or bool(
            result.get("input_sensitivity")
            and result["input_sensitivity"]["review_required"]
        ),
        "current_findings": findings,
        "meaning": "Current recorded findings and future kidney warnings are separate. Missing information is not a normal result.",
    }
