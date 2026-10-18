"""Independent clinical examples, timing counterexamples and cohort regression cases."""

import numpy as np
import pandas as pd
import pytest

from aki.clinical import assess, creatinine_events, urine_window
from aki.dataset import label_window, observed_endpoint
from aki.features import build_features, quality
from aki.schema import Patient, Reading
from aki.train import META, evaluate, grouped_split

PATIENT = Patient(age=60, weight_kg=70)


@pytest.mark.parametrize(
    "baseline,current,hours,stage",
    [
        (0.6, 0.9, 48, 1),  # >=0.3 even inside a lab's normal range
        (0.6, 0.89, 48, 0),
        (0.4, 0.6, 168, 1),  # ratio criterion, without a 0.3 rise
        (0.4, 0.6, 169, None),
        (1.5, 1.8, 49, 0),  # absolute criterion has expired
        (0.9, 1.8, 72, 2),
        (0.9, 2.7, 72, 3),
        (3.8, 4.1, 24, 3),
        (4.1, 4.1, 24, 0),  # chronically high is not proof of acute injury
        (1.5, 1.0, 24, 0),  # later recovery is never a preceding baseline
    ],
)
def test_kdigo_creatinine_boundary_examples(baseline, current, hours, stage):
    rows = [
        Reading(hour=0, creatinine=baseline),
        Reading(hour=hours, creatinine=current),
    ]
    result = assess(PATIENT, rows, hours)
    assert result["latest_creatinine_stage"] == stage


def test_late_baseline_can_establish_aki_but_never_before_it_arrives():
    rows = [
        Reading(hour=0, available_hour=10, creatinine=0.8),
        Reading(hour=6, available_hour=6, creatinine=1.2),
    ]
    assert not assess(PATIENT, rows, 8)["creatinine_aki_observed"]
    event = creatinine_events(PATIENT, rows, 10)[0]
    assert event["measurement_hour"] == 6
    assert event["documented_hour"] == 10
    assert assess(PATIENT, rows, 10)["latest_creatinine_stage"] == 1


def test_future_revision_cannot_change_past_assessment():
    rows = [Reading(hour=0, creatinine=0.8), Reading(hour=6, creatinine=1.2)]
    revision = Reading(hour=6, available_hour=20, creatinine=0.9)
    assert assess(PATIENT, rows, 12) == assess(PATIENT, [*rows, revision], 12)
    assert not assess(PATIENT, [*rows, revision], 20)["creatinine_aki_observed"]


def test_two_creatinines_too_far_apart_are_not_a_valid_acute_comparison():
    rows = [Reading(hour=-168, creatinine=0.8), Reading(hour=24, creatinine=0.9)]
    result = assess(PATIENT, rows, 24)
    assert not result["creatinine_comparison_available"]
    assert result["latest_creatinine_stage"] is None


def test_feature_comparison_window_is_relative_to_sample_not_prediction_time():
    rows = [Reading(hour=-36, creatinine=0.8), Reading(hour=12, creatinine=1.0)]
    f, _, _ = build_features(PATIENT, rows, 24)
    assert f["creatinine_change_48h"] == pytest.approx(0.2)


@pytest.mark.parametrize(
    "hours,amount,expected",
    [(6, 20, 1), (12, 20, 2), (12, 0, 3), (24, 15, 3), (6, 35, 0)],
)
def test_complete_urine_intervals_and_exact_threshold(hours, amount, expected):
    rows = [
        Reading(hour=h, urine_output_ml=amount, urine_interval_hours=1)
        for h in range(1, hours + 1)
    ]
    assert assess(PATIENT, rows, hours)["urine_stage"] == expected


def test_urine_correction_replaces_volume_instead_of_creating_overlap():
    rows = [
        Reading(hour=6, urine_output_ml=0, urine_interval_hours=6),
        Reading(hour=6, available_hour=8, urine_output_ml=420, urine_interval_hours=6),
    ]
    assert urine_window(PATIENT, rows, 6, 6)["rate_ml_kg_h"] == 0
    corrected = urine_window(PATIENT, rows, 6, 6, knowledge_hour=8)
    assert corrected["complete"]
    assert corrected["rate_ml_kg_h"] == 1


def test_recovered_or_delayed_urine_aki_does_not_reenter_first_episode_cohort():
    rows = [
        Reading(hour=6, available_hour=10, urine_output_ml=0, urine_interval_hours=6),
        Reading(hour=12, urine_output_ml=420, urine_interval_hours=6),
    ]
    result = assess(PATIENT, rows, 12)
    assert result["urine_stage"] == 0
    assert result["urine_aki_observed"]
    assert not result["eligible_for_new_aki_forecast"]


def test_old_measurements_do_not_count_as_current_model_coverage():
    q = quality(
        PATIENT,
        [Reading(hour=-24, bun=20, map=80), Reading(hour=12, creatinine=0.9)],
        24,
    )
    assert q["available_model_inputs"] == 1
    assert "bun" in q["missing_inputs"]
    assert q["latest_measurements"]["bun"]["age_hours"] == 48


