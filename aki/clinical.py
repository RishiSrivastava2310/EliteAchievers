"""Availability-safe operational KDIGO-2012 research rules.

Observed preceding minima are proxy baselines, not known healthy kidney function.
Measurement time defines the observed endpoint; availability defines what was known.
"""


def known_readings(readings, at_hour):
    return sorted(
        [r for r in readings if r.hour <= at_hour and r.available_hour <= at_hour],
        key=lambda r: (r.available_hour, r.hour),
    )


def creatinine_history(patient, readings, at_hour):
    # Collapse corrected values only after their revision becomes available.
    latest_by_time = {
        r.hour: (r.hour, r.available_hour, r.creatinine)
        for r in known_readings(
            [r for r in readings if r.creatinine is not None], at_hour
        )
    }
    if (
        patient.baseline_creatinine is not None
        and patient.baseline_hour <= at_hour
        and patient.baseline_hour not in latest_by_time
    ):
        latest_by_time[patient.baseline_hour] = (
            patient.baseline_hour,
            patient.baseline_hour,
            patient.baseline_creatinine,
        )
    return sorted(latest_by_time.values(), key=lambda r: (r[1], r[0]))


def _first_recognition_hours(patient, readings):
    """Earliest as-of recognition per sample, preserving the original result versions."""
    from itertools import groupby

    versions = [(r.hour, r.available_hour, r.creatinine) for r in readings]
    if patient.baseline_creatinine is not None:
        versions.append(
            (patient.baseline_hour, patient.baseline_hour, patient.baseline_creatinine)
        )
    versions.sort(key=lambda row: (row[1], row[0]))
    state, first = {}, {}
    for available, group in groupby(versions, key=lambda row: row[1]):
        changed = set()
        for time, _, value in group:
            state[time] = value
            changed.add(time)
        for time, value in state.items():
            if time in first or not any(t <= time <= t + 168 for t in changed):
                continue
            if any(
                value / prior >= 1.5 - 1e-9
                or (t >= time - 48 and value - prior >= 0.3 - 1e-9)
                for t, prior in state.items()
                if time - 168 <= t < time
            ):
                first[time] = available
    return first


def creatinine_events(patient, readings, at_hour):
    history = creatinine_history(patient, readings, at_hour)
    known_labs = [
        r for r in known_readings(readings, at_hour) if r.creatinine is not None
    ]
    has_revisions = len(known_labs) != len({r.hour for r in known_labs})
    # The supplied baseline is known at baseline_hour, even if an identical lab
    # is entered later. Revisions must not shift an earlier observed diagnosis.
    first_seen = (
        _first_recognition_hours(patient, known_labs)
        if has_revisions or patient.baseline_creatinine is not None
        else {}
    )
    events = []
    for time, available, value in history:
        prior = [x for x in history if time - 168 <= x[0] < time]
        if not prior:
            continue
        qualifying = [
            x
            for x in prior
            if value / x[2] >= 1.5 - 1e-9
            or (x[0] >= time - 48 and value - x[2] >= 0.3 - 1e-9)
        ]
        if not qualifying:
            continue
        # A delayed earlier baseline can establish AKI when that baseline arrives.
        documented = first_seen.get(time, min(max(available, x[1]) for x in qualifying))
        baseline = min(x[2] for x in prior)
        prior48 = [x[2] for x in prior if x[0] >= time - 48]
        rise = value - min(prior48) if prior48 else None
        ratio = value / baseline
        stage = 3 if ratio >= 3 - 1e-9 or value >= 4 else 2 if ratio >= 2 - 1e-9 else 1
        events.append(
            {
                "measurement_hour": time,
                "documented_hour": documented,
                "latest_result_available_hour": available,
                "stage": stage,
                "creatinine": value,
                "reference_creatinine": baseline,
                "rise_48h": None if rise is None else round(rise, 6),
                "ratio_7d": round(ratio, 6),
            }
        )
    return sorted(events, key=lambda e: (e["documented_hour"], e["measurement_hour"]))


