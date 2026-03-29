from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_db
from models_ml import HomepageSnapshotManifest
from services.homepage_snapshots import (
    apply_snapshot_headers,
    build_homepage_bootstrap_payload,
    get_active_snapshot,
)

router = APIRouter(prefix="/homepage", tags=["homepage"])


class HomepageBootstrapResponse(BaseModel):
    generated_at: str | None = None
    results_generated_at: str | None = None
    upcoming: dict[str, Any]
    live: dict[str, Any]
    bankroll: dict[str, Any] | None = None
    active_bets: list[dict[str, Any]]
    active_positions_by_series: list[dict[str, Any]] = []
    match_betting_statuses: list[dict[str, Any]] = []
    power_rankings_preview: list[dict[str, Any]]
    refresh_status: dict[str, Any]
    section_status: dict[str, Any] = {}


@router.get("/bootstrap", response_model=HomepageBootstrapResponse)
def get_homepage_bootstrap(
    response: Response,
    session: Session = Depends(get_db),
) -> HomepageBootstrapResponse:
    snapshot = get_active_snapshot(session, HomepageSnapshotManifest)
    apply_snapshot_headers(response, snapshot, key="homepage")
    payload = build_homepage_bootstrap_payload(session, homepage_snapshot=snapshot)
    return HomepageBootstrapResponse.model_validate(payload)