def test_already_drawn_unreported_abnormal_sample_is_not_future_aki():
    rows = [
        Reading(hour=0, creatinine=0.8),
        Reading(hour=10, available_hour=20, creatinine=1.2),
        Reading(hour=36, creatinine=1.3),
    ]
    endpoint = observed_endpoint(PATIENT, rows, 48)
    assert endpoint["measurement_hour"] == 10
    assert not assess(PATIENT, rows, 12)["creatinine_aki_observed"]
    assert label_window(rows, 48, 12, endpoint) == (
        None,
        "aki_sample_already_collected",
    )


def test_dialysis_inside_horizon_is_censored_before_creatinine_can_be_lowered():
    rows = [
        Reading(hour=0, creatinine=0.8),
        Reading(hour=20, rrt=1),
        Reading(hour=36, creatinine=0.8),
    ]
    assert label_window(rows, 48, 12, None) == (None, "rrt_before_observed_outcome")


def test_dialysis_after_observed_aki_does_not_erase_positive_outcome():
    endpoint = {"measurement_hour": 20, "documented_hour": 22}
    assert label_window([Reading(hour=24, rrt=1)], 48, 12, endpoint) == (1, "positive")


def test_negative_requires_late_draw_not_late_entry_of_old_sample():
    rows = [Reading(hour=10, available_hour=32, creatinine=0.8)]
    assert label_window(rows, 48, 12, None) == (None, "incomplete_followup")
    rows.append(Reading(hour=32, available_hour=34, creatinine=0.9))
    assert label_window(rows, 48, 12, None) == (0, "negative")
    assert label_window(rows, 35, 12, None) == (None, "incomplete_followup")


def test_both_onset_timestamps_are_metadata_and_never_predictors():
    assert "onset_hour" in META
    assert "onset_documented_hour" in META


def test_lead_time_and_missed_event_denominator_are_honest():
    frame = pd.DataFrame(
        {
            "patient_id": ["a", "a", "b"],
            "stay_id": ["a", "a", "b"],
            "hospital_id": ["h"] * 3,
            "label": [1, 1, 1],
            "at_hour": [12, 18, 12],
            "onset_hour": [30, 30, 24],
            "onset_documented_hour": [35, 35, 25],
            "sex_male": [1, 1, 0],
            "sex_unknown": [0, 0, 0],
            "age": [60, 60, 50],
        }
    )
    result = evaluate(frame, np.array([0.8, 0.9, 0.1]), 0.5, bootstrap=False)
    assert result["evaluable_aki_stays"] == 2
    assert result["event_sensitivity"] == 0.5
    assert result["median_sample_lead_hours"] == 18
    assert result["median_documented_lead_hours"] == 23
    assert result["fraction_evaluable_events_warned_at_least_hours"]["18"] == 0.5


def test_new_patients_cannot_silently_replace_old_test_patients(tmp_path, monkeypatch):
    import json

    import aki.train as training

    frozen = {
        "eicu": {
            "development": ["old"],
            "calibration": ["c0", "c1"],
            "test": ["t0", "t1"],
        }
    }
    (tmp_path / "frozen_patient_splits.json").write_text(json.dumps(frozen))
    monkeypatch.setattr(training, "REPORTS", tmp_path)
    frame = pd.DataFrame(
        {
            "patient_id": ["old", "new", "c0", "c1", "t0", "t1"],
            "label": [0, 1, 0, 1, 0, 1],
        }
    )
    development, calibration, test = grouped_split(frame, "eicu")
    assert set(development.patient_id) == {"old", "new"}
    assert set(calibration.patient_id) == {"c0", "c1"}
    assert set(test.patient_id) == {"t0", "t1"}


@pytest.mark.parametrize(
    "case,baseline,values,first_hour",
    [
        ("A", 1.0, [1.3, 1.5, 2.0, 1.0], 24),
        ("B", 1.0, [1.1, 1.2, 1.4, 1.0], 72),
        ("C", 0.4, [0.5, 0.6, 0.7, 0.4], 48),
        ("D", 1.0, [1.1, 1.2, 1.3, 1.5], 168),
        ("E", 1.0, [1.3, 1.5, 1.8, 2.2], 24),
    ],
)
def test_kdigo_2012_table_7_cases_a_through_e(case, baseline, values, first_hour):
    # KDIGO chapter 2.4, Table 7: preceding baseline known at time zero.
    patient = Patient(age=60, baseline_creatinine=baseline, baseline_hour=0)
    rows = [Reading(hour=h, creatinine=v) for h, v in zip((24, 48, 72, 168), values)]
    events = creatinine_events(patient, rows, 168)
    assert min(e["measurement_hour"] for e in events) == first_hour, case


def test_unknown_admission_baseline_is_not_invented_from_future_recovery():
    # Table 7 case F needs retrospective inference; real-time code cannot know day 7.
    rows = [
        Reading(hour=h, creatinine=v)
        for h, v in zip((24, 48, 72, 168), (3, 2.6, 2.2, 1))
    ]
    result = assess(PATIENT, rows, 24)
    assert result["latest_creatinine_stage"] is None
    assert not result["creatinine_comparison_available"]
    assert not creatinine_events(PATIENT, rows, 168)
