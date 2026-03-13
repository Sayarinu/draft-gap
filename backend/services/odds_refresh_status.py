from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

ODDS_REFRESH_CURRENT_TASK_ID_KEY = "odds:refresh:current_task_id"
ODDS_REFRESH_LAST_COMPLETED_AT_KEY = "odds:refresh:last_completed_at"
LAST_COMPLETED_AT_TTL_SECONDS = 86400

_redis_client: Redis | None = None
_redis_init_attempted = False


def _get_redis() -> Redis | None:
    global _redis_client, _redis_init_attempted
    if _redis_init_attempted:
        return _redis_client
    _redis_init_attempted = True
    redis_url = (os.getenv("REDIS_URL") or "").strip()
    if not redis_url:
        return None
    try:
        client = Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        _redis_client = client
    except Exception as e:
        logger.warning(
            "odds_refresh_status redis unavailable: error_type=%s error=%s",
            type(e).__name__,
            str(e),
        )
        _redis_client = None
    return _redis_client


def get_current_task_id() -> str | None:
    client = _get_redis()
    if client is None:
        return None
    try:
        raw = client.get(ODDS_REFRESH_CURRENT_TASK_ID_KEY)
        return str(raw).strip() if raw else None
    except RedisError as e:
        logger.warning(
            "odds_refresh_status get_current_task_id failed: error_type=%s error=%s",
            type(e).__name__,
            str(e),
        )
        return None


def set_current_task_id(task_id: str) -> bool:
    client = _get_redis()
    if client is None:
        return False
    try:
        client.set(
            ODDS_REFRESH_CURRENT_TASK_ID_KEY,
            task_id,
            ex=3600,
        )
        return True
    except RedisError as e:
        logger.warning(
            "odds_refresh_status set_current_task_id failed: error_type=%s error=%s",
            type(e).__name__,
            str(e),
        )
        return False


def clear_current_task_id() -> None:
    client = _get_redis()
    if client is None:
        return
    try:
        client.delete(ODDS_REFRESH_CURRENT_TASK_ID_KEY)
    except RedisError as e:
        logger.warning(
            "odds_refresh_status clear_current_task_id failed: error_type=%s error=%s",
            type(e).__name__,
            str(e),
        )


def set_last_completed_at(iso_timestamp: str) -> None:
    client = _get_redis()
    if client is None:
        return
    try:
        client.set(
            ODDS_REFRESH_LAST_COMPLETED_AT_KEY,
            iso_timestamp,
            ex=LAST_COMPLETED_AT_TTL_SECONDS,
        )
    except RedisError as e:
        logger.warning(
            "odds_refresh_status set_last_completed_at failed: error_type=%s error=%s",
            type(e).__name__,
            str(e),
        )


def get_last_completed_at() -> str | None:
    client = _get_redis()
    if client is None:
        return None
    try:
        raw = client.get(ODDS_REFRESH_LAST_COMPLETED_AT_KEY)
        return str(raw).strip() if raw else None
    except RedisError as e:
        logger.warning(
            "odds_refresh_status get_last_completed_at failed: error_type=%s error=%s",
            type(e).__name__,
            str(e),
        )
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def set_last_completed_at_now() -> None:
    set_last_completed_at(_utc_now_iso())
