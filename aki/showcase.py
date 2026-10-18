"""Build a portable graph report from the same model and availability-safe inputs."""

import base64
import hashlib
import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .clinical import creatinine_history, known_readings
from .config import DB_PATH, REPORTS, ROOT
from .schema import PredictionRequest
from .service import model_info, run_prediction
from .storage import load_stay

TEAL, ORANGE, INK, GRID = "#087f8c", "#c55b22", "#17324d", "#e4eaf0"


def local_story(result):
    if result["status"] != "predicted":
        return result["clinical_summary"]["message"]
    clinical = result["clinical_assessment"]
    value, reference = (
        clinical["latest_creatinine"],
        clinical["observed_reference_creatinine"],
    )
    rising = (
        value is not None and reference is not None and value - reference > 0.02 + 1e-9
    )
    if result["alert"]:
        return (
            "The kidney blood-test reading has risen from a recent observed low. "
            if rising
            else "The overall pattern of available measurements raises concern in the model. "
        ) + (
            "The model raises a warning while the available readings do not yet meet the rule for an existing kidney injury. "
            "This warning calls for review of the available readings."
        )
    return (
        "The latest blood-test reading is above a recent observed low, but the model stays below its warning threshold."
        if rising
        else "The latest kidney blood-test reading is close to its recent observed low. The model stays below its warning threshold."
    )


def make_frame(patient, readings, hour):
    patient_at_time = patient
    if patient.baseline_hour is not None and patient.baseline_hour > hour:
        patient_at_time = patient.model_copy(
            update={"baseline_creatinine": None, "baseline_hour": None}
        )
    known = known_readings(readings, hour)
    result = run_prediction(
        PredictionRequest(patient=patient_at_time, at_hour=hour, readings=known)
    )
    history = creatinine_history(patient_at_time, known, hour)
    return {
        "hour": hour,
        "risk": result["predicted_risk_percent"],
        "alert": result["alert"],
        "status": result["status"],
        "headline": result["clinical_summary"]["headline"],
        "explanation": local_story(result),
        "creatinine": [[h, v] for h, _, v in history if h >= 0],
        "current_findings": result["clinical_summary"]["current_findings"],
        "threshold": result["alert_threshold"] * 100,
        "_result": result,
    }


CASE_PATTERNS = {
    "warning_before_injury": "Early warning before recorded injury",
    "no_warning_no_injury": "Below warning level / no injury recorded in the next day",
    "warning_without_injury": "Warning for review / no injury recorded in the next day",
    "injury_without_warning": "Below warning level before a later injury sample",
}


def patient_case(
    stay,
    selected_hour,
    endpoint,
    case_id,
    label,
    expected_alert=True,
    expected_label=1,
    pattern="warning_before_injury",
):
    from .dataset import label_window, observed_endpoint

    selected_hour = float(selected_hour)
    observed = observed_endpoint(
        stay["patient"], stay["readings"], stay["duration_hours"]
    )
    actual_endpoint = observed["measurement_hour"] if observed else None
    if (actual_endpoint is None) != (endpoint is None) or (
        actual_endpoint is not None and abs(actual_endpoint - endpoint) > 1e-6
    ):
        raise ValueError(
            "The observed outcome changed; run prepare to refresh examples."
        )
    endpoint = actual_endpoint
    actual_label, _ = label_window(
        stay["readings"], stay["duration_hours"], selected_hour, observed
    )
    if actual_label != expected_label:
        raise ValueError("The selected follow-up cannot be reproduced; run prepare.")
    # Keep the original full replay; other patients focus on a recent 36h history
    # and the next 24h so the portable report remains quick to navigate.
    start = 12 if case_id == "real" else max(12, int(selected_hour) - 36)
    end = min(stay["duration_hours"], selected_hour + 24)
    if case_id == "real":
        end = min(stay["duration_hours"], endpoint + 12, max(180, endpoint + 6))
    replay_end = end if case_id == "real" else selected_hour
    hours = list(range(start, int(replay_end) + 1, 6))
    frames = [make_frame(stay["patient"], stay["readings"], h) for h in hours]
    chosen = next((f for f in frames if abs(f["hour"] - selected_hour) < 1e-6), None)
    if (
        chosen is None
        or chosen["status"] != "predicted"
        or chosen["alert"] != expected_alert
    ):
        raise ValueError("The selected forecast cannot be reproduced; run prepare.")
    for frame in frames:
        outcome_label, _ = label_window(
            stay["readings"], stay["duration_hours"], frame["hour"], observed
        )
        frame["followup_status"] = (
            "injury_already_recorded"
            if endpoint is not None and endpoint <= frame["hour"]
            else "injury_recorded"
            if outcome_label == 1
            else "no_injury_recorded"
            if outcome_label == 0
            else "incomplete_followup"
        )
    final_history = creatinine_history(stay["patient"], stay["readings"], end)
    source = "eICU" if stay["source"] == "eicu" else "MIMIC-IV"
    return {
        "id": case_id,
        "kind": "patient",
        "label": label,
        "patient_id": stay["patient_id"],
        "stay_id": stay["stay_id"],
        "hospital_id": stay["hospital_id"],
        "pattern": pattern,
        "selected_label": expected_label,
        "selected_alert": expected_alert,
        "origin": f"Real historical patient / {source} public demo",
        "description": CASE_PATTERNS[pattern]
        + ". Replay the recorded measurements and compare the next-day outcome.",
        "selected_hour": float(selected_hour),
        "outcome_hour": endpoint,
        "end_hour": end,
        "later_creatinine": [[h, v] for h, _, v in final_history if 0 <= h <= end],
        "frames": frames,
        "source_note": "Selected historical examples show varied patterns, not overall accuracy. Later records never enter an earlier prediction.",
    }


