"""Plot-point, timeline and output checks for the judge's graph report."""

import base64
import json
import re
import xml.etree.ElementTree as ET

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from aki.clinical import creatinine_history
from aki.config import ROOT
from aki.dataset import observed_endpoint
from aki.showcase import collect_cases, plot_frame
from aki.storage import load_stay


@pytest.fixture(scope="module")
def cases():
    return collect_cases()[0]


def test_every_real_creatinine_point_matches_available_record(cases):
    for case in [c for c in cases if c["kind"] == "patient"]:
        stay = load_stay(case["stay_id"])
        _assert_record_parity(case, stay)


def _assert_record_parity(case, stay):
    for frame in case["frames"]:
        actual = [
            [h, v]
            for h, _, v in creatinine_history(
                stay["patient"], stay["readings"], frame["hour"]
            )
            if h >= 0
        ]
        assert frame["creatinine"] == actual
        assert all(h <= frame["hour"] for h, _ in frame["creatinine"])


def test_real_risk_points_match_preserved_training_audit_probabilities(cases):
    saved = pd.read_csv(ROOT / "reports/eicu_internal_predictions.csv")
    saved = saved[saved.stay_id == "eicu-2361839"]
    matched = 0
    for frame in cases[0]["frames"]:
        row = saved[saved.at_hour == frame["hour"]]
        if frame["risk"] is not None and not row.empty:
            assert frame["risk"] == round(float(row.predicted_risk.iloc[0]) * 100, 2)
            matched += 1
    assert matched == len(saved) and matched > 0


def test_outcome_marker_is_actual_sample_time_and_lead_is_not_invented(cases):
    stay = load_stay("eicu-2361839")
    actual = observed_endpoint(
        stay["patient"], stay["readings"], stay["duration_hours"]
    )
    assert cases[0]["outcome_hour"] == actual["measurement_hour"]
    assert cases[0]["outcome_hour"] - cases[0]["selected_hour"] == pytest.approx(18.35)


def test_missing_scores_are_null_instead_of_zero(cases):
    assert any(frame["risk"] is None for frame in cases[0]["frames"])
    for frame in cases[0]["frames"]:
        if frame["status"] != "predicted":
            assert frame["risk"] is None


def test_synthetic_comparison_uses_real_model_predictions_without_fake_outcomes(cases):
    stable, rising = [c for c in cases if c["kind"] == "illustrative"]
    assert stable["outcome_hour"] is None and rising["outcome_hour"] is None
    assert stable["frames"][0]["risk"] == 8.93
    assert rising["frames"][0]["risk"] == 45.84
    assert not stable["frames"][0]["alert"] and rising["frames"][0]["alert"]


def test_plot_labels_match_quantities_and_future_is_separate(cases):
    case = cases[0]
    index = next(i for i, f in enumerate(case["frames"]) if f["hour"] == 150)
    figure = plot_frame(case, index, False)
    assert len(figure.axes) == 2
    assert "mg/dL" in figure.axes[0].get_ylabel()
    assert "%" in figure.axes[1].get_ylabel()
    assert figure.axes[1].get_ylim() == (0, 100)
    assert all(
        text.get_text() != "Kidney injury recorded" for text in figure.axes[0].texts
    )
    plt.close(figure)


def test_generated_report_contains_real_svg_plots_and_no_provider_branding():
    path = ROOT / "reports/judge_showcase.html"
    if not path.exists():
        pytest.skip("Build graph report before artifact verification")
    html = path.read_text()
    data = json.loads(re.search(r'id="data">(.*?)</script>', html, re.DOTALL)[1])
    count = 0
    for case in data["cases"]:
        for frame in case["frames"]:
            for plot in frame["plots"].values():
                svg = ET.fromstring(base64.b64decode(plot.split(",", 1)[1]))
                assert svg.tag.endswith("svg")
                assert len(svg.findall(".//{http://www.w3.org/2000/svg}path")) > 5
                count += 1
    assert count > 20
    assert "gemini" not in html.lower()
    assert "GEMINI_API_KEY" not in html


