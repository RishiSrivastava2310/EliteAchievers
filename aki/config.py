import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env():
    """Load simple KEY=value settings without overriding the process environment."""
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key.isidentifier():
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env()

DATA = ROOT / "data"
ARTIFACTS = ROOT / "artifacts"
REPORTS = ROOT / "reports"
DB_PATH = Path(os.environ.get("AKI_DB_PATH", str(DATA / "aki.sqlite3")))
MODEL_PATH = Path(os.environ.get("AKI_MODEL_PATH", str(ARTIFACTS / "model.joblib")))
SEED = 42
HORIZON = 24.0


def ensure_dirs():
    for path in (DATA, ARTIFACTS, REPORTS):
        path.mkdir(parents=True, exist_ok=True)
