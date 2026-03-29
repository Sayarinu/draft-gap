from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "active_model_manifest.json"


class ModelManifest(TypedDict, total=False):
    source_run_id: int
    model_type: str
    model_version: str
    active_artifact_basename: str
    active_artifact_path: str
    trained_at: str
    promoted_at: str


def get_model_dir() -> Path:
    model_dir = Path(os.environ.get("ML_MODEL_PATH", "./models"))
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def get_manifest_path() -> Path:
    return get_model_dir() / MANIFEST_FILENAME


def read_model_manifest() -> ModelManifest | None:
    manifest_path = get_manifest_path()
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read model manifest at %s", manifest_path, exc_info=True)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def write_model_manifest(
    *,
    source_run_id: int,
    model_type: str,
    model_version: str,
    artifact_path: str,
    trained_at: datetime | None = None,
) -> ModelManifest:
    manifest_path = get_manifest_path()
    artifact = Path(artifact_path)
    trained_at_value = trained_at or datetime.now(timezone.utc)
    payload: ModelManifest = {
        "source_run_id": source_run_id,
        "model_type": model_type,
        "model_version": model_version,
        "active_artifact_basename": artifact.name,
        "active_artifact_path": str(artifact),
        "trained_at": trained_at_value.astimezone(timezone.utc).isoformat(),
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }
    temp_path = manifest_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(manifest_path)
    return payload
