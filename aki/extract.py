"""Reproducible adapters for only the official unrestricted demo releases.

Units are normalized before insertion. Lab availability uses store/revised offsets
when supplied. Ward vitals are aggregated to completed ICU hours, never back-filled.
"""

import json
import math
import re
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from .config import DATA, REPORTS, ensure_dirs
from .schema import RANGES, Patient
from .storage import connect, initialize

LAB_ITEMS = {
    50912: "creatinine",
    51006: "bun",
    50971: "potassium",
    50882: "bicarbonate",
    50813: "lactate",
    50983: "sodium",
    50931: "glucose",
    51222: "hemoglobin",
    51301: "wbc",
}
CHART_ITEMS = {
    220045: "heart_rate",
    220052: "map",
    220181: "map",
    220277: "spo2",
    220210: "respiratory_rate",
    223762: "temperature",
    226512: "weight_kg",
    224639: "weight_kg",
}
DRUG_PATTERNS = {
    "vasopressor": r"norepinephrine|noradrenaline|epinephrine|vasopressin|phenylephrine|dopamine",
    "diuretic": r"furosemide|bumetanide|torsemide|chlorothiazide|metolazone",
    "nephrotoxic_drug": r"vancomycin|gentamicin|tobramycin|amikacin|amphotericin|acyclovir|ibuprofen|ketorolac",
}
LAB_NAMES = {
    "creatinine": "creatinine",
    "bun": "bun",
    "potassium": "potassium",
    "bicarbonate": "bicarbonate",
    "hco3": "bicarbonate",
    "lactate": "lactate",
    "sodium": "sodium",
    "glucose": "glucose",
    "hgb": "hemoglobin",
    "wbc x 1000": "wbc",
}


def treatment_is_rrt(label):
    normalized = re.sub(r"\s+", "", str(label).lower())
    return bool(
        re.search(
            r"^renal\|dialysis\|(hemodialysis(?:\||$)|cvvh|crrt|peritonealdialysis)",
            normalized,
        )
    )


def history_is_dialysis(label):
    return bool(
        re.search(
            r"renal failure - (hemodialysis|peritoneal dialysis)|end.stage renal|esrd|chronic dialysis",
            str(label),
            re.IGNORECASE,
        )
    )


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def admission(value):
    s = str(value).lower()
    if "elective" in s:
        return "elective"
    if "emerg" in s or s in ("ed", "emergency department"):
        return "emergency"
    if "urgent" in s:
        return "urgent"
    return "unknown"


class Writer:
    def __init__(self, con, source):
        self.con, self.source = con, source
        self.counts = Counter()
        self.buffer = []
        self.valid = set()

    def stay(self, sid, pid, hospital, duration, patient, metadata):
        self.con.execute(
            "INSERT INTO stays VALUES (?,?,?,?,?,?,?)",
            (
                sid,
                self.source,
                pid,
                str(hospital),
                duration,
                patient.model_dump_json(),
                json.dumps(metadata),
            ),
        )
        self.valid.add(sid)
        self.counts["adult_stays"] += 1

    def add(self, sid, hour, available, variable, value, interval=None):
        if sid not in self.valid or variable not in RANGES:
            return
        value = number(value)
        if value is None:
            return
        low, high = RANGES[variable]
        if value < low or value > high:
            self.counts["rejected_out_of_range"] += 1
            return
        if not math.isfinite(hour) or hour < -168 or hour > 8760:
            return
        available = max(hour, available)
        if available > 9000:
            return
        self.buffer.append(
            (sid, round(hour, 6), round(available, 6), variable, value, interval)
        )
        self.counts["accepted_" + variable] += 1
        if len(self.buffer) >= 20000:
            self.flush()

    def flush(self):
        if self.buffer:
            # Exact duplicate events are collapsed. Conflicting values at identical
            # timestamps are replaced deterministically in source file order.
            self.con.executemany(
                "INSERT INTO observations VALUES (?,?,?,?,?,?) ON CONFLICT(stay_id,hour,available_hour,variable) DO UPDATE SET value=excluded.value, interval_hours=excluded.interval_hours",
                self.buffer,
            )
            self.buffer.clear()

    def finish(self):
        self.flush()
        counts = dict(self.counts)
        counts["known_chronic_dialysis_evidence_matches"] = counts.pop(
            "known_chronic_dialysis", 0
        )
        counts["known_chronic_dialysis"] = sum(
            bool(json.loads(row[0]).get("chronic_dialysis"))
            for row in self.con.execute(
                "SELECT patient_json FROM stays WHERE source=?", (self.source,)
            )
        )
        counts["source"] = self.source
        counts["endpoint"] = "new creatinine-defined KDIGO-2012 AKI in next 24 hours"
        counts["baseline_limitation"] = (
            "prior observed minimum; pre-hospital baseline often unavailable"
        )
        counts["support_features"] = (
            "extracted context only; shared core model uses labs/vitals/documented urine volume/age/sex/time"
        )
        self.con.execute(
            "INSERT OR REPLACE INTO audit VALUES (?,?)",
            (self.source, json.dumps(counts)),
        )
        return counts


