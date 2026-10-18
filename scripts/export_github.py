"""Copy publishable source into GITHUB_FOLDER; never copy secrets or runtime data."""

import hashlib
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "GITHUB_FOLDER"
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "data",
    "artifacts",
    "reports",
    "tmp",
    "node_modules",
    "htmlcov",
    ".idea",
    ".vscode",
    ".codex",
    ".agents",
    ".aws",
}
GENERATED_EXAMPLES = {
    "real_patient.json",
    "real_patient_provenance.json",
    "false_alert.json",
    "false_alert_provenance.json",
    "missed_case.json",
    "missed_case_provenance.json",
    "case_manifest.json",
}
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".joblib",
    ".sqlite",
    ".sqlite3",
    ".log",
    ".tmp",
    ".pem",
    ".key",
}


def publishable_files():
    for directory, directories, files in os.walk(ROOT, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in EXCLUDED_DIRS
            and not name.startswith("GITHUB_FOLDER")
            and not (Path(directory) / name).is_symlink()
        )
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(ROOT)
            if path.is_symlink():
                continue
            if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
                continue
            if path.suffix.lower() in EXCLUDED_SUFFIXES or name == ".coverage":
                continue
            if relative.parts[0] == "examples" and name in GENERATED_EXAMPLES:
                continue
            yield path, relative


def configured_secrets():
    env = ROOT / ".env"
    if not env.is_file():
        return []
    secrets = []
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.partition("=")
        if (
            separator
            and not key.strip().startswith("#")
            and re.search(r"KEY|TOKEN|SECRET|PASSWORD", key, re.IGNORECASE)
        ):
            value = value.strip().strip(chr(34) + chr(39))
            if len(value) >= 8:
                secrets.append(value.encode())
    return secrets


def main():
    if DESTINATION.exists() and any(DESTINATION.iterdir()):
        raise SystemExit(
            "GITHUB_FOLDER already contains files; choose a fresh export folder before rerunning."
        )
    files = list(publishable_files())
    secrets = configured_secrets()
    for source, relative in files:
        payload = source.read_bytes()
        if any(secret in payload for secret in secrets) or re.search(
            rb"AIza[0-9A-Za-z_-]{35}", payload
        ):
            raise SystemExit(
                f"Possible credential found in {relative}; export stopped."
            )
    DESTINATION.mkdir(exist_ok=True)
    for source, relative in files:
        target = DESTINATION / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if (
            hashlib.sha256(source.read_bytes()).digest()
            != hashlib.sha256(target.read_bytes()).digest()
        ):
            raise SystemExit(f"Copy verification failed: {relative}")
    print(
        f"Created GITHUB_FOLDER: {len(files)} verified files; secrets, data and generated artifacts excluded."
    )
    print("On a fresh clone, run setup.bat, then show_graphs.bat.")


if __name__ == "__main__":
    main()
