"""Write the current completion audit from actual model and verification artifacts."""

import json
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aki.artifacts import atomic_json
from aki.diagnostics import readiness
from aki.service import model_info


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def main():
    model = model_info()
    evaluation = read_json("reports/evaluation.json")
    verification = read_json("reports/verification.json")
    sensitivity = read_json("reports/sensitivity_audit.json")
    assert (
        evaluation["model_sha256"]
        == verification["model_sha256"]
        == model["model_sha256"]
    )
    suites = ET.parse(ROOT / "reports/pytest.xml").getroot().findall(".//testsuite")
    tests = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    assert failures == 0
    expert_cases = sum(
        1
        for suite in suites
        for case in suite.findall("testcase")
        if case.get("classname", "").endswith("test_expert_cases")
    )
    timing_path = ROOT / "reports/expert_timing_changes.json"
    timing = json.loads(timing_path.read_text()) if timing_path.exists() else {}
    if timing:
        assert timing["model_sha256"] == model["model_sha256"]
    baseline = ROOT / "reports/baseline_v0_2/features.csv.gz"
    same_cohort = None
    if baseline.exists():
        same_cohort = (
            pd.read_csv(baseline)
            .drop(columns="onset_documented_hour")
            .equals(
                pd.read_csv(ROOT / "data/features.csv.gz").drop(
                    columns="onset_documented_hour"
                )
            )
        )
    status = readiness()
    assert status["ready"]
    http = {}
    for name in ("http_smoke.json", "http_launcher_smoke.json"):
        path = ROOT / "reports" / name
        value = json.loads(path.read_text()) if path.exists() else {}
        http[name] = bool(
            value.get("status") == "passed"
            and value.get("model_sha256") == model["model_sha256"]
        )

    def grid_change(report):
        values = {
            r["last_creatinine"]: r["risk_percent"] for r in report["creatinine_grid"]
        }
        return round(abs(values[0.85] - values[0.81]), 2)

    previous = read_json("reports/baseline_v0_2/sensitivity_audit.json")
    old_change, new_change = grid_change(previous), grid_change(sensitivity)
    rows = []
    for source, direction in evaluation["directions"].items():
        if "internal_test" not in direction:
            continue
        for target, metrics in {
            "internal audit": direction["internal_test"],
            **direction["external_tests"],
        }.items():
            rows.append(
                f"| {source} | {target} | {metrics['patients']} | {metrics['windows']} | {metrics['auroc']:.3f} | {metrics['auprc']:.3f} | {metrics['sensitivity']:.1%} | {metrics['precision']:.1%} |"
            )
    eicu = evaluation["directions"]["eicu"]
    internal, external = eicu["internal_test"], eicu["external_tests"]["mimic"]
    selection = eicu["metadata"]["selected_algorithm"]["name"]
    selected_cv = next(r for r in eicu["tuning"] if r["config"]["name"] == selection)
    loo = evaluation["leave_hospital_out"]["results"]
    text = f"""# Completion and logic audit: {model["model_version"]}

The adult ICU hackathon model/backend is working and verified. This audit closes
engineering gaps; it does not claim clinical readiness or universal hospital use.
No frontend was built.

## Changes delivered

- Twenty predeclared model/feature candidates, grouped development-only CV with
  explicit creatinine/missing-input sensitivity penalties. Default: **{selection}**
  ({model["feature_count"]} features; CV AUPRC {selected_cv["mean_auprc"]:.3f}).
- Every prediction includes an engineering input-sensitivity diagnostic.
  Threshold crossings, current-AKI boundaries and >=10 percentage-point changes
  request review. Nominal alert thresholds and evaluation remain unchanged by
  that review flag.
- Corrected lab collection/result timing, delayed baselines, valid comparison
  windows, RRT censoring, urine revisions and historical first-episode eligibility.
- Confirmed timed zero urine does not require weight; positive-volume normalized
  rates do. Overlaps are checked before clipping collections, and equivalent
  duplicate records cannot discard a known interval merely through row ordering.
- Still-qualifying lab corrections preserve earliest as-of criterion recognition;
  latest corrected value availability remains a separate timestamp.
- Later CSV weight cannot become an admission-known baseline for earlier replay.
  A corrected urine record can remove its old interval instead of inventing coverage.
- Readiness validates model/database/evaluation consistency. Corrupt/incompatible
  artifacts return unavailable status. Atomic writes preserve earlier files on
  failed writes; model caches reload after replacement.
- Patient ID search, caller-history replay, bounded supplied/stored batches,
  optional shared API key, configured CORS and bounded JSON/CSV request bodies.
- Retraining refreshes examples, results and OpenAPI. Missing example types are
  explicitly unavailable; stale examples are not silently shown.
- Advanced console accepts requested treatment context. No unsupported claim that
  context-only inputs affect the prediction.
- requirements-lock.txt, doctor.bat, API/requirements handoff and repeatable checks.

## Exact scope

See [requirements checklist](../docs/REQUIREMENTS.md).
Creatinine/BUN, MAP/heart rate, potassium/bicarbonate/lactate, shared vitals, documented
urine, age and sex drive the model. Ventilation/drugs/admission type remain
context-only because reliable administration/state harmonization is incomplete.
Weight, baselines and dialysis also support separate clinical eligibility checks.
GET /v1/model classifies every accepted measurement/patient field.

The next-24h endpoint is the first qualifying **sample time**, using only available
measurements as prediction inputs. It is not biological onset, death prediction
or a guaranteed 24h warning. The operational clinical checks reference
[KDIGO 2012](https://kdigo.org/wp-content/uploads/2016/10/KDIGO-2012-AKI-Guideline-English.pdf)
and the [official eICU lab timestamp definitions](https://eicu.mit.edu/eicutables/lab/).

## Verification evidence

- **{tests} automated tests passed**, no errors/failures.
- **{expert_cases} adversarial clinical cases** include 32 seeded delayed/revised
  creatinine timelines checked at each availability time against an independent
  decimal-exact reference, 16 urine-volume sequences checked against separate
  arithmetic, and 8 future-data/reordering invariance cases.
  See [readable clinical cases](../docs/CLINICAL_TEST_CASES.md).
- Recognition metadata audit: {len(timing.get("changed_stays", {}))} stay changed;
  predictors, labels, sample times and model weights were unchanged. The recorded
  correction is in expert_timing_changes.json.
- **{verification["raw_publisher_hashes_verified"]} raw publisher hashes**, SQLite
  integrity/foreign keys, {verification["observation_count"]:,} observations.
- 20 sampled source-to-feature/label comparisons plus training/API replay parity.
- Tests cover delayed/future data, KDIGO example trajectories, missing urine,
  corrected intervals, weight timing, dialysis, patient splits, context fields,
  model corruption/reload, atomic failure, auth/body limits, batching and search.
- Full rebuild from cached raw data was exercised, including extraction, cohort,
  both training directions, hospital holdouts and automatic handoff refresh.
- Rebuilt predictor/label table (excluding corrected documentation-time metadata) exactly matches the preserved 0.2 values: **{same_cohort}**.
- Current-artifact live module HTTP check: **{http["http_smoke.json"]}**.
- Current-artifact actual start_api.bat HTTP check: **{http["http_launcher_smoke.json"]}**.
- Manual/advanced console, CSV, JSON, demo launcher, doctor and cached prepare
  are exercised separately. Server smoke checks stop their own temporary servers.

Machine-readable evidence: pytest.xml, verification.json, http_smoke.json,
http_launcher_smoke.json and completion.json. Run verify.bat --http; the actual
launcher smoke can also be run with scripts/smoke_http.py --launcher.

## Additional improvement work

The bounded development-only challenger study and optional source-calibrated
fewer-alert policy are documented in [the improvement report](IMPROVEMENTS.md).
Patient/hospital fold isolation, patient weights, qualification gates, calibration
support, stale profile handling, API protection and alert-subset behavior have
regression tests. Standard predictions and model weights are preserved.

## Results and remaining weaknesses

Source calibration and thresholds stay frozen externally. Earlier calibration/test
patient IDs are preserved; all audit sets were previously inspected.
No tuning uses the target hospitals' scores. Source calibration/external separation
follows the [cross-site study design](https://doi.org/10.1038/s41467-020-19551-w).
The same source cohort permits an exploratory comparison to 0.2, not a fresh
independent validation claim.

| Train | Test | Patients | Windows | AUROC | AUPRC | Sensitivity | Precision |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

The default model has {external["confusion"]["tp"]} true-alert and
{external["confusion"]["fp"]} false-alert MIMIC windows, with
{external["confusion"]["fn"]} positive windows without an alert. These are correlated
windows, not independent patients. Alert fatigue remains a major unresolved problem.

Median qualifying-sample lead among detected evaluable stays is
{internal["median_sample_lead_hours"]:.2f}h internally and
{external["median_sample_lead_hours"]:.2f}h in MIMIC. Small MIMIC-trained reverse
transport remains weak, with unsupported calibration on its small calibration set.
Hospital holdouts evaluate {sum(h["status"] == "evaluated" for h in loo)}/{len(loo)}
hospitals with a separate fixed logistic baseline.

In the repeated illustrative creatinine check (0.81 -> 0.85 mg/dL), the estimate
change fell from {old_change:.2f} to {new_change:.2f} percentage points. The current
example stays below the threshold. This one illustration is not proof of global
robustness. sensitivity_audit.json preserves the full grid/missing-group checks;
development CV uses separate patient stress cases.

Larger approved cohorts, reliable active treatment mappings, clinician-reviewed
labels, untouched external validation and prospective workflow evaluation remain
necessary to establish clinical utility. This project does not invent those results.
"""
    (ROOT / "reports/LOGIC_AUDIT.md").write_text(text, encoding="utf-8")
    atomic_json(
        ROOT / "reports/completion.json",
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "model_version": model["model_version"],
            "model_sha256": model["model_sha256"],
            "tests": tests,
            "failures_or_errors": failures,
            "readiness": status,
            "same_feature_values_as_0_2": same_cohort,
            "comparison_excluded_metadata": ["onset_documented_hour"],
            "adversarial_clinical_tests": expert_cases,
            "recognition_timing_audit": timing,
            "live_http_current_artifact": http,
            "engineering_sensitivity_example": {
                "prior_change_pp": old_change,
                "current_change_pp": new_change,
            },
            "scope": "Working hackathon backend/model; context-only treatments and research/clinical limits remain explicit",
        },
    )
    print(f"Completion audit written: {tests} passed tests, ready={status['ready']}.")


if __name__ == "__main__":
    main()