def urine_window(patient, readings, at_hour, window, knowledge_hour=None):
    knowledge_hour = at_hour if knowledge_hour is None else knowledge_hour
    known = [r for r in known_readings(readings, knowledge_hour) if r.hour <= at_hour]
    unknown = {
        "rate_ml_kg_h": None,
        "volume_ml": None,
        "coverage_hours": 0.0,
        "complete": False,
    }
    # Latest correction replaces the complete collection record. At an identical
    # knowledge time, a duplicate with known duration enriches a missing duration.
    by_end = {}
    for row in known:
        if row.urine_output_ml is None:
            continue
        previous = by_end.get(row.hour)
        if previous is None or (
            row.available_hour,
            row.urine_interval_hours is not None,
        ) > (previous.available_hour, previous.urine_interval_hours is not None):
            by_end[row.hour] = row
    intervals = []
    for row in by_end.values():
        if row.urine_interval_hours is None:
            continue
        start, end = row.hour - row.urine_interval_hours, row.hour
        if end <= at_hour - window or start >= at_hour:
            continue
        intervals.append((start, end, row.urine_output_ml))
    intervals.sort()
    last_end = None
    for start, end, _ in intervals:
        # Validate all intersecting intervals before skipping boundary-spanning
        # volumes; otherwise a conflicting long collection could be hidden.
        if last_end is not None and start < last_end - 1e-6:
            return {**unknown, "reason": "Overlapping urine intervals"}
        last_end = end
    coverage, volume, last_end = 0.0, 0.0, at_hour - window
    for start, end, amount in intervals:
        if start < at_hour - window - 1e-6 or end > at_hour + 1e-6:
            # Exact zero over a longer collection proves zero in every contained
            # subinterval. A positive volume has no known within-interval split.
            if amount != 0:
                continue
            start, end = max(start, at_hour - window), min(end, at_hour)
        coverage += end - start
        volume += amount
        last_end = end
    complete = abs(coverage - window) < 1e-5 and abs(last_end - at_hour) < 1e-5
    weights = [
        r.weight_kg
        for r in sorted(known, key=lambda r: (r.hour, r.available_hour))
        if r.weight_kg is not None
    ]
    weight = weights[-1] if weights else patient.weight_kg
    return {
        "rate_ml_kg_h": (
            0.0 if volume == 0 else volume / weight / window if weight else None
        )
        if complete
        else None,
        "volume_ml": volume if complete else None,
        "coverage_hours": round(coverage, 4),
        "complete": complete,
    }


def _urine_stage(windows):
    six, twelve, day = windows
    stage = (
        (1 if six["rate_ml_kg_h"] < 0.5 else 0)
        if six["rate_ml_kg_h"] is not None
        else None
    )
    if twelve["rate_ml_kg_h"] is not None and twelve["rate_ml_kg_h"] < 0.5:
        stage = 2
    if (twelve["complete"] and twelve["volume_ml"] == 0) or (
        day["rate_ml_kg_h"] is not None and day["rate_ml_kg_h"] < 0.3
    ):
        stage = 3
    return stage


def assess(patient, readings, at_hour):
    known = known_readings(readings, at_hour)
    events = creatinine_events(patient, known, at_hour)
    history = creatinine_history(patient, known, at_hour)
    latest = max(history, key=lambda x: x[0]) if history else None
    prior = [x for x in history if latest and latest[0] - 168 <= x[0] < latest[0]]
    latest_event = next(
        (e for e in events if latest and e["measurement_hour"] == latest[0]), None
    )
    windows = [urine_window(patient, known, at_hour, w) for w in (6, 12, 24)]
    urine_stage = _urine_stage(windows)
    # A recovered patient must not re-enter a first-episode forecasting cohort.
    urine_endpoints = sorted(
        {
            r.hour
            for r in known
            if r.urine_output_ml is not None and r.urine_interval_hours is not None
        }
    )
    first_urine = next(
        (
            t
            for t in urine_endpoints
            if _urine_stage(
                [
                    urine_window(patient, known, t, w, knowledge_hour=at_hour)
                    for w in (6, 12, 24)
                ]
            )
        ),
        None,
    )
    urine_observed = first_urine is not None or bool(urine_stage)
    rrt = any(r.rrt == 1 for r in known)
    history_dialysis = patient.chronic_dialysis or any(
        r.dialysis_history == 1 for r in known
    )
    reasons = []
    if events:
        reasons.append("Creatinine-based AKI has already been observed in this history")
    if urine_observed:
        reasons.append("Available urine history meets a KDIGO urine-output criterion")
    if history_dialysis or rrt:
        reasons.append(
            "Dialysis/RRT patients are outside the new-AKI prediction cohort"
        )
    return {
        "creatinine_aki_observed": bool(events),
        "first_documented_creatinine_aki_hour": events[0]["documented_hour"]
        if events
        else None,
        "latest_creatinine_stage": latest_event["stage"]
        if latest_event
        else 0
        if prior
        else None,
        "latest_creatinine": latest[2] if latest else None,
        "observed_reference_creatinine": min(x[2] for x in prior) if prior else None,
        "reference_method": "provided historical value plus preceding observed 7-day minimum"
        if patient.baseline_creatinine is not None
        else "preceding observed 7-day minimum; pre-admission baseline may be missing",
        "urine_stage": urine_stage,
        "urine_aki_observed": urine_observed,
        "first_observed_urine_aki_measurement_hour": first_urine,
        "urine_6h": windows[0],
        "urine_12h": windows[1],
        "urine_24h": windows[2],
        "rrt_observed": rrt,
        "dialysis_history_observed": history_dialysis,
        "eligible_for_new_aki_forecast": not reasons,
        "ineligibility_reasons": reasons,
        "creatinine_comparison_available": bool(prior),
    }
