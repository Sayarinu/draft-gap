from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal, init_db

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


class UnresolvedSummary(BaseModel):
    counts: dict[str, int]
    total: int


class UnresolvedEntry(BaseModel):
    id: int
    raw_value: str
    entity_type: str
    confidence: float
    source_system: str
    created_at: str


class ResolveRequest(BaseModel):
    entry_id: int
    canonical_name: str


class ResolveResponse(BaseModel):
    status: str
    resolved_id: int | None = None
    message: str


class ModelRunItem(BaseModel):
    id: int
    model_type: str
    model_version: str
    is_active: bool
    train_accuracy: float | None
    val_accuracy: float | None
    test_accuracy: float | None
    val_log_loss: float | None
    val_roc_auc: float | None
    train_samples: int | None
    val_samples: int | None
    test_samples: int | None
    created_at: str


@router.get("/entity-resolution/unresolved", response_model=UnresolvedSummary)
def get_unresolved_summary() -> UnresolvedSummary:
    from entity_resolution.audit_log import get_unresolved_count

    init_db()
    session = SessionLocal()
    try:
        counts = get_unresolved_count(session)
        return UnresolvedSummary(counts=counts, total=sum(counts.values()))
    finally:
        session.close()


@router.get("/entity-resolution/unresolved/list", response_model=list[UnresolvedEntry])
def list_unresolved(entity_type: str | None = None, limit: int = 100) -> list[UnresolvedEntry]:
    from entity_resolution.audit_log import get_unresolved_entries

    init_db()
    session = SessionLocal()
    try:
        entries = get_unresolved_entries(session, entity_type=entity_type, limit=limit)
        return [
            UnresolvedEntry(
                id=e.id,
                raw_value=e.raw_value,
                entity_type=e.entity_type,
                confidence=e.confidence,
                source_system=e.source_system,
                created_at=str(e.created_at),
            )
            for e in entries
        ]
    finally:
        session.close()


@router.post("/entity-resolution/resolve", response_model=ResolveResponse)
def resolve_entity(request: ResolveRequest) -> ResolveResponse:
    from entity_resolution.resolver import EntityResolver
    from models_ml import EntityResolutionLog

    init_db()
    session = SessionLocal()
    try:
        entry = session.query(EntityResolutionLog).get(request.entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        if entry.resolved:
            return ResolveResponse(status="already_resolved", resolved_id=entry.resolved_id, message="Already resolved")

        resolver = EntityResolver(session)
        entity_type = entry.entity_type

        resolved_id = None
        if entity_type == "team":
            team = resolver.resolve_team(request.canonical_name, "manual")
            if team:
                resolved_id = team.id
                from entity_resolution.canonical_store import add_team_alias
                add_team_alias(session, team.id, entry.raw_value, "manual")
        elif entity_type == "player":
            player = resolver.resolve_player(request.canonical_name, "manual")
            if player:
                resolved_id = player.id
                from entity_resolution.canonical_store import add_player_alias
                add_player_alias(session, player.id, entry.raw_value, "manual")
        elif entity_type == "champion":
            champ = resolver.resolve_champion(request.canonical_name, "manual")
            if champ:
                resolved_id = champ.id
        elif entity_type == "league":
            league = resolver.resolve_league(request.canonical_name, "manual")
            if league:
                resolved_id = league.id

        if resolved_id is not None:
            entry.resolved = True
            entry.resolved_id = resolved_id
            entry.method = "manual"
            entry.confidence = 1.0
            session.commit()
            return ResolveResponse(status="resolved", resolved_id=resolved_id, message=f"Resolved to {request.canonical_name}")
        else:
            raise HTTPException(status_code=400, detail="Could not resolve to the given canonical name")
    finally:
        session.close()


@router.get("/model-runs", response_model=list[ModelRunItem])
def list_model_runs() -> list[ModelRunItem]:
    from models_ml import MLModelRun

    init_db()
    session = SessionLocal()
    try:
        runs = session.query(MLModelRun).order_by(MLModelRun.created_at.desc()).limit(20).all()
        return [
            ModelRunItem(
                id=r.id,
                model_type=r.model_type,
                model_version=r.model_version,
                is_active=r.is_active,
                train_accuracy=r.train_accuracy,
                val_accuracy=r.val_accuracy,
                test_accuracy=r.test_accuracy,
                val_log_loss=r.val_log_loss,
                val_roc_auc=r.val_roc_auc,
                train_samples=r.train_samples,
                val_samples=r.val_samples,
                test_samples=r.test_samples,
                created_at=str(r.created_at),
            )
            for r in runs
        ]
    finally:
        session.close()
