from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def _is_enabled(raw_value: str | None) -> bool:
    if raw_value is None:
        return False
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def purge_cloudflare_cache(reason: str) -> bool:
    if not _is_enabled(os.getenv("CLOUDFLARE_PURGE_ENABLED")):
        return False

    zone_id = (os.getenv("CLOUDFLARE_ZONE_ID") or "").strip()
    api_token = (os.getenv("CLOUDFLARE_API_TOKEN") or "").strip()
    if not zone_id or not api_token:
        logger.warning(
            "cloudflare.purge skipped: missing credentials enabled=%s zone_id_present=%s token_present=%s reason=%s",
            os.getenv("CLOUDFLARE_PURGE_ENABLED"),
            bool(zone_id),
            bool(api_token),
            reason,
        )
        return False

    timeout_raw = (os.getenv("CLOUDFLARE_PURGE_TIMEOUT_SECONDS") or "10").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError:
        timeout_seconds = 10.0

    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, object] = {"purge_everything": True}

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()

        if not isinstance(body, dict):
            logger.warning(
                "cloudflare.purge unexpected response type=%s reason=%s",
                type(body).__name__,
                reason,
            )
            return False

        success = bool(body.get("success"))
        if not success:
            logger.warning(
                "cloudflare.purge failed reason=%s errors=%s",
                reason,
                body.get("errors"),
            )
            return False

        logger.info("cloudflare.purge success reason=%s", reason)
        return True
    except Exception as exc:
        logger.warning(
            "cloudflare.purge error reason=%s error_type=%s error=%s",
            reason,
            type(exc).__name__,
            str(exc),
            exc_info=True,
        )
        return False
