"""Refresh disclosed examples after a successful training run."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aki.demo_cases import refresh_cases

if __name__ == "__main__":
    print(json.dumps(refresh_cases(), indent=2))
