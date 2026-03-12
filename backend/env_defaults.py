from __future__ import annotations

import os
from pathlib import Path

_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        pass

DEFAULTS: dict[str, str | int | float] = {
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "changeme",
    "POSTGRES_DB": "draftgap",
    "DATABASE_URL": "postgresql://postgres:changeme@db:5432/draftgap",
    "REDIS_URL": "redis://redis:6379/0",
    "PGADMIN_EMAIL": "admin@example.com",
    "PGADMIN_PASSWORD": "changeme",
    "VITE_API_URL": "http://localhost:8000",
    "FRONTEND_API_SECRET": "",
    "VITE_API_SECRET": "",
    "PANDA_SCORE_KEY": "",
    "ML_DEVICE": "cpu",
    "ML_MODEL_PATH": "./models",
    "RECENCY_HALFLIFE_DAYS": 30,
    "ML_EPOCHS": 50,
    "ML_BATCH_SIZE": 64,
    "ML_LR": 0.001,
    "ML_VAL_FRAC": 0.15,
    "INGEST_API_URL": "http://localhost:8000",
    "INGEST_REQUEST_TIMEOUT": 60,
    "CLOUDFLARE_PURGE_ENABLED": "false",
    "CLOUDFLARE_ZONE_ID": "",
    "CLOUDFLARE_API_TOKEN": "",
    "CLOUDFLARE_PURGE_TIMEOUT_SECONDS": 10,
}


def get_required(key: str) -> str:
    default = DEFAULTS.get(key, "")
    val = os.getenv(key, str(default) if default is not None else "")
    if isinstance(val, str):
        val = val.strip()
    return val if val else str(default)


def get_int(key: str) -> int:
    default = DEFAULTS.get(key, 0)
    if isinstance(default, str):
        try:
            default = int(default)
        except ValueError:
            default = 0
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return int(default)
    try:
        return int(float(raw))
    except ValueError:
        return int(default)


def get_float(key: str) -> float:
    default = DEFAULTS.get(key, 0.0)
    if isinstance(default, str):
        try:
            default = float(default)
        except ValueError:
            default = 0.0
    raw = os.getenv(key)
    if raw is None or not str(raw).strip():
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)
