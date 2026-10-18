import pytest
from pydantic import ValidationError

from aki.clinical import assess, creatinine_events, urine_window
from aki.features import build_features
from aki.schema import Patient, PredictionRequest, Reading


def patient(**kwargs):
    return Patient(age=60, **kwargs)


def test_small_absolute_rise_can_meet_aki_even_at_normal_looking_values():
    rows = [Reading(hour=0, creatinine=0.6), Reading(hour=12, creatinine=0.9)]
    result = assess(patient(), rows, 12)
    assert result["creatinine_aki_observed"]
    assert result["latest_creatinine_stage"] == 1
    assert not result["eligible_for_new_aki_forecast"]


def test_relative_rise_without_point_three_also_meets_aki():
    rows = [Reading(hour=0, creatinine=0.4), Reading(hour=24, creatinine=0.6)]
    assert assess(patient(), rows, 24)["latest_creatinine_stage"] == 1


def test_slow_small_rise_outside_48h_is_not_automatically_aki():
    rows = [Reading(hour=0, creatinine=1.5), Reading(hour=60, creatinine=1.8)]
    assert not assess(patient(), rows, 60)["creatinine_aki_observed"]


def test_future_low_baseline_cannot_relabel_an_earlier_value():
    rows = [Reading(hour=0, creatinine=1.5), Reading(hour=24, creatinine=1.0)]
    assert not creatinine_events(patient(), rows, 24)


def test_delayed_result_cannot_trigger_early_detection_or_features():
    rows = [
        Reading(hour=0, creatinine=0.8),
        Reading(hour=6, available_hour=14, creatinine=1.2),
    ]
    assert not assess(patient(), rows, 12)["creatinine_aki_observed"]
    assert assess(patient(), rows, 14)["first_documented_creatinine_aki_hour"] == 14
    f, _, _ = build_features(patient(), rows, 12)
    assert f["creatinine_last"] == 0.8


def test_future_observations_cannot_change_features():
    historical = [
        Reading(hour=0, creatinine=0.8, map=80),
        Reading(hour=12, creatinine=0.9, map=75),
    ]
    future = [*historical, Reading(hour=24, creatinine=5, map=35)]
    f1, _, _ = build_features(patient(), historical, 12)
    f2, _, _ = build_features(patient(), future, 12)
    for key in f1:
        assert f1[key] == pytest.approx(f2[key], nan_ok=True)


def test_api_contract_rejects_future_input_instead_of_silently_using_it():
    with pytest.raises(ValidationError, match="Future"):
        PredictionRequest(
            patient=patient(), at_hour=12, readings=[Reading(hour=13, creatinine=0.8)]
        )


def test_missing_urine_is_unknown_not_anuria():
    result = assess(patient(weight_kg=70), [Reading(hour=0, creatinine=0.8)], 12)
    assert result["urine_stage"] is None


def test_six_complete_hours_of_low_urine_meets_stage_one():
    rows = [
        Reading(hour=h, urine_output_ml=20, urine_interval_hours=1) for h in range(1, 7)
    ]
    result = assess(patient(weight_kg=70), rows, 6)
    assert result["urine_stage"] == 1
    assert result["urine_6h"]["complete"]


def test_missing_hour_prevents_urine_diagnosis():
    rows = [
        Reading(hour=h, urine_output_ml=0, urine_interval_hours=1)
        for h in (1, 2, 3, 5, 6)
    ]
    assert assess(patient(weight_kg=70), rows, 6)["urine_stage"] is None


def test_overlapping_urine_intervals_are_not_double_counted():
    rows = [
        Reading(hour=4, urine_output_ml=0, urine_interval_hours=4),
        Reading(hour=6, urine_output_ml=0, urine_interval_hours=4),
    ]
    assert not urine_window(patient(weight_kg=70), rows, 6, 6)["complete"]


def test_urine_volume_without_known_collection_interval_is_not_hourly():
    rows = [Reading(hour=6, urine_output_ml=0)]
    assert assess(patient(weight_kg=70), rows, 6)["urine_stage"] is None


def test_dialysis_is_outside_incident_prediction_cohort():
    assert not assess(
        patient(chronic_dialysis=True), [Reading(hour=0, creatinine=0.8)], 12
    )["eligible_for_new_aki_forecast"]
    assert not assess(patient(), [Reading(hour=0, rrt=1, creatinine=0.8)], 12)[
        "eligible_for_new_aki_forecast"
    ]


def test_pre_icu_history_can_supply_comparison():
    rows = [Reading(hour=-24, creatinine=0.8), Reading(hour=0, creatinine=1.2)]
    assert assess(patient(), rows, 0)["creatinine_aki_observed"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 80])
def test_invalid_creatinine_is_rejected(value):
    with pytest.raises(ValidationError):
        Reading(hour=0, creatinine=value)


def test_provided_baseline_requires_timestamp():
    with pytest.raises(ValidationError):
        Patient(age=60, baseline_creatinine=0.8)


def test_documented_urine_volume_is_not_made_into_a_complete_rate():
    import math

    rows = [Reading(hour=2, urine_output_ml=100), Reading(hour=6, urine_output_ml=50)]
    f, _, urine = build_features(patient(weight_kg=70), rows, 6)
    assert f["urine_output_ml_documented_6h"] == 150
    assert not urine["complete"]
    missing, _, _ = build_features(patient(), [Reading(hour=0, creatinine=0.8)], 6)
    assert math.isnan(missing["urine_output_ml_documented_6h"])


def test_dialysis_catheter_does_not_imply_actual_dialysis():
    from aki.extract import history_is_dialysis, treatment_is_rrt

    assert treatment_is_rrt("renal|dialysis|hemodialysis|for acute renal failure")
    assert treatment_is_rrt("renal|dialysis|C V V H D")
    assert not treatment_is_rrt(
        "renal|dialysis|insertion of venous catheter for dialysis"
    )
    assert not treatment_is_rrt("renal|dialysis|arteriovenous shunt for renal dialysis")
    assert history_is_dialysis("renal failure - hemodialysis")
    assert not history_is_dialysis("chronic kidney disease stage 3")


def test_dialysis_history_only_changes_eligibility_when_available():
    rows = [
        Reading(hour=0, creatinine=0.8),
        Reading(hour=0, available_hour=20, dialysis_history=1),
    ]
    assert assess(patient(), rows, 12)["eligible_for_new_aki_forecast"]
    assert not assess(patient(), rows, 24)["eligible_for_new_aki_forecast"]


def test_revised_result_is_used_only_after_revision_is_available():
    rows = [
        Reading(hour=0, creatinine=0.8),
        Reading(hour=0, available_hour=8, creatinine=0.9),
    ]
    early, _, _ = build_features(patient(), rows, 6)
    later, _, _ = build_features(patient(), rows, 10)
    assert early["creatinine_last"] == 0.8
    assert later["creatinine_last"] == 0.9
    assert later["creatinine_mean_24h"] == 0.9


def test_urine_counts_and_mixed_stool_are_not_treated_as_urine_volumes():
    from aki.extract import urine_cell_is_volume

    assert urine_cell_is_volume("I&O|Output (ml)|Urine Output-Foley")
    assert not urine_cell_is_volume("I&O|Output (ml)|Urine Count")
    assert not urine_cell_is_volume("I&O|Output (ml)|Urine Occurrence")
    assert not urine_cell_is_volume("I&O|Output (ml)|Mixed Urine/Stool Volume")
