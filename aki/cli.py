"""Windows-friendly terminal entry point. No web frontend required."""

import argparse
import json
import math
import sys
from pathlib import Path

from .config import REPORTS, ROOT, ensure_dirs
from .csvio import read_csv
from .schema import Patient, PredictionRequest, Reading
from .service import evaluation, run_prediction


def print_prediction(result):
    print("\n" + "=" * 68)
    print("AKI EARLY WARNING | research demonstration")
    print("=" * 68)
    if result.get("stay_id"):
        print("Stay:", result["stay_id"])
    print("Prediction time: ICU hour", result["at_hour"])
    print("Result:", result["status"].replace("_", " ").upper())
    summary = result.get("clinical_summary", {})
    if summary:
        print(summary["headline"])
        print(summary["message"])
        for finding in summary["current_findings"]:
            print("CHECK NOW:", finding["message"])
    if result["predicted_risk_percent"] is not None:
        print(f"Estimated next-24h AKI risk: {result['predicted_risk_percent']:.2f}%")
        print("Risk category:", result["risk_category"].upper())
        print("Early risk alert:", "YES" if result["alert"] else "NO")
        print(f"Demo alert threshold: {result['alert_threshold'] * 100:.2f}%")
        fewer = result.get("alert_options", {}).get("fewer_alerts")
        if fewer:
            print(
                f"Optional fewer-alert policy: {'YES' if fewer['alert'] else 'NO'} "
                f"at {fewer['threshold'] * 100:.2f}% (may miss more AKI)"
            )
    clinical = result["clinical_assessment"]
    print("Creatinine-based AKI already observed:", clinical["creatinine_aki_observed"])
    print("Latest creatinine:", clinical["latest_creatinine"], "mg/dL")
    print("Latest creatinine stage:", clinical["latest_creatinine_stage"])
    print(
        "Urine-output stage:",
        clinical["urine_stage"]
        if clinical["urine_stage"] is not None
        else "unknown / incomplete intervals",
    )
    for reason in clinical["ineligibility_reasons"]:
        print(" -", reason)
    quality = result["data_quality"]
    print(
        f"Measurements available: {quality['available_model_inputs']}/{quality['total_model_inputs']} model groups"
    )
    if result["model_contributions"]:
        print("Main model contributions (not proven causes):")
        for row in result["model_contributions"][:3]:
            print(
                f" - {row['measurement']}: {row['contribution_percentage_points']:+.2f} percentage points"
            )
    sensitivity = result.get("input_sensitivity")
    if sensitivity:
        print("Input sensitivity:", sensitivity["status"].replace("_", " "))
        limits = sensitivity["ranges"]["creatinine"]
        print(
            f"  Creatinine stress estimate: {limits['minimum_risk_percent']:.2f}%-{limits['maximum_risk_percent']:.2f}% (not a confidence interval)"
        )
    for warning in quality["warnings"]:
        print("Data note:", warning)
    print(
        "Model:",
        result["model"]["algorithm"],
        "| trained on",
        result["model"]["training_source"],
        "open demo",
    )
    print(result["notice"])
    print(result["lead_time_note"])


def save_result(result, output):
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print("JSON saved:", path)


def show_results():
    report = evaluation()
    print("\nREAL-DATA DEMO EVALUATION (patient-separated; exploratory)")
    for source, direction in report["directions"].items():
        if "internal_test" not in direction:
            print(source, ":", direction.get("reason", "unavailable"))
            continue
        tests = {"internal": direction["internal_test"], **direction["external_tests"]}
        print("\nTraining source:", source)
        for name, metrics in tests.items():

            def fmt(key, metrics=metrics):
                v = metrics.get(key)
                return f"{v:.3f}" if v is not None else "not estimable"

            print(
                f"  Test {name}: {metrics['patients']} patients, {metrics['windows']} windows"
            )
            print(
                f"    AUROC={fmt('auroc')}  AUPRC={fmt('auprc')}  prevalence={fmt('prevalence')}"
            )
            print(
                f"    sensitivity={fmt('sensitivity')}  precision={fmt('precision')}  Brier={fmt('brier_score')}"
            )
            print(
                f"    median measured-sample lead hours={fmt('median_sample_lead_hours')}"
            )
    print("\nFull results:", REPORTS / "evaluation.json")
    print(
        "Small open demo samples do not establish clinical readiness or universal hospital performance."
    )


