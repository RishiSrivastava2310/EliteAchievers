"""Choose a real patient in the standalone report without opening a browser."""

import json
from pathlib import Path
from urllib.parse import urlencode

from .artifacts import atomic_json


def select_report(reports: Path, action: str = "open"):
    if action not in {"open", "next"}:
        raise ValueError("Use open or next.")
    manifest = json.loads((reports / "showcase_manifest.json").read_text())
    patients = [c["id"] for c in manifest["cases"] if c.get("kind") == "patient"]
    if not patients:
        raise ValueError("Build the patient reports first.")
    position = 0
    if action == "next":
        try:
            saved = json.loads((reports / "showcase_cursor.json").read_text())
            if saved.get("model_sha256") == manifest["model_sha256"]:
                position = patients.index(saved.get("patient"))
        except (OSError, ValueError, TypeError, AttributeError):
            position = 0
        position = (position + 1) % len(patients)
    patient = patients[position]
    atomic_json(
        reports / "showcase_cursor.json",
        {"model_sha256": manifest["model_sha256"], "patient": patient},
    )
    url = (reports / "judge_showcase.html").resolve().as_uri()
    url += "#" + urlencode({"patient": patient})
    (reports / "showcase_open_url.txt").write_text(url, encoding="ascii")
    return position + 1, len(patients), url