def select_patient_rows(saved, threshold, primary_patient_id):
    """Fixed scenario counts and hospital diversity, without fitting any weights."""
    used = {primary_patient_id}
    hospitals = set()
    selected = []
    groups = (
        ("warning_before_injury", 1, True, 4),
        ("no_warning_no_injury", 0, False, 4),
        ("warning_without_injury", 0, True, 3),
        ("injury_without_warning", 1, False, 3),
    )
    for pattern, label, alert, count in groups:
        pool = saved[
            (saved.label == label)
            & ((saved.predicted_risk >= threshold) == alert)
            & (
                (saved.onset_hour - saved.at_hour >= 6)
                if label
                else saved.onset_hour.isna()
            )
        ].copy()
        for _ in range(count):
            choices = pool[~pool.patient_id.isin(used)].copy()
            if choices.empty:
                raise ValueError(
                    f"Not enough distinct patient examples for {pattern}; run prepare."
                )
            choices["seen_hospital"] = choices.hospital_id.isin(hospitals)
            choices = choices.sort_values(
                ["seen_hospital", "hospital_id", "stay_id", "at_hour"]
            )
            row = choices.iloc[0]
            selected.append((pattern, label, alert, row))
            used.add(row.patient_id)
            hospitals.add(row.hospital_id)
    return selected


def collect_cases():
    import pandas as pd

    info = model_info()
    provenance = json.loads(
        (ROOT / "examples/real_patient_provenance.json").read_text()
    )
    if provenance["model_sha256"] != info["model_sha256"]:
        raise ValueError("Historical example needs refreshing; run prepare.")
    stay = load_stay(provenance["stay_id"])
    cases = [
        patient_case(
            stay,
            provenance["at_hour"],
            provenance["retrospective_outcome"]["creatinine_aki_measurement_hour"],
            "real",
            "Patient 1",
        )
    ]
    saved = pd.read_csv(REPORTS / f"{info['training_source']}_internal_predictions.csv")
    choices = select_patient_rows(saved, info["alert_threshold"], stay["patient_id"])
    for number, (pattern, label, alert, row) in enumerate(choices, 2):
        endpoint = None if pd.isna(row.onset_hour) else float(row.onset_hour)
        cases.append(
            patient_case(
                load_stay(row.stay_id),
                row.at_hour,
                endpoint,
                f"patient_{number}",
                f"Patient {number}",
                expected_alert=alert,
                expected_label=label,
                pattern=pattern,
            )
        )
    for name, label in (
        ("stable", "Stable example"),
        ("concerning_trend", "Rising example"),
    ):
        body = PredictionRequest.model_validate_json(
            (ROOT / f"examples/{name}.json").read_text()
        )
        cases.append(
            {
                "id": name,
                "kind": "illustrative",
                "label": label,
                "origin": "Illustrative readings / risk calculated by the trained model",
                "description": "Compare the pattern in these example readings with the model's warning.",
                "selected_hour": body.at_hour,
                "outcome_hour": None,
                "end_hour": body.at_hour,
                "later_creatinine": [],
                "frames": [make_frame(body.patient, body.readings, body.at_hour)],
                "source_note": "Synthetic input example. No later outcome is provided.",
            }
        )
    return cases, info


