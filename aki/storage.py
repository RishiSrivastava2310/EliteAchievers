"""SQLite repository. Parameterized queries and explicit, indexed source separation."""

import json
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH, ensure_dirs
from .schema import Patient, Reading

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS stays (
    stay_id TEXT PRIMARY KEY, source TEXT NOT NULL, patient_id TEXT NOT NULL,
    hospital_id TEXT NOT NULL, duration_hours REAL NOT NULL, patient_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stays_source ON stays(source,patient_id,hospital_id);
CREATE TABLE IF NOT EXISTS observations (
    stay_id TEXT NOT NULL REFERENCES stays(stay_id) ON DELETE CASCADE,
    hour REAL NOT NULL, available_hour REAL NOT NULL, variable TEXT NOT NULL,
    value REAL NOT NULL, interval_hours REAL,
    PRIMARY KEY(stay_id,hour,available_hour,variable)
);
CREATE INDEX IF NOT EXISTS idx_obs_available ON observations(stay_id,available_hour,hour);
CREATE TABLE IF NOT EXISTS audit (source TEXT PRIMARY KEY, report_json TEXT NOT NULL);
"""


@contextmanager
def connect(path=None):
    target = path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def initialize(path=None):
    ensure_dirs()
    with connect(path) as con:
        con.executescript(SCHEMA)


def list_stays(source=None, limit=50, offset=0, path=None, search=None):
    with connect(path) as con:
        clauses, args = [], []
        if source:
            clauses.append("source=?")
            args.append(source)
        if search and search.strip():
            escaped = (
                search.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            clauses.append(
                "(stay_id LIKE ? ESCAPE '\\' OR patient_id LIKE ? ESCAPE '\\')"
            )
            args.extend(["%" + escaped + "%"] * 2)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        total = con.execute("SELECT COUNT(*) FROM stays" + where, args).fetchone()[0]
        rows = con.execute(
            "SELECT * FROM stays" + where + " ORDER BY stay_id LIMIT ? OFFSET ?",
            [*args, limit, offset],
        ).fetchall()
    return {
        "total": total,
        "items": [
            {
                k: r[k]
                for k in (
                    "stay_id",
                    "source",
                    "patient_id",
                    "hospital_id",
                    "duration_hours",
                )
            }
            for r in rows
        ],
    }


def load_stay(stay_id, at_hour=None, path=None):
    with connect(path) as con:
        row = con.execute("SELECT * FROM stays WHERE stay_id=?", (stay_id,)).fetchone()
        if row is None:
            raise KeyError(stay_id)
        sql = "SELECT * FROM observations WHERE stay_id=?"
        args = [stay_id]
        if at_hour is not None:
            sql += " AND hour<=? AND available_hour<=?"
            args.extend([at_hour, at_hour])
        obs = con.execute(sql + " ORDER BY hour,available_hour", args).fetchall()
    grouped = {}
    for x in obs:
        key = (x["hour"], x["available_hour"])
        target = grouped.setdefault(
            key, {"hour": x["hour"], "available_hour": x["available_hour"]}
        )
        target[x["variable"]] = x["value"]
        if x["variable"] == "urine_output_ml" and x["interval_hours"] is not None:
            target["urine_interval_hours"] = x["interval_hours"]
    return {
        "stay_id": row["stay_id"],
        "source": row["source"],
        "patient_id": row["patient_id"],
        "hospital_id": row["hospital_id"],
        "duration_hours": row["duration_hours"],
        "patient": Patient.model_validate_json(row["patient_json"]),
        "metadata": json.loads(row["metadata_json"]),
        "readings": [Reading.model_validate(v) for v in grouped.values()],
    }


def audits(path=None):
    with connect(path) as con:
        return {
            r["source"]: json.loads(r["report_json"])
            for r in con.execute("SELECT * FROM audit")
        }