def demo():
    ensure_dirs()
    results = []
    for name in ("stable", "concerning_trend", "existing_aki"):
        request = PredictionRequest.model_validate_json(
            (ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8")
        )
        print(
            "\nILLUSTRATIVE INPUT SCENARIO:",
            name,
            "(synthetic inputs, real trained demo model)",
        )
        result = run_prediction(request)
        print_prediction(result)
        results.append(
            {
                "case": name,
                "input_provenance": "synthetic illustrative measurements",
                **result,
            }
        )
    manifest_path = ROOT / "examples" / "case_manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    )

    def available_case(name):
        return manifest.get("cases", {}).get(name, {"available": True})["available"]

    real_path = ROOT / "examples" / "real_patient.json"
    provenance_path = ROOT / "examples" / "real_patient_provenance.json"
    if (
        available_case("real_patient")
        and real_path.exists()
        and provenance_path.exists()
    ):
        from .service import model_info

        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance.get("model_sha256") != model_info()["model_sha256"]:
            raise ValueError("Demo case provenance is stale; run prepare to refresh it")
        print("\nREAL OPEN-DEMO PATIENT | preserved historical audit case")
        real_request = PredictionRequest.model_validate_json(
            real_path.read_text(encoding="utf-8")
        )
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        real_result = run_prediction(real_request)
        print_prediction(real_result)
        print(
            "Retrospective comparison only: qualifying AKI sample was collected",
            round(provenance["retrospective_outcome"]["hours_after_prediction"], 2),
            "hours after this prediction.",
        )
        print(
            "Case selected to illustrate a successful alert; see overall results and examples/missed_case.json for limitations."
        )
        results.append(
            {"case": "real_patient", "input_provenance": provenance, **real_result}
        )
    print("\nREAL CASE LIMITATIONS | selected retrospective audit windows")
    for name, title in (
        ("missed_case", "MISSED EARLY WARNING WINDOW"),
        ("false_alert", "FALSE ALERT WITHIN THIS 24H HORIZON"),
    ):
        path = ROOT / "examples" / f"{name}.json"
        provenance_file = ROOT / "examples" / f"{name}_provenance.json"
        if (
            not available_case(name)
            or not path.exists()
            or not provenance_file.exists()
        ):
            continue
        request = PredictionRequest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
        result = run_prediction(request)
        print(
            title,
            "| risk",
            str(result["predicted_risk_percent"]) + "%",
            "| alert",
            "YES" if result["alert"] else "NO",
        )
        future = provenance["retrospective_outcome"]
        if future["observed_aki_within_24h"]:
            print(
                "  Qualifying AKI sample",
                round(future["hours_after_prediction"], 2),
                "hours later. A later alert can still occur.",
            )
        else:
            print(
                "  No observed qualifying AKI in the next 24h, with follow-up testing."
            )
        results.append({"case": name, "input_provenance": provenance, **result})
    save_result(results, REPORTS / "latest_demo.json")
    show_results()


def prompt_number(prompt, default=None, required=False):
    while True:
        suffix = (
            f" [{default}]"
            if default is not None
            else " [Enter to skip]"
            if not required
            else ""
        )
        raw = input(prompt + suffix + ": ").strip()
        if not raw:
            if default is not None:
                return default
            if not required:
                return None
        try:
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("Non-finite number")
            return value
        except ValueError:
            print("Enter a number, or leave an optional input blank.")


def manual(advanced=False):
    print("\nEnter one adult patient's timestamped readings.")
    print(
        "Hours are relative to ICU admission. Use negative hours for earlier history."
    )
    print("Blank optional measurements mean unknown, not zero.")
    age = prompt_number("Age in years", required=True)
    sex = (
        input("Recorded sex (male/female/unknown) [unknown]: ").strip().lower()
        or "unknown"
    )
    weight = prompt_number("Weight (kg)")
    baseline = prompt_number("Earlier baseline creatinine (mg/dL)")
    baseline_hour = (
        prompt_number("Hour of that baseline measurement", required=True)
        if baseline is not None
        else None
    )
    context = {}
    if advanced:
        context["admission_type"] = (
            input(
                "Admission type (emergency/elective/urgent/other/unknown) [unknown]: "
            )
            .strip()
            .lower()
            or "unknown"
        )
        context["chronic_dialysis"] = input(
            "Known chronic dialysis? (yes/no) [no]: "
        ).strip().lower() in ("yes", "y")
        print(
            "Ventilation/drug flags are recorded as context; this shared model uses harmonized labs/vitals."
        )
    patient = Patient(
        **context,
        age=age,
        sex=sex,
        weight_kg=weight,
        baseline_creatinine=baseline,
        baseline_hour=baseline_hour,
    )
    raw_count = prompt_number("Number of readings to enter", default=3)
    if not float(raw_count).is_integer():
        raise ValueError("Number of readings must be a whole number")
    count = int(raw_count)
    if not 1 <= count <= 100:
        raise ValueError("Enter between 1 and 100 readings")
    rows = []
    variables = [
        ("creatinine", "Creatinine (mg/dL)"),
        ("bun", "BUN (mg/dL)"),
        ("map", "Mean arterial pressure (mmHg)"),
        ("heart_rate", "Heart rate (bpm)"),
        ("potassium", "Potassium (mmol/L)"),
        ("bicarbonate", "Bicarbonate (mmol/L)"),
        ("lactate", "Lactate (mmol/L)"),
        ("urine_output_ml", "Urine volume (mL)"),
    ]
    if advanced:
        variables += [
            ("spo2", "Oxygen saturation (%)"),
            ("respiratory_rate", "Respiratory rate (/min)"),
            ("temperature", "Temperature (C)"),
            ("ventilation", "Ventilation (0/1; blank if unknown)"),
            ("vasopressor", "Vasopressor exposure (0/1; blank if unknown)"),
            ("diuretic", "Diuretic exposure (0/1; blank if unknown)"),
            ("nephrotoxic_drug", "Nephrotoxic-drug exposure (0/1; blank if unknown)"),
            ("fluid_input_ml", "Documented fluid input (mL)"),
        ]
    for index in range(count):
        print(f"\nReading {index + 1}/{count}")
        hour = prompt_number("Measurement ICU hour", required=True)
        available = prompt_number(
            "Hour this information became available", default=hour
        )
        data = {"hour": hour, "available_hour": available}
        for name, label in variables:
            value = prompt_number(label)
            if value is not None:
                data[name] = value
        if "urine_output_ml" in data:
            interval = prompt_number(
                "Urine collection interval length (hours; skip if unknown)"
            )
            if interval is not None:
                data["urine_interval_hours"] = interval
        rows.append(Reading.model_validate(data))
    t = prompt_number(
        "Predict at ICU hour", default=max(r.available_hour for r in rows)
    )
    request = PredictionRequest(patient=patient, at_hour=t, readings=rows)
    result = run_prediction(request)
    print_prediction(result)
    save_result(result, REPORTS / "manual_prediction.json")


def replay(stay_id, hour, output=None):
    from .storage import load_stay

    stay = load_stay(stay_id, hour)
    if hour > stay["duration_hours"]:
        raise ValueError("Selected hour is beyond ICU stay")
    request = PredictionRequest(
        patient=stay["patient"], at_hour=hour, readings=stay["readings"]
    )
    result = {"stay_id": stay_id, "source": stay["source"], **run_prediction(request)}
    print_prediction(result)
    if output:
        save_result(result, output)
    return result


def prepare(skip_download=False, force=False):
    from .dataset import build_dataset
    from .download import download
    from .extract import extract
    from .storage import connect, initialize
    from .train import train_all

    initialize()
    with connect() as con:
        available_sources = {
            row[0] for row in con.execute("SELECT DISTINCT source FROM stays")
        }
    data_ready = (
        {"mimic", "eicu"}.issubset(available_sources)
        and (ROOT / "data" / "features.csv.gz").exists()
        and (REPORTS / "evaluation.json").exists()
    )
    from .diagnostics import readiness

    if data_ready and readiness()["ready"] and not force:
        print(
            "Current model, database and evaluation are ready. Refreshing handoff files."
        )
        finalize_training()
        return
    if not skip_download:
        print("Downloading relevant official unrestricted demo tables...", flush=True)
        download()
    extract()
    frame, _cohort = build_dataset()
    print("Labelled windows:", len(frame), flush=True)
    report = train_all()
    finalize_training(report)
    print("Ready. Run run.bat demo, run.bat manual, or start_api.bat")


def finalize_training(report=None):
    from .alerting import refresh_alert_profiles
    from .api import export_openapi
    from .demo_cases import refresh_cases
    from .service import load_model

    load_model.cache_clear()
    refresh_alert_profiles()
    write_summary(report if report is not None else evaluation())
    export_openapi()
    refreshed = refresh_cases()
    print(f"Refreshed {len(refreshed)} retrospective demo cases and API contract.")


def retrain():
    from .diagnostics import readiness
    from .train import train_all

    if not (ROOT / "data/features.csv.gz").exists():
        raise ValueError("No feature dataset. Run prepare first.")
    finalize_training(train_all())
    if not readiness()["ready"]:
        raise ValueError("Training completed but readiness checks failed; run doctor")


def write_summary(report):
    lines = [
        "# Exploratory demo evaluation",
        "",
        "Official unrestricted demo samples; no prospective clinical validation.",
        "Patient-disjoint development, calibration and test partitions. Previously inspected baseline holdout IDs are preserved; these are reused audit sets, not fresh validation.",
        "Model settings selected by grouped development CV with explicit input-sensitivity penalties; see completion_protocol.json.",
        "Source calibration and alert threshold use only calibration patients; unsupported calibration is disclosed.",
        "",
        "| Training source | Test cohort | Patients | Windows | AUROC | AUPRC | Prevalence | Sensitivity | Precision |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def fmt(v):
        return f"{v:.3f}" if v is not None else "N/A"

    for source, direction in report["directions"].items():
        if "internal_test" not in direction:
            lines.append(f"\n{source}: {direction.get('reason', 'unavailable')}\n")
            continue
        tests = {
            "internal held-out": direction["internal_test"],
            **direction["external_tests"],
        }
        for target, m in tests.items():
            lines.append(
                f"| {source} | {target} | {m['patients']} | {m['windows']} | {fmt(m['auroc'])} | {fmt(m['auprc'])} | {fmt(m['prevalence'])} | {fmt(m['sensitivity'])} | {fmt(m['precision'])} |"
            )
    lines.extend(
        [
            "",
            "A next-24h forecast does not establish 24h of advance warning.",
            "Observed onset uses the qualifying SAMPLE time; result availability limits inputs. Biological injury may occur earlier.",
            "Negative windows require full ICU follow-up and a late-horizon creatinine sample. RRT before a future endpoint causes censoring.",
            "Urine output from the source demos has no assumed collection interval.",
            "See evaluation.json for tuning, curves, calibration and leave-hospital-out results.",
            "See cohort.json and extraction.json for exclusions, missingness and provenance.",
            "GET /v1/alert-profiles and alert_profiles.json compare standard and optional stricter alerts; risk estimates are unchanged.",
        ]
    )
    (REPORTS / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def menu():
    while True:
        print(
            "\nAKI EARLY WARNING\n1. Run example scenarios and evaluation\n2. Enter patient readings manually\n3. Predict from a CSV file\n4. Show evaluation results\n5. List stored ICU stays\n0. Exit"
        )
        choice = input("Choose: ").strip()
        try:
            if choice == "0":
                return
            if choice == "1":
                demo()
            elif choice == "2":
                manual()
            elif choice == "3":
                path = input("CSV path: ").strip().strip('"')
                result = run_prediction(read_csv(path))
                print_prediction(result)
                save_result(result, REPORTS / "csv_prediction.json")
            elif choice == "4":
                show_results()
            elif choice == "5":
                from .storage import list_stays

                print(json.dumps(list_stays(limit=20), indent=2))
            else:
                print("Choose a listed option.")
        except (ValueError, OSError, KeyError) as exc:
            print("Could not complete request:", exc)


def main():
    parser = argparse.ArgumentParser(
        description="AKI model, data pipeline and console demo"
    )
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("prepare")
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--force", action="store_true")
    sub.add_parser("demo")
    manual_parser = sub.add_parser("manual")
    manual_parser.add_argument("--advanced", action="store_true")
    sub.add_parser("results")
    sub.add_parser("doctor")
    sub.add_parser("train")
    sub.add_parser("menu")
    p = sub.add_parser("csv")
    p.add_argument("path")
    p.add_argument("--at-hour", type=float)
    p.add_argument("--output")
    p = sub.add_parser("json")
    p.add_argument("path")
    p.add_argument("--output")
    p = sub.add_parser("replay")
    p.add_argument("stay_id")
    p.add_argument("--at-hour", required=True, type=float)
    p.add_argument("--output")
    p = sub.add_parser("stays")
    p.add_argument("--source", choices=["mimic", "eicu"])
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=8000)
    sub.add_parser("export-openapi")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.skip_download, args.force)
        elif args.command == "doctor":
            from .diagnostics import doctor_report

            report = doctor_report()
            print(json.dumps(report, indent=2))
            return 0 if report["ready"] else 1
        elif args.command == "train":
            retrain()
        elif args.command == "demo":
            demo()
        elif args.command == "manual":
            manual(args.advanced)
        elif args.command == "results":
            show_results()
        elif args.command in ("csv", "json"):
            request = (
                read_csv(args.path, args.at_hour)
                if args.command == "csv"
                else PredictionRequest.model_validate_json(
                    Path(args.path).read_text(encoding="utf-8-sig")
                )
            )
            result = run_prediction(request)
            print_prediction(result)
            if args.output:
                save_result(result, args.output)
        elif args.command == "replay":
            replay(args.stay_id, args.at_hour, args.output)
        elif args.command == "stays":
            from .storage import list_stays

            print(json.dumps(list_stays(args.source, args.limit), indent=2))
        elif args.command == "serve":
            import uvicorn

            uvicorn.run("aki.api:app", host="127.0.0.1", port=args.port)
        elif args.command == "export-openapi":
            from .api import export_openapi

            export_openapi()
        else:
            menu()
    except (ValueError, OSError, KeyError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1
    return 0