def plot_frame(case, index, reveal):
    frame = case["frames"][index]
    hour, end = frame["hour"], max(case["end_hour"], 12)
    fig, axes = plt.subplots(
        2, 1, figsize=(10.4, 6.1), sharex=True, layout="constrained"
    )
    fig.set_facecolor("white")
    start = max(0, hour - 36) if case.get("kind") == "patient" else 0
    stop = min(end + 1, hour + 24) if case.get("kind") == "patient" else end + 1
    for ax in axes:
        ax.set_facecolor("white")
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        for edge in ("bottom", "left"):
            ax.spines[edge].set_color("#b9c7d3")
        ax.tick_params(colors=INK, labelsize=10)
        ax.set_xlim(start, stop)
        if hour < stop:
            ax.axvspan(hour, stop, color="#f1f4f7", zorder=0)
        ax.axvline(hour, color=INK, linewidth=1, alpha=0.6)
    past = frame["creatinine"]
    if past:
        axes[0].plot(
            [p[0] for p in past],
            [p[1] for p in past],
            color=TEAL,
            marker="o",
            markersize=4.5,
            linewidth=2,
            label="Readings available at this time",
        )
    if reveal and case.get("kind") == "patient":
        later = [p for p in case["later_creatinine"] if p[0] > hour]
        if later:
            connection = past[-1:] + later
            axes[0].plot(
                [p[0] for p in connection],
                [p[1] for p in connection],
                color=TEAL,
                marker="o",
                markersize=4,
                linestyle="--",
                linewidth=1.5,
                alpha=0.7,
                label="Later records",
            )
        if case["outcome_hour"] is not None:
            onset = case["outcome_hour"]
            for ax in axes:
                ax.axvline(onset, color=ORANGE, linewidth=1.5, linestyle=":")
            axes[0].annotate(
                "Kidney injury recorded" if start <= onset <= stop else "",
                xy=(onset, 1),
                xycoords=("data", "axes fraction"),
                xytext=(-5, -12),
                textcoords="offset points",
                ha="right",
                va="top",
                color=ORANGE,
                fontsize=10,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.9},
            )
    axes[0].set_title(
        "Kidney blood test / creatinine", loc="left", fontsize=13, color=INK, pad=10
    )
    axes[0].set_ylabel("Creatinine (mg/dL)", fontsize=11, color=INK)
    if not any(start <= p[0] <= stop for p in past):
        axes[0].text(
            0.5,
            0.5,
            "No blood-test sample in this time window",
            transform=axes[0].transAxes,
            ha="center",
            color=INK,
        )
    all_values = [p[1] for p in past if start <= p[0] <= stop]
    if reveal:
        all_values += [p[1] for p in case["later_creatinine"] if start <= p[0] <= stop]
    if all_values:
        low, high = min(all_values), max(all_values)
        pad = max(0.13, (high - low) * 0.28)
        axes[0].set_ylim(max(0, low - pad), high + pad)
        axes[0].legend(
            loc="upper left",
            bbox_to_anchor=(0, -0.10),
            ncols=2,
            frameon=False,
            fontsize=9,
        )
    scored = [f for f in case["frames"][: index + 1] if f["risk"] is not None]
    if scored:
        axes[1].plot(
            [f["hour"] for f in scored],
            [f["risk"] for f in scored],
            color=TEAL,
            marker="o",
            markersize=4,
            linewidth=2,
            label="Model estimate",
        )
    if not any(start <= f["hour"] <= stop for f in scored):
        axes[1].text(
            0.5,
            0.5,
            "More history is needed before scoring",
            transform=axes[1].transAxes,
            ha="center",
            color=INK,
        )
    axes[1].axhline(
        frame["threshold"],
        color=ORANGE,
        linestyle="--",
        linewidth=1.4,
        label="Warning threshold",
    )
    if frame["risk"] is not None:
        axes[1].scatter(
            [hour],
            [frame["risk"]],
            s=80,
            color=ORANGE if frame["alert"] else TEAL,
            zorder=5,
        )
    axes[1].set_title(
        "Chance of new kidney injury in the next 24 hours",
        loc="left",
        fontsize=13,
        color=INK,
        pad=24,
    )
    axes[1].set_ylim(0, 100)
    axes[1].set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    axes[1].set_ylabel("Model estimate (%)", fontsize=11, color=INK)
    axes[1].set_xlabel("Hours since ICU admission", fontsize=11, color=INK)
    axes[1].legend(
        loc="upper left", bbox_to_anchor=(0, -0.21), ncols=2, frameon=False, fontsize=9
    )
    return fig