def read(path, **kwargs):
    return pd.read_csv(path, **kwargs)


def mimic(con):
    root = DATA / "raw" / "mimic"
    patients = read(root / "hosp/patients.csv.gz").set_index("subject_id")
    admissions = read(root / "hosp/admissions.csv.gz")
    admissions["admittime"] = pd.to_datetime(admissions.admittime, format="ISO8601")
    adm = admissions.set_index("hadm_id")
    stays = read(root / "icu/icustays.csv.gz")
    stays["intime"] = pd.to_datetime(stays.intime, format="ISO8601")
    stays["outtime"] = pd.to_datetime(stays.outtime, format="ISO8601")
    writer = Writer(con, "mimic")
    starts, by_hadm, by_patient = {}, defaultdict(list), defaultdict(list)
    for r in stays.itertuples(index=False):
        p = patients.loc[r.subject_id]
        age = float(p.anchor_age) + r.intime.year - int(p.anchor_year)
        if age < 18:
            continue
        age = min(age, 100)
        sid = f"mimic-{r.stay_id}"
        start = r.intime
        duration = (r.outtime - start).total_seconds() / 3600
        if duration < 0:
            continue
        pat = Patient(
            age=age,
            sex="male" if p.gender == "M" else "female",
            admission_type=admission(adm.loc[r.hadm_id].admission_type),
        )
        writer.stay(
            sid,
            f"mimic-{r.subject_id}",
            "mimic-bidmc",
            duration,
            pat,
            {
                "icu_type": r.first_careunit,
                "baseline": "observed history",
                "data_release": "mimic-iv-demo/2.2",
            },
        )
        starts[sid] = start
        by_hadm[r.hadm_id].append((sid, start, r.outtime))
        by_patient[r.subject_id].append((sid, start, r.outtime))
    # Exclude ESRD/chronic-dialysis when documented on an earlier admission only.
    dx = read(root / "hosp/diagnoses_icd.csv.gz", dtype={"icd_code": str})
    renal = dx[
        dx.icd_code.str.replace(".", "", regex=False).isin(
            ["5856", "V4511", "N186", "Z992"]
        )
    ]
    for row in renal.itertuples(index=False):
        if row.hadm_id not in adm.index:
            continue
        discharged = pd.to_datetime(adm.loc[row.hadm_id].dischtime)
        for sid, start, end in by_patient.get(row.subject_id, []):
            if discharged <= start:
                old = con.execute(
                    "SELECT patient_json FROM stays WHERE stay_id=?", (sid,)
                ).fetchone()[0]
                pat = Patient.model_validate_json(old)
                pat.chronic_dialysis = True
                con.execute(
                    "UPDATE stays SET patient_json=? WHERE stay_id=?",
                    (pat.model_dump_json(), sid),
                )
                writer.counts["known_chronic_dialysis"] += 1
    labs = read(
        root / "hosp/labevents.csv.gz",
        usecols=[
            "subject_id",
            "hadm_id",
            "itemid",
            "charttime",
            "storetime",
            "valuenum",
            "valueuom",
        ],
    )
    labs = labs[labs.itemid.isin(LAB_ITEMS)].copy()
    labs["charttime"] = pd.to_datetime(labs.charttime, format="ISO8601")
    labs["storetime"] = pd.to_datetime(labs.storetime, format="ISO8601")
    for r in labs.itertuples(index=False):
        for sid, start, end in by_patient.get(r.subject_id, []):
            if not start - pd.Timedelta(days=7) <= r.charttime <= end:
                continue
            variable = LAB_ITEMS[r.itemid]
            unit = str(r.valueuom).lower().replace(" ", "")
            valid_units = {
                "creatinine": {"mg/dl"},
                "bun": {"mg/dl"},
                "potassium": {"meq/l", "mmol/l"},
                "bicarbonate": {"meq/l", "mmol/l"},
                "lactate": {"mmol/l"},
                "sodium": {"meq/l", "mmol/l"},
                "glucose": {"mg/dl"},
                "hemoglobin": {"g/dl"},
                "wbc": {"k/ul", "10^3/ul"},
            }
            if unit not in valid_units[variable]:
                writer.counts["rejected_lab_units"] += 1
                continue
            hour = (r.charttime - start).total_seconds() / 3600
            available = (
                (r.storetime - start).total_seconds() / 3600
                if pd.notna(r.storetime)
                else hour
            )
            writer.add(sid, hour, available, variable, r.valuenum)
    chartpath = root / "icu/chartevents.csv.gz"
    for chunk in read(
        chartpath,
        chunksize=100000,
        usecols=["stay_id", "itemid", "charttime", "storetime", "valuenum"],
    ):
        chunk = chunk[chunk.itemid.isin(CHART_ITEMS)].copy()
        chunk["charttime"] = pd.to_datetime(chunk.charttime, format="ISO8601")
        chunk["storetime"] = pd.to_datetime(chunk.storetime, format="ISO8601")
        for r in chunk.itertuples(index=False):
            sid = f"mimic-{r.stay_id}"
            if sid not in starts:
                continue
            time = r.charttime
            stored = r.storetime
            hour = (time - starts[sid]).total_seconds() / 3600
            available = (
                (stored - starts[sid]).total_seconds() / 3600
                if pd.notna(stored)
                else hour
            )
            writer.add(sid, hour, available, CHART_ITEMS[r.itemid], r.valuenum)
    # Use only urine-specific output item IDs, excluding irrigant and other drains.
    urine_ids = {226559, 226560, 226561, 226584, 226563, 226564, 226565, 226567, 226557}
    output = read(root / "icu/outputevents.csv.gz")
    output = output[output.itemid.isin(urine_ids)].copy()
    output["charttime"] = pd.to_datetime(output.charttime, format="ISO8601")
    output["storetime"] = pd.to_datetime(output.storetime, format="ISO8601")
    # Sum simultaneous catheter channels, then infer intervals only with known prior charting.
    for (stay, time), g in output.groupby(["stay_id", "charttime"], sort=True):
        sid = f"mimic-{stay}"
        if sid not in starts:
            continue
        if set(g.valueuom.dropna().str.lower()) - {"ml"}:
            continue
        h = (time - starts[sid]).total_seconds() / 3600
        a = max(
            [h]
            + [(v - starts[sid]).total_seconds() / 3600 for v in g.storetime.dropna()]
        )
        writer.add(sid, h, a, "urine_output_ml", g.value.sum())
    # Timestamped procedures: dialysis excludes forecasts after it is documented.
    proc = read(root / "icu/procedureevents.csv.gz")
    for col in ("starttime", "storetime"):
        proc[col] = pd.to_datetime(proc[col], format="ISO8601")
    for r in proc.itertuples(index=False):
        sid = f"mimic-{r.stay_id}"
        if sid not in starts:
            continue
        var = (
            "rrt"
            if r.itemid in {225441, 225802, 225803, 225805, 225809, 225955}
            else "ventilation"
            if r.itemid in {225792, 225794}
            else None
        )
        if var:
            h = (r.starttime - starts[sid]).total_seconds() / 3600
            a = (r.storetime - starts[sid]).total_seconds() / 3600
            writer.add(sid, h, a, var, 1)
    items = read(root / "icu/d_items.csv.gz").set_index("itemid").label.to_dict()
    inp = read(root / "icu/inputevents.csv.gz")
    for col in ("starttime", "endtime", "storetime"):
        inp[col] = pd.to_datetime(inp[col], format="ISO8601")
    for r in inp.itertuples(index=False):
        sid = f"mimic-{r.stay_id}"
        if sid not in starts:
            continue
        h = (r.starttime - starts[sid]).total_seconds() / 3600
        a = (r.storetime - starts[sid]).total_seconds() / 3600
        label = str(items.get(r.itemid, ""))
        if str(getattr(r, "statusdescription", "")).lower() in (
            "rewritten",
            "cancelled",
        ):
            continue
        for var, pattern in DRUG_PATTERNS.items():
            if re.search(pattern, label, re.IGNORECASE):
                writer.add(sid, h, a, var, 1)
        # A complete infusion amount is only available after its documented end.
        if str(r.amountuom).lower() == "ml":
            end = (r.endtime - starts[sid]).total_seconds() / 3600
            writer.add(sid, end, max(end, a), "fluid_input_ml", r.amount)
    # Urine intervals are not assumed from irregular charting in the source release.
    writer.counts["urine_interval_assumption_disabled"] = 1
    return writer.finish()


