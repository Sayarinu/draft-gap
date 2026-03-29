from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import PlainTextResponse

from api.dependencies import get_db, require_admin_api_key
from betting.bet_manager import get_match_betting_diagnostics
from services.runtime_diagnostics import (
    build_match_feed_comparison_payload,
    build_operator_debug_payload,
    build_runtime_status_payload,
    render_operator_debug_report,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_api_key)],
)
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
    entry_id: int = Field(ge=1)
    canonical_name: str = Field(min_length=1, max_length=200)


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


class RuntimeStatusResponse(BaseModel):
    model_runtime: dict[str, object]
    snapshot_status: dict[str, dict[str, object]]
    betting_state: dict[str, object]
    force_window_blockers: dict[str, object]
    refresh_status: dict[str, object]
    odds_attachment_status: dict[str, dict[str, object] | None]
    thunderpick_scrape_status: dict[str, object] | None = None
    detected_issues: list[str]


class MatchDecisionDiagnosticResponse(BaseModel):
    pandascore_match_id: int
    scheduled_at: str | None = None
    league: str | None = None
    team_a: str
    team_b: str
    series_format: str
    status: str
    reason_code: str | None = None
    reason_detail: str | None = None
    short_detail: str | None = None
    within_force_window: bool = False
    force_bet_after: str | None = None
    position_count: int = 0
    is_bettable: bool = False
    eligibility_reason: str | None = None
    odds_source_kind: str | None = None
    odds_source_status: str | None = None
    market_offer_count: int = 0
    has_match_winner_offer: bool = False
    terminal_outcome: str | None = None
    diagnostics: dict[str, Any] = {}


class BettingDiagnosticsResponse(BaseModel):
    summary: dict[str, Any]
    matches: list[MatchDecisionDiagnosticResponse]


class AdminDebugReportResponse(BaseModel):
    generated_at: str
    runtime_status: dict[str, Any]
    betting_diagnostics: dict[str, Any]
    component_checks: list[dict[str, Any]]
    recommendations: list[str]
    detected_issues: list[str]


class MatchFeedComparisonRowResponse(BaseModel):
    pandascore_match_id: int
    scheduled_at: str | None = None
    league: str | None = None
    team_a: str
    team_b: str
    in_homepage_visible: bool
    in_upcoming_snapshot: bool
    in_upcoming_source_matches: bool
    in_betting_statuses: bool
    betting_status: str | None = None
    reason_code: str | None = None
    short_detail: str | None = None
    is_bettable: bool = False
    eligibility_reason: str | None = None
    bookie_odds_present: bool = False
    odds_source_kind: str | None = None
    discrepancy_codes: list[str] = []


class MatchFeedComparisonResponse(BaseModel):
    summary: dict[str, Any]
    sources: dict[str, Any]
    matches: list[MatchFeedComparisonRowResponse]


@router.get("/entity-resolution/unresolved", response_model=UnresolvedSummary)
def get_unresolved_summary(
    session: Session = Depends(get_db),
) -> UnresolvedSummary:
    from entity_resolution.audit_log import get_unresolved_count

    counts = get_unresolved_count(session)
    return UnresolvedSummary(counts=counts, total=sum(counts.values()))


@router.get("/entity-resolution/unresolved/list", response_model=list[UnresolvedEntry])
def list_unresolved(
    entity_type: Annotated[
        str | None,
        Query(pattern="^(team|player|champion|league)$"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    session: Session = Depends(get_db),
) -> list[UnresolvedEntry]:
    from entity_resolution.audit_log import get_unresolved_entries

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


@router.post("/entity-resolution/resolve", response_model=ResolveResponse)
def resolve_entity(
    request: ResolveRequest,
    session: Session = Depends(get_db),
) -> ResolveResponse:
    from entity_resolution.resolver import EntityResolver
    from models_ml import EntityResolutionLog

    entry = session.get(EntityResolutionLog, request.entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.resolved:
        return ResolveResponse(
            status="already_resolved",
            resolved_id=entry.resolved_id,
            message="Already resolved",
        )

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

    if resolved_id is None:
        raise HTTPException(
            status_code=400,
            detail="Could not resolve to the given canonical name",
        )

    entry.resolved = True
    entry.resolved_id = resolved_id
    entry.method = "manual"
    entry.confidence = 1.0
    session.commit()
    return ResolveResponse(
        status="resolved",
        resolved_id=resolved_id,
        message=f"Resolved to {request.canonical_name}",
    )


@router.get("/model-runs", response_model=list[ModelRunItem])
def list_model_runs(
    session: Session = Depends(get_db),
) -> list[ModelRunItem]:
    from models_ml import MLModelRun

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


@router.get("/runtime-status", response_model=RuntimeStatusResponse)
def get_runtime_status(
    session: Session = Depends(get_db),
) -> RuntimeStatusResponse:
    return RuntimeStatusResponse.model_validate(build_runtime_status_payload(session))


@router.get("/betting/diagnostics", response_model=BettingDiagnosticsResponse)
def get_betting_diagnostics(
    search: str | None = Query(default=None, max_length=120),
    match_id: int | None = Query(default=None, ge=1),
    include_live: bool = Query(default=True),
    include_placed: bool = Query(default=False),
    limit: int = Query(default=25, ge=1, le=200),
    session: Session = Depends(get_db),
) -> BettingDiagnosticsResponse:
    payload = get_match_betting_diagnostics(
        session,
        search=search,
        match_id=match_id,
        include_live=include_live,
        include_placed=include_placed,
        limit=limit,
    )
    return BettingDiagnosticsResponse.model_validate(payload)


@router.get("/match-feed-compare", response_model=MatchFeedComparisonResponse)
def get_match_feed_compare(
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    mismatches_only: bool = Query(default=False),
    session: Session = Depends(get_db),
) -> MatchFeedComparisonResponse:
    payload = build_match_feed_comparison_payload(
        session,
        search=search,
        limit=limit,
        mismatches_only=mismatches_only,
    )
    return MatchFeedComparisonResponse.model_validate(payload)


@router.get("/debug-report", response_model=AdminDebugReportResponse)
def get_admin_debug_report(
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=10, ge=1, le=50),
    output: str = Query(default="json", pattern="^(json|text)$"),
    session: Session = Depends(get_db),
):
    payload = build_operator_debug_payload(
        session,
        search=search,
        limit=limit,
    )
    if output == "text":
        return PlainTextResponse(render_operator_debug_report(payload))
    return AdminDebugReportResponse.model_validate(payload)
