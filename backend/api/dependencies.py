from __future__ import annotations

import os
import secrets
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal

ADMIN_API_KEY_HEADER = "X-Admin-Key"


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_configured_admin_api_key() -> str:
    return (
        os.getenv("ADMIN_API_KEY")
        or os.getenv("FRONTEND_API_SECRET")
        or ""
    ).strip()


def require_admin_api_key(
    x_admin_key: Annotated[str | None, Header(alias=ADMIN_API_KEY_HEADER)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    configured = get_configured_admin_api_key()
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="Admin API key is not configured.",
        )

    provided = (x_admin_key or "").strip()
    if not provided and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            provided = token.strip()

    if not provided or not secrets.compare_digest(provided, configured):
        raise HTTPException(status_code=403, detail="Forbidden")