def urine_cell_is_volume(path):
    text = str(path).lower()
    return "urine" in text and not re.search(
        r"irrig|dialys|24.?h|total|count|occurrence|mixed|stool", text
    )


def import_eicu_urine(writer, root):
    io = read(root / "intakeOutput.csv.gz")
    # cellPath identifies urine specifically; outputTotal includes drains/blood loss.
    urine = io[io.cellpath.map(urine_cell_is_volume)]
    for (uid, offset), group in urine.groupby(
        ["patientunitstayid", "intakeoutputoffset"]
    ):
        h = float(offset) / 60
        entry = pd.to_numeric(group.intakeoutputentryoffset, errors="coerce").max()
        available = max(h, float(entry) / 60) if pd.notna(entry) else h
        writer.add(
            f"eicu-{uid}",
            h,
            available,
            "urine_output_ml",
            pd.to_numeric(group.cellvaluenumeric, errors="coerce").sum(min_count=1),
        )


def eicu(con):
    root = DATA / "raw" / "eicu"
    table = read(root / "patient.csv.gz")
    writer = Writer(con, "eicu")
    validuid = set()
    for r in table.itertuples(index=False):
        age = 90 if str(r.age).strip().startswith(">") else number(r.age)
        if age is None or age < 18:
            continue
        duration = number(r.unitdischargeoffset)
        if duration is None or duration <= 0:
            continue
        weight = number(r.admissionweight)
        if weight is not None and not 20 <= weight <= 350:
            weight = None
        gender = str(r.gender).lower()
        patient = Patient(
            age=min(age, 100),
            sex=gender if gender in ("male", "female") else "unknown",
            weight_kg=weight,
            admission_type=admission(r.unitadmitsource),
        )
        sid = f"eicu-{r.patientunitstayid}"
        writer.stay(
            sid,
            f"eicu-{r.uniquepid}",
            f"eicu-{r.hospitalid}",
            duration / 60,
            patient,
            {"icu_type": r.unittype, "data_release": "eicu-crd-demo/2.0.1"},
        )
        validuid.add(r.patientunitstayid)
    labs = read(root / "lab.csv.gz")
    labs["variable"] = labs.labname.str.lower().str.strip().map(LAB_NAMES)
    expected_units = {
        "creatinine": "mg/dl",
        "bun": "mg/dl",
        "glucose": "mg/dl",
        "potassium": "mmol/l",
        "bicarbonate": "mmol/l",
        "lactate": "mmol/l",
        "sodium": "mmol/l",
        "hemoglobin": "g/dl",
        "wbc": "k/mcl",
    }
    for r in labs[labs.variable.notna()].itertuples(index=False):
        system_unit = str(r.labmeasurenamesystem).lower().strip()
        if system_unit != expected_units[r.variable]:
            writer.counts["rejected_lab_units"] += 1
            continue
        h = float(r.labresultoffset) / 60
        revised = number(r.labresultrevisedoffset)
        a = max(h, revised / 60) if revised is not None else h
        writer.add(f"eicu-{r.patientunitstayid}", h, a, r.variable, r.labresult)
    # Exact weighted hourly means across chunks. Final hour = end of bin,
    # so measurements later in an hour cannot enter predictions at its start.
    for filename, mapping in [
        (
            "vitalPeriodic.csv.gz",
            {
                "heartrate": "heart_rate",
                "sao2": "spo2",
                "respiration": "respiratory_rate",
                "temperature": "temperature",
                "systemicmean": "map",
            },
        ),
        ("vitalAperiodic.csv.gz", {"noninvasivemean": "map"}),
    ]:
        aggregate = defaultdict(lambda: [0.0, 0])
        for chunk in read(
            root / filename,
            usecols=["patientunitstayid", "observationoffset", *mapping],
            chunksize=150000,
        ):
            chunk = chunk[chunk.patientunitstayid.isin(validuid)].copy()
            chunk["hour"] = np.floor(chunk.observationoffset / 60) + 1
            chunk = chunk[(chunk.hour >= 0) & (chunk.hour <= 8760)]
            for col, var in mapping.items():
                values = pd.to_numeric(chunk[col], errors="coerce")
                low, high = RANGES[var]
                good = chunk[values.between(low, high)].copy()
                good[col] = values.loc[good.index]
                sums = good.groupby(["patientunitstayid", "hour"])[col].agg(
                    ["sum", "count"]
                )
                for (uid, h), row in sums.iterrows():
                    key = (int(uid), float(h), var)
                    aggregate[key][0] += row["sum"]
                    aggregate[key][1] += int(row["count"])
        for (uid, h, var), (total, count) in aggregate.items():
            writer.add(f"eicu-{uid}", h, h, var, total / count)
    import_eicu_urine(writer, root)
    treatment = read(root / "treatment.csv.gz")
    for r in treatment.itertuples(index=False):
        label = str(r.treatmentstring).lower()
        h = float(r.treatmentoffset) / 60
        if treatment_is_rrt(label):
            writer.add(f"eicu-{r.patientunitstayid}", h, h, "rrt", 1)
        if "mechanical ventilation" in label or "invasive ventilation" in label:
            writer.add(f"eicu-{r.patientunitstayid}", h, h, "ventilation", 1)
    infusion = read(root / "infusiondrug.csv.gz")
    for r in infusion.itertuples(index=False):
        h = float(r.infusionoffset) / 60
        for var, pattern in DRUG_PATTERNS.items():
            if re.search(pattern, str(r.drugname), re.IGNORECASE):
                writer.add(f"eicu-{r.patientunitstayid}", h, h, var, 1)
    meds = read(
        root / "medication.csv.gz",
        usecols=[
            "patientunitstayid",
            "drugstartoffset",
            "drugorderoffset",
            "drugordercancelled",
            "drugname",
        ],
    )
    for r in meds.itertuples(index=False):
        # Medication table is orders, not confirmed administrations; record availability
        # after both entry and intended start, and expose only contextual flags.
        start = number(r.drugstartoffset)
        entered = number(r.drugorderoffset)
        if start is None or entered is None:
            continue
        h = max(start, entered) / 60
        if str(r.drugordercancelled).lower() in ("yes", "true", "1"):
            continue
        for var, pattern in DRUG_PATTERNS.items():
            if re.search(pattern, str(r.drugname), re.IGNORECASE):
                writer.add(f"eicu-{r.patientunitstayid}", h, h, var, 1)
    history = read(root / "pastHistory.csv.gz")
    for r in history.itertuples(index=False):
        text = " ".join(
            str(getattr(r, col, ""))
            for col in ("pasthistorypath", "pasthistoryvalue", "pasthistoryvaluetext")
        ).lower()
        offset = number(r.pasthistoryoffset)
        entered = number(r.pasthistoryenteredoffset)
        if offset is None:
            continue
        available = max(offset, entered) if entered is not None else offset
        if history_is_dialysis(text):
            sid = f"eicu-{r.patientunitstayid}"
            if sid not in writer.valid:
                continue
            if available <= 0:
                row = con.execute(
                    "SELECT patient_json FROM stays WHERE stay_id=?", (sid,)
                ).fetchone()
                pat = Patient.model_validate_json(row[0])
                pat.chronic_dialysis = True
                con.execute(
                    "UPDATE stays SET patient_json=? WHERE stay_id=?",
                    (pat.model_dump_json(), sid),
                )
            else:
                writer.add(sid, available / 60, available / 60, "dialysis_history", 1)
            writer.counts["known_chronic_dialysis"] += 1
    writer.counts["urine_interval_assumption_disabled"] = 1
    return writer.finish()


