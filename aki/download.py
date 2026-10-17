"""Download only allow-listed, unrestricted PhysioNet demo tables over verified HTTPS."""

import hashlib
import json
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from .artifacts import atomic_json
from .config import DATA, ensure_dirs

SOURCES = {
    "mimic": {
        "base": "https://physionet.org/files/mimic-iv-demo/2.2/",
        "citation": "https://physionet.org/content/mimic-iv-demo/2.2/",
        "files": [
            "hosp/patients.csv.gz",
            "hosp/admissions.csv.gz",
            "hosp/labevents.csv.gz",
            "hosp/d_labitems.csv.gz",
            "hosp/diagnoses_icd.csv.gz",
            "hosp/prescriptions.csv.gz",
            "icu/icustays.csv.gz",
            "icu/d_items.csv.gz",
            "icu/chartevents.csv.gz",
            "icu/outputevents.csv.gz",
            "icu/inputevents.csv.gz",
            "icu/procedureevents.csv.gz",
        ],
    },
    "eicu": {
        "base": "https://physionet.org/files/eicu-crd-demo/2.0.1/",
        "citation": "https://physionet.org/content/eicu-crd-demo/2.0.1/",
        "files": [
            "patient.csv.gz",
            "hospital.csv.gz",
            "lab.csv.gz",
            "vitalPeriodic.csv.gz",
            "vitalAperiodic.csv.gz",
            "intakeOutput.csv.gz",
            "infusiondrug.csv.gz",
            "medication.csv.gz",
            "treatment.csv.gz",
            "pastHistory.csv.gz",
            "diagnosis.csv.gz",
        ],
    },
}


def fetch(url: str) -> bytes:
    # Python's default SSL context uses the Windows system certificate store too.
    request = Request(url, headers={"User-Agent": "AKI-Hackathon-Research/0.1"})
    for attempt in range(3):
        try:
            with urlopen(
                request, timeout=90, context=ssl.create_default_context()
            ) as response:
                return response.read()
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError("Download failed")


def download(source: str = "all") -> dict:
    if source not in ("all", *SOURCES):
        raise ValueError("Unknown source; choose all, mimic or eicu")
    ensure_dirs()
    previous = DATA / "download_manifest.json"
    existing = (
        json.loads(previous.read_text(encoding="utf-8")) if previous.exists() else {}
    )
    retained = [
        r
        for r in existing.get("files", [])
        if source != "all" and r["source"] != source
    ]
    manifest = {"downloaded_at": datetime.now(UTC).isoformat(), "files": retained}
    for name, definition in SOURCES.items():
        if source not in ("all", name):
            continue
        folder = DATA / "raw" / name
        folder.mkdir(parents=True, exist_ok=True)
        checksum_bytes = fetch(definition["base"] + "SHA256SUMS.txt")
        (folder / "SHA256SUMS.txt").write_bytes(checksum_bytes)
        expected = {}
        for line in checksum_bytes.decode().splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                expected[parts[1].lstrip("* ./")] = parts[0]
        license_bytes = fetch(definition["base"] + "LICENSE.txt")
        (folder / "LICENSE.txt").write_bytes(license_bytes)

        def one(
            relative: str,
            *,
            folder=folder,
            expected=expected,
            name=name,
            definition=definition,
        ):
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            checksum = expected.get(relative)
            if checksum is None:
                raise ValueError(f"No publisher checksum for {name}/{relative}")
            if (
                path.exists()
                and hashlib.sha256(path.read_bytes()).hexdigest() == checksum
            ):
                payload = path.read_bytes()
            else:
                payload = fetch(definition["base"] + relative)
                if hashlib.sha256(payload).hexdigest() != checksum:
                    raise ValueError(f"Checksum mismatch: {relative}")
                temporary = path.with_suffix(path.suffix + ".part")
                temporary.write_bytes(payload)
                temporary.replace(path)
            print(f"  verified {name}/{relative}: {len(payload):,} bytes", flush=True)
            return {
                "source": name,
                "file": relative,
                "url": definition["base"] + relative,
                "sha256": checksum,
                "bytes": len(payload),
            }

        with ThreadPoolExecutor(max_workers=3) as pool:
            manifest["files"].extend(pool.map(one, definition["files"]))
    manifest["license"] = (
        "Open Data Commons Open Database License 1.0; see raw source LICENSE.txt files"
    )
    atomic_json(DATA / "download_manifest.json", manifest)
    return manifest
