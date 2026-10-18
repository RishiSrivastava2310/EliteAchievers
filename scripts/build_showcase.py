"""Build the offline graph demo; optionally request plain-language AI explanations."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aki.showcase import build_fingerprint, build_showcase
from aki.showcase_navigation import select_report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("open", "next"), default="open")
    parser.add_argument("--ai", action="store_true")
    parser.add_argument("--if-needed", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    manifest = ROOT / "reports/showcase_manifest.json"
    reuse = False
    if args.if_needed and not args.refresh and manifest.exists():
        try:
            saved = json.loads(manifest.read_text())
            reuse = (
                saved.get("build_fingerprint") == build_fingerprint(args.ai)
                and (ROOT / "reports/judge_showcase.html").is_file()
            )
        except (ValueError, OSError):
            reuse = False
    if reuse:
        print("Graph demo is ready.")
    else:
        build_showcase(include_ai=args.ai)
    number, total, _ = select_report(ROOT / "reports", args.action)
    print(f"Patient report {number} of {total} is ready.")