def extract(source="all"):
    ensure_dirs()
    initialize()
    reports = {}
    with connect() as con:
        for name, adapter in (("mimic", mimic), ("eicu", eicu)):
            if source not in ("all", name):
                continue
            print(f"Extracting {name}...", flush=True)
            con.execute("DELETE FROM stays WHERE source=?", (name,))
            reports[name] = adapter(con)
            print(json.dumps(reports[name], indent=2), flush=True)
    from .storage import audits

    (REPORTS / "extraction.json").write_text(
        json.dumps(audits(), indent=2), encoding="utf-8"
    )
    return reports


def refresh_eicu_urine():
    """Rebuild just urine observations after a mapping correction, transactionally."""
    with connect() as con:
        previous = con.execute(
            "SELECT report_json FROM audit WHERE source='eicu'"
        ).fetchone()
        if previous is None:
            raise ValueError("eICU has not been extracted")
        writer = Writer(con, "eicu")
        writer.valid = {
            r[0] for r in con.execute("SELECT stay_id FROM stays WHERE source='eicu'")
        }
        old = json.loads(previous[0])
        writer.counts.update({k: v for k, v in old.items() if isinstance(v, int)})
        writer.counts["accepted_urine_output_ml"] = 0
        con.execute(
            "DELETE FROM observations WHERE variable=? AND stay_id IN (SELECT stay_id FROM stays WHERE source=?)",
            ("urine_output_ml", "eicu"),
        )
        import_eicu_urine(writer, DATA / "raw" / "eicu")
        result = writer.finish()
    from .storage import audits

    (REPORTS / "extraction.json").write_text(
        json.dumps(audits(), indent=2), encoding="utf-8"
    )
    return result
