"""Strict, single-patient wide CSV parser shared by API and terminal."""

import csv
import io
from pathlib import Path

from .schema import Patient, PredictionRequest, Reading

PATIENT_FIELDS = set(Patient.model_fields)
READING_FIELDS = set(Reading.model_fields)
ID_FIELDS = {"patient_id", "stay_id"}


def parse_csv(text, at_hour=None):
    if len(text.encode("utf-8")) > 2_000_000:
        raise ValueError("CSV exceeds 2 MB; submit one patient history at a time")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    headers = reader.fieldnames
    if not headers or "hour" not in headers or "age" not in headers:
        raise ValueError("CSV requires hour and age columns; use examples/template.csv")
    if len(headers) != len(set(headers)):
        raise ValueError("Duplicate CSV headers")
    unknown = set(headers) - PATIENT_FIELDS - READING_FIELDS - ID_FIELDS
    if unknown:
        raise ValueError("Unknown CSV columns: " + ", ".join(sorted(unknown)))
    rows = list(reader)
    if not rows or len(rows) > 10000:
        raise ValueError("CSV must contain 1-10,000 rows")

    def value(s):
        return s.strip() if isinstance(s, str) else s

    for name in ID_FIELDS:
        ids = {value(r.get(name)) for r in rows if value(r.get(name))}
        if len(ids) > 1:
            raise ValueError(f"CSV contains multiple {name} values")
    patient_data = {}
    # CSV weights belong to timestamped readings. Promoting a later weight to
    # static patient context would leak it into earlier replay/urine checks.
    for name in PATIENT_FIELDS - {"weight_kg"}:
        vals = [value(r.get(name)) for r in rows if value(r.get(name))]
        if vals:
            if name != "weight_kg" and len(set(vals)) > 1:
                raise ValueError(
                    f"Patient metadata {name} must be consistent within a CSV"
                )
            patient_data[name] = vals[0]
    patient = Patient.model_validate(patient_data)
    readings = []
    for number, row in enumerate(rows, 2):
        if None in row:
            raise ValueError(f"Extra cells on CSV line {number}")
        data = {
            name: value(row[name]) for name in READING_FIELDS if value(row.get(name))
        }
        try:
            readings.append(Reading.model_validate(data))
        except ValueError as exc:
            details = (
                "; ".join(error["msg"] for error in exc.errors())
                if hasattr(exc, "errors")
                else str(exc)
            )
            raise ValueError(
                f"Invalid reading on CSV line {number}: {details}"
            ) from exc
    t = max(r.available_hour for r in readings) if at_hour is None else at_hour
    return PredictionRequest(patient=patient, at_hour=t, readings=readings)


def read_csv(path, at_hour=None):
    return parse_csv(Path(path).read_text(encoding="utf-8-sig"), at_hour)
