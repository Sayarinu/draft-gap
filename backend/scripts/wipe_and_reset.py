#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

_env = _backend.parent / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env)
    except ImportError:
        pass

from sqlalchemy import text

from database import engine

TABLES = [
    "game_team",
    "team_rating",
    "game",
    "league_alias",
    "team_alias",
    "league",
    "team",
    "game_stats",
]


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Wipe app tables (and optionally Celery queue)")
    parser.add_argument("--purge-queue", action="store_true", help="Purge Celery task queue in Redis")
    args = parser.parse_args()

    print("Dropping app tables...")
    with engine.begin() as conn:
        for table in TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            print(f"  Dropped {table}")
    print("Done. Restart the API to recreate tables (init_db), then run generate_models.py and ingest.")

    if args.purge_queue:
        try:
            import redis
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            r = redis.from_url(redis_url)
            r.flushdb()
            print("Celery queue (Redis DB) purged.")
        except Exception as e:
            print(f"Could not purge queue: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
