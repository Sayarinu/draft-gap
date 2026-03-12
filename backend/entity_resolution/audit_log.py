from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from models_ml import EntityResolutionLog

logger = logging.getLogger(__name__)


def log_resolution(
    session: Session,
    *,
    raw_value: str,
    entity_type: str,
    resolved_id: int | None,
    method: str,
    confidence: float,
    source_system: str,
    resolved: bool = True,
) -> EntityResolutionLog:
    entry = EntityResolutionLog(
        raw_value=raw_value,
        entity_type=entity_type,
        resolved_id=resolved_id,
        method=method,
        confidence=confidence,
        source_system=source_system,
        resolved=resolved,
    )
    session.add(entry)
    return entry


def log_unresolved(
    session: Session,
    *,
    raw_value: str,
    entity_type: str,
    source_system: str,
    best_confidence: float = 0.0,
) -> EntityResolutionLog:
    logger.warning(
        "UNRESOLVED entity: type=%s raw=%r source=%s confidence=%.2f",
        entity_type,
        raw_value,
        source_system,
        best_confidence,
    )
    return log_resolution(
        session,
        raw_value=raw_value,
        entity_type=entity_type,
        resolved_id=None,
        method="unresolved",
        confidence=best_confidence,
        source_system=source_system,
        resolved=False,
    )


def get_unresolved_count(session: Session) -> dict[str, int]:
    from sqlalchemy import func

    rows = (
        session.query(EntityResolutionLog.entity_type, func.count())
        .filter(EntityResolutionLog.resolved == False)  # noqa: E712
        .group_by(EntityResolutionLog.entity_type)
        .all()
    )
    return {entity_type: count for entity_type, count in rows}


def get_unresolved_entries(
    session: Session,
    entity_type: str | None = None,
    limit: int = 100,
) -> list[EntityResolutionLog]:
    q = session.query(EntityResolutionLog).filter(
        EntityResolutionLog.resolved == False  # noqa: E712
    )
    if entity_type:
        q = q.filter(EntityResolutionLog.entity_type == entity_type)
    return q.order_by(EntityResolutionLog.created_at.desc()).limit(limit).all()