def build_fingerprint(include_ai=False):
    from .summaries import summary_status

    info = model_info()
    paths = [
        REPORTS / f"{info['training_source']}_internal_predictions.csv",
        Path(__file__),
        ROOT / "aki/templates/showcase.html",
        ROOT / "aki/summaries.py",
        ROOT / "aki/service.py",
        ROOT / "aki/clinical.py",
        ROOT / "aki/clinical_summary.py",
        ROOT / "aki/features.py",
        ROOT / "aki/schema.py",
        ROOT / "aki/robustness.py",
        ROOT / "examples/stable.json",
        ROOT / "examples/concerning_trend.json",
        ROOT / "examples/real_patient_provenance.json",
    ]
    signature = {
        "files": [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths],
        "model": info["model_sha256"],
        "database_modified_ns": DB_PATH.stat().st_mtime_ns,
        "settings_modified_ns": (ROOT / ".env").stat().st_mtime_ns
        if (ROOT / ".env").exists()
        else None,
        "summary_settings": summary_status() if include_ai else None,
    }
    return hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()


def build_showcase(include_ai=False):
    cases, info = collect_cases()
    json.dumps(cases, allow_nan=False)
    REPORTS.mkdir(exist_ok=True)
    # Each graph uses genuine predictions at the displayed times. No fabricated
    # hourly predictions or numeric interpolation are used to create chart points.
    provider_available = include_ai
    for case in cases:
        print("Preparing graphs:", case["label"], flush=True)
        default = min(
            range(len(case["frames"])),
            key=lambda i: abs(case["frames"][i]["hour"] - case["selected_hour"]),
        )
        case["default_index"] = default
        for i, frame in enumerate(case["frames"]):
            if provider_available:
                from .summaries import explain_result

                # One summary per case, on its selected frame; other frames keep
                # the reliable local explanation. No bulk provider calls.
                if i == default:
                    explanation = explain_result(frame["_result"])
                    if explanation["provider"] == "gemini":
                        frame["explanation"] = explanation["summary"]
                    elif explanation["reason_code"] in {
                        "missing_key",
                        "invalid_model",
                        "provider_unavailable",
                        "timeout",
                    }:
                        provider_available = False
            frame.pop("_result")
            frame["plots"] = {}
            for reveal in (False, True):
                fig = plot_frame(case, i, reveal)
                stream = io.BytesIO()
                fig.savefig(
                    stream, format="svg", metadata={"Date": None}, bbox_inches="tight"
                )
                frame["plots"][str(reveal).lower()] = (
                    "data:image/svg+xml;base64,"
                    + base64.b64encode(stream.getvalue()).decode()
                )
                if case["kind"] == "patient" and i == default and reveal:
                    fig.savefig(
                        REPORTS
                        / (
                            "judge_graphs.png"
                            if case["id"] == "real"
                            else case["id"] + "_graphs.png"
                        ),
                        dpi=150,
                        bbox_inches="tight",
                    )
                plt.close(fig)
    data = {
        "cases": cases,
        "model_sha256": info["model_sha256"],
        "data_scope": "Public demo records and labelled illustrative examples",
    }
    template = (ROOT / "aki/templates/showcase.html").read_text(encoding="utf-8")
    embedded = json.dumps(data, ensure_ascii=True, allow_nan=False).replace(
        "<", "\\u003c"
    )
    target = REPORTS / "judge_showcase.html"
    target.write_text(template.replace("__SHOWCASE_DATA__", embedded), encoding="utf-8")
    # A small separate manifest supports reproducibility without embedded plot data.
    manifest = {
        "model_sha256": info["model_sha256"],
        "build_fingerprint": build_fingerprint(include_ai),
        "cases": [
            {
                "id": c["id"],
                "kind": c["kind"],
                "stay_id": c.get("stay_id"),
                "patient_id": c.get("patient_id"),
                "hospital_id": c.get("hospital_id"),
                "pattern": c.get("pattern"),
                "selected_label": c.get("selected_label"),
                "selected_alert": c.get("selected_alert"),
                "frames": len(c["frames"]),
                "selected_hour": c["selected_hour"],
                "outcome_hour": c["outcome_hour"],
                "origin": c["origin"],
            }
            for c in cases
        ],
        "html": "reports/judge_showcase.html",
        "preview": "reports/judge_graphs.png",
    }
    from .artifacts import atomic_json

    atomic_json(REPORTS / "showcase_manifest.json", manifest)
    print("Graph demo ready:", target)
    return target