def test_report_control_logic_for_every_frame():
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None or not (ROOT / "reports/judge_showcase.html").exists():
        pytest.skip("Node and the built graph report are needed for control checks")
    checked = subprocess.run(
        [node, str(ROOT / "scripts/check_showcase.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_real_patients_have_distinct_varied_reproducible_forecasts(cases):
    from collections import Counter

    from aki.dataset import label_window

    patients = [c for c in cases if c["kind"] == "patient"]
    assert len(patients) == len({c["patient_id"] for c in patients}) == 15
    assert len({c["hospital_id"] for c in patients}) >= 6
    assert Counter(c["pattern"] for c in patients) == {
        "warning_before_injury": 5,
        "no_warning_no_injury": 4,
        "warning_without_injury": 3,
        "injury_without_warning": 3,
    }
    selected_frames = [
        next(f for f in c["frames"] if f["hour"] == c["selected_hour"])
        for c in patients
    ]
    assert min(f["risk"] for f in selected_frames) < 10
    assert max(f["risk"] for f in selected_frames) > 50
    assert min(f["creatinine"][-1][1] for f in selected_frames) < 0.8
    assert max(f["creatinine"][-1][1] for f in selected_frames) > 2
    patient_details = [load_stay(c["stay_id"])["patient"] for c in patients]
    assert len({p.sex for p in patient_details}) >= 2
    assert (
        max(p.age for p in patient_details) - min(p.age for p in patient_details) >= 30
    )
    saved = pd.read_csv(ROOT / "reports/eicu_internal_predictions.csv")
    for case in patients:
        frame = next(f for f in case["frames"] if f["hour"] == case["selected_hour"])
        assert frame["status"] == "predicted"
        assert frame["alert"] == case["selected_alert"]
        row = saved[
            (saved.stay_id == case["stay_id"]) & (saved.at_hour == frame["hour"])
        ].iloc[0]
        assert frame["risk"] == round(float(row.predicted_risk) * 100, 2)
        stay = load_stay(case["stay_id"])
        endpoint = observed_endpoint(
            stay["patient"], stay["readings"], stay["duration_hours"]
        )
        assert case["outcome_hour"] == (
            endpoint["measurement_hour"] if endpoint else None
        )
        label, _ = label_window(
            stay["readings"], stay["duration_hours"], frame["hour"], endpoint
        )
        assert label == case["selected_label"]
        assert frame["followup_status"] == (
            "injury_recorded" if label else "no_injury_recorded"
        )
        if label:
            assert 6 <= case["outcome_hour"] - case["selected_hour"] <= 24
        else:
            assert stay["duration_hours"] >= frame["hour"] + 24
            assert any(
                r.creatinine is not None
                and frame["hour"] + 18 <= r.hour <= frame["hour"] + 24
                for r in stay["readings"]
            )


def test_negative_cases_reveal_real_later_tests_without_fake_injury_marker(cases):
    case = next(c for c in cases if c.get("pattern") == "no_warning_no_injury")
    index = next(
        i for i, f in enumerate(case["frames"]) if f["hour"] == case["selected_hour"]
    )
    figure = plot_frame(case, index, True)
    assert any(line.get_label() == "Later records" for line in figure.axes[0].lines)
    assert all(
        text.get_text() != "Kidney injury recorded" for text in figure.axes[0].texts
    )
    plt.close(figure)


@pytest.fixture
def navigation_report(tmp_path):
    (tmp_path / "showcase_manifest.json").write_text(
        json.dumps(
            {
                "model_sha256": "model-a",
                "cases": [
                    {"id": "real" if i == 1 else f"patient_{i}", "kind": "patient"}
                    for i in range(1, 16)
                ]
                + [{"id": "stable", "kind": "illustrative"}],
            }
        )
    )
    return tmp_path


def test_report_commands_cycle_real_patients_and_open_resets(navigation_report):
    from aki.showcase_navigation import select_report

    reports = navigation_report
    first = select_report(reports)
    assert first[:2] == (1, 15)
    assert first[2].endswith("#patient=real")
    assert select_report(reports, "next")[:2] == (2, 15)
    assert (
        (reports / "showcase_open_url.txt").read_text().endswith("#patient=patient_2")
    )
    assert select_report(reports, "next")[:2] == (3, 15)
    for number in range(4, 16):
        assert select_report(reports, "next")[:2] == (number, 15)
    assert select_report(reports, "next")[:2] == (1, 15)
    select_report(reports, "next")
    assert select_report(reports)[:2] == (1, 15)
    assert (reports / "showcase_open_url.txt").read_text().startswith("file:///")


@pytest.mark.parametrize(
    "cursor",
    [
        None,
        "{invalid",
        "[]",
        '{"model_sha256":"old-model","patient":"patient_3"}',
        '{"model_sha256":"model-a","patient":"unknown"}',
    ],
)
def test_report_next_recovers_from_missing_or_stale_cursor(navigation_report, cursor):
    from aki.showcase_navigation import select_report

    if cursor is not None:
        (navigation_report / "showcase_cursor.json").write_text(cursor)
    assert select_report(navigation_report, "next")[:2] == (2, 15)


def test_summary_service_failure_keeps_all_patient_explanations(monkeypatch, tmp_path):
    import copy

    from aki import showcase, summaries

    frame = {
        "hour": 12,
        "risk": 8.0,
        "alert": False,
        "status": "predicted",
        "explanation": "An explanation from measured inputs.",
        "_result": {},
        "creatinine": [[0, 0.8], [12, 0.8]],
        "threshold": 17,
        "current_findings": [],
    }
    cases = [
        {
            "id": f"test_{i}",
            "kind": "illustrative",
            "label": f"Example {i}",
            "selected_hour": 12,
            "outcome_hour": None,
            "end_hour": 12,
            "later_creatinine": [],
            "frames": [copy.deepcopy(frame)],
            "origin": "Illustrative",
        }
        for i in range(3)
    ]
    calls = []

    def unavailable(result):
        calls.append(result)
        return {
            "provider": "local",
            "reason_code": "provider_unavailable",
            "summary": "A service fallback.",
        }

    monkeypatch.setattr(showcase, "REPORTS", tmp_path)
    monkeypatch.setattr(
        showcase, "collect_cases", lambda: (cases, {"model_sha256": "test"})
    )
    monkeypatch.setattr(showcase, "build_fingerprint", lambda _: "test")
    monkeypatch.setattr(summaries, "explain_result", unavailable)
    showcase.build_showcase(include_ai=True)
    assert len(calls) == 1
    assert all(c["frames"][0]["explanation"] == frame["explanation"] for c in cases)
    assert (tmp_path / "judge_showcase.html").exists()


def test_all_varied_patient_data_exports_as_strict_json(cases):
    exported = json.loads(json.dumps(cases, allow_nan=False))
    assert len([c for c in exported if c["kind"] == "patient"]) == 15
    assert all(c["end_hour"] >= c["selected_hour"] for c in exported)
