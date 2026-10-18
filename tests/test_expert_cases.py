"""Adversarial clinical tests with an independent exact-arithmetic reference."""

from fractions import Fraction
from itertools import permutations

import numpy as np
import pytest

from aki.clinical import assess, creatinine_events, urine_window
from aki.dataset import label_window
from aki.features import build_features
from aki.schema import Patient, PredictionRequest, Reading
from aki.service import run_prediction


def snapshot_oracle(patient, readings, cutoff):
    # Independent pairwise definition with decimal-exact arithmetic; no production
    # clinical/feature helper is called by this reference.
    state = {}
    if patient.baseline_hour is not None and patient.baseline_hour <= cutoff:
        state[patient.baseline_hour] = Fraction(str(patient.baseline_creatinine))
    for row in sorted(readings, key=lambda r: (r.available_hour, r.hour)):
        if (
            row.hour <= cutoff
            and row.available_hour <= cutoff
            and row.creatinine is not None
        ):
            state[row.hour] = Fraction(str(row.creatinine))
    result = {}
    for time, value in state.items():
        prior = [(t, v) for t, v in state.items() if time - 168 <= t < time]
        if not prior:
            continue
        qualifies = any(
            value * 2 >= v * 3 or (t >= time - 48 and value - v >= Fraction(3, 10))
            for t, v in prior
        )
        if qualifies:
            ratio = value / min(v for _, v in prior)
            result[time] = 3 if ratio >= 3 or value >= 4 else 2 if ratio >= 2 else 1
    return result, state


@pytest.mark.parametrize("seed", range(32))
def test_random_delays_and_revisions_match_independent_decimal_reference(seed):
    rng = np.random.default_rng(seed)
    times = sorted(rng.choice(np.arange(0, 181, 6), size=9, replace=False))
    rows = []
    for time in times:
        lag = int(rng.integers(0, 15))
        rows.append(
            Reading(
                hour=int(time),
                available_hour=int(time) + lag,
                creatinine=int(rng.integers(4, 51)) / 10,
            )
        )
        if rng.random() < 0.5:
            rows.append(
                Reading(
                    hour=int(time),
                    available_hour=int(time) + lag + 5,
                    creatinine=int(rng.integers(4, 51)) / 10,
                )
            )
    patient = Patient(
        age=60,
        **({"baseline_hour": -24, "baseline_creatinine": 0.8} if seed % 2 else {}),
    )
    cutoffs = sorted({0, *(r.available_hour for r in rows)})
    snapshots = {cutoff: snapshot_oracle(patient, rows, cutoff) for cutoff in cutoffs}
    for cutoff in cutoffs:
        expected, state = snapshots[cutoff]
        actual = {
            event["measurement_hour"]: event
            for event in creatinine_events(patient, rows, cutoff)
        }
        assert {time: event["stage"] for time, event in actual.items()} == expected
        for time, event in actual.items():
            earliest = min(
                t for t in cutoffs if t <= cutoff and time in snapshots[t][0]
            )
            assert event["documented_hour"] == earliest
            assert event["creatinine"] == float(state[time])


def test_still_qualifying_correction_preserves_first_actual_recognition():
    patient = Patient(age=60)
    rows = [
        Reading(hour=0, creatinine=0.8),
        Reading(hour=6, creatinine=1.2),
        Reading(hour=6, available_hour=8, creatinine=1.4),
    ]
    event = creatinine_events(patient, rows, 8)[0]
    assert event["documented_hour"] == 6
    assert event["latest_result_available_hour"] == 8
    assert event["creatinine"] == 1.4


def test_repeated_identical_baseline_entry_cannot_move_first_recognition_later():
    rows = [
        Reading(hour=0, creatinine=0.8),
        Reading(hour=6, creatinine=1.2),
        Reading(hour=0, available_hour=10, creatinine=0.8),
    ]
    assert (
        assess(Patient(age=60), rows, 10)["first_documented_creatinine_aki_hour"] == 6
    )


def test_retracted_abnormal_result_is_not_retained_as_true_current_aki():
    rows = [
        Reading(hour=0, creatinine=0.8),
        Reading(hour=6, creatinine=1.2),
        Reading(hour=6, available_hour=8, creatinine=0.9),
    ]
    assert assess(Patient(age=60), rows, 6)["creatinine_aki_observed"]
    assert not assess(Patient(age=60), rows, 8)["creatinine_aki_observed"]


@pytest.mark.parametrize("hours", [12, 18, 24])
def test_confirmed_anuria_needs_complete_duration_but_not_body_weight(hours):
    patient = Patient(age=60)
    rows = [Reading(hour=hours, urine_output_ml=0, urine_interval_hours=hours)]
    result = assess(patient, rows, hours)
    assert result["urine_stage"] == 3
    assert result["urine_12h"]["complete"]
    # Zero volume has a zero rate for any positive body weight.
    assert result["urine_12h"]["rate_ml_kg_h"] == 0
    assert result["urine_12h"]["volume_ml"] == 0
    assert not result["eligible_for_new_aki_forecast"]


def test_zero_urine_without_a_collection_interval_is_still_unknown():
    result = assess(Patient(age=60), [Reading(hour=12, urine_output_ml=0)], 12)
    assert result["urine_stage"] is None
    assert not result["urine_12h"]["complete"]


def test_eleven_confirmed_zero_hours_plus_missing_hour_is_not_proof_of_anuria_12h():
    rows = [
        Reading(hour=h, urine_output_ml=0, urine_interval_hours=1) for h in range(2, 13)
    ]
    result = assess(Patient(age=60), rows, 12)
    # Six complete zero-output hours qualify, but the 12-hour gap prevents anuria staging.
    assert result["urine_stage"] == 1
    assert result["urine_12h"]["coverage_hours"] == 11
    assert not result["urine_12h"]["complete"]


