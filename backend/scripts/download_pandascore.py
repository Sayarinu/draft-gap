#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys

_backend_root = os.environ.get("PYTHONPATH", "/app")
if not os.path.isdir(_backend_root):
    _backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from services.pandascore import download_upcoming_lol_fixtures


def main() -> int:
    tiers_env = os.environ.get("PANDASCORE_TIERS", "").strip()
    tiers = [t.strip() for t in tiers_env.split(",") if t.strip()] or None
    try:
        summary = download_upcoming_lol_fixtures(tiers=tiers)
    except Exception as e:
        summary = {"saved": [], "errors": [{"global": str(e)}]}
    print(json.dumps(summary))
    return 0 if not summary.get("errors") else 1


if __name__ == "__main__":
    sys.exit(main())
