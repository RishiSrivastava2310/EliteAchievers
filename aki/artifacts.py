"""Atomic local artifact writes. Model files are trusted project artifacts only."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import joblib


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def atomic_model(path, bundle):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=path.parent, suffix=".joblib.tmp", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        joblib.dump(bundle, temporary)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