def test_positive_partial_collection_is_not_prorated_into_a_rate():
    result = assess(
        Patient(age=60, weight_kg=70),
        [Reading(hour=18, urine_output_ml=180, urine_interval_hours=18)],
        18,
    )
    assert result["urine_stage"] is None
    assert result["urine_12h"]["rate_ml_kg_h"] is None


def test_boundary_spanning_overlap_cannot_be_hidden_by_window_clipping():
    rows = [
        Reading(hour=h, urine_output_ml=0, urine_interval_hours=1) for h in range(1, 7)
    ]
    rows.append(Reading(hour=2.5, urine_output_ml=1000, urine_interval_hours=12))
    result = urine_window(Patient(age=60, weight_kg=70), rows, 6, 6)
    assert not result["complete"]
    assert result["rate_ml_kg_h"] is None
    assert "Overlapping" in result["reason"]


def test_duplicate_with_missing_duration_is_order_independent():
    rows = [
        Reading(hour=6, urine_output_ml=0, urine_interval_hours=6),
        Reading(hour=6, urine_output_ml=0),
    ]
    results = []
    for order in permutations(rows):
        body = PredictionRequest(
            patient=Patient(age=60, weight_kg=70), at_hour=6, readings=list(order)
        )
        results.append(assess(body.patient, body.readings, 6))
    assert results[0] == results[1]
    assert results[0]["urine_stage"] == 1


def test_true_later_unknown_duration_revision_still_removes_earlier_coverage():
    rows = [
        Reading(hour=6, urine_output_ml=0, urine_interval_hours=6),
        Reading(hour=6, available_hour=8, urine_output_ml=0),
    ]
    assert not urine_window(
        Patient(age=60, weight_kg=70), rows, 6, 6, knowledge_hour=8
    )["complete"]


@pytest.mark.parametrize("volume,expected", [(0, 3), (21, 2), (35, 0), (36, 0)])
def test_exact_urine_thresholds_are_strict(volume, expected):
    rows = [
        Reading(hour=h, urine_output_ml=volume, urine_interval_hours=1)
        for h in range(1, 25)
    ]
    assert assess(Patient(age=60, weight_kg=70), rows, 24)["urine_stage"] == expected


@pytest.mark.parametrize("seed", range(16))
def test_urine_stage_matches_independent_complete_hourly_volume_reference(seed):
    rng = np.random.default_rng(seed)
    volumes = rng.choice([0, 10, 20, 21, 34, 35, 36, 70], size=24)
    rows = [
        Reading(hour=h, urine_output_ml=int(v), urine_interval_hours=1)
        for h, v in enumerate(volumes, 1)
    ]
    expected = 0
    if sum(volumes[-6:]) < 35 * 6:
        expected = 1
    if sum(volumes[-12:]) < 35 * 12:
        expected = 2
    if sum(volumes[-12:]) == 0 or sum(volumes) < 21 * 24:
        expected = 3
    result = assess(Patient(age=60, weight_kg=70), rows, 24)
    assert result["urine_stage"] == expected


def test_unknown_weight_blocks_weighted_oliguria_but_not_confirmed_anuria_api():
    body = PredictionRequest(
        patient=Patient(age=60),
        at_hour=12,
        readings=[
            Reading(hour=h, urine_output_ml=0, urine_interval_hours=1)
            for h in range(1, 13)
        ],
    )
    result = run_prediction(body)
    assert result["status"] == "aki_already_observed"
    assert result["clinical_assessment"]["urine_stage"] == 3
    assert result["predicted_risk"] is None


@pytest.mark.parametrize(
    "onset,expected",
    [
        (12, (None, "aki_sample_already_collected")),
        (12.0001, (1, "positive")),
        (36, (1, "positive")),
        (36.0001, (0, "negative")),
    ],
)
def test_forecast_horizon_is_open_at_start_and_closed_at_24_hours(onset, expected):
    rows = [Reading(hour=36, creatinine=0.8)]
    assert label_window(rows, 48, 12, {"measurement_hour": onset}) == expected


def test_observed_positive_before_early_exit_does_not_require_full_negative_followup():
    endpoint = {"measurement_hour": 20}
    assert label_window([], 21, 12, endpoint) == (1, "positive")
    assert label_window([], 21, 12, None) == (None, "incomplete_followup")


@pytest.mark.parametrize("seed", range(8))
def test_reordering_and_future_additions_do_not_change_available_features(seed):
    rng = np.random.default_rng(seed)
    rows = [
        Reading(hour=h, available_hour=h + 1, creatinine=0.8 + h / 100, map=80 - h)
        for h in (0, 6, 12)
    ]
    future = [*rows, Reading(hour=24, available_hour=30, creatinine=5, map=30)]
    rng.shuffle(future)
    left, _, _ = build_features(Patient(age=60), rows, 13)
    right, _, _ = build_features(Patient(age=60), future, 13)
    for key in left:
        assert left[key] == pytest.approx(right[key], nan_ok=True)


def test_six_hours_of_exact_zero_output_has_zero_rate_for_any_positive_weight():
    result = assess(
        Patient(age=60), [Reading(hour=6, urine_output_ml=0, urine_interval_hours=6)], 6
    )
    assert result["urine_6h"]["rate_ml_kg_h"] == 0
    assert result["urine_stage"] == 1


def test_nonzero_urine_requires_weight_for_normalized_oliguria():
    result = assess(
        Patient(age=60),
        [Reading(hour=6, urine_output_ml=120, urine_interval_hours=6)],
        6,
    )
    assert result["urine_6h"]["complete"]
    assert result["urine_6h"]["volume_ml"] == 120
    assert result["urine_6h"]["rate_ml_kg_h"] is None
    assert result["urine_stage"] is None
