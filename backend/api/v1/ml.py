from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_db, require_admin_api_key
from ml.config import get_model_path
from typing_utils import CheckCompletedResponse

router = APIRouter(prefix="/ml", tags=["ml"])
logger = logging.getLogger(__name__)


class PredictRequest(BaseModel):
    team_name: str | None = Field(None, min_length=1, max_length=120)
    picks: list[str] = Field(default_factory=list)
    side: str | None = Field(None)
    stats: dict[str, int | float | bool | str] | None = Field(None)


class PredictResponse(BaseModel):
    win_probability: float
    side: str | None = None


class MatchPredictRequest(BaseModel):
    team_a: str = Field(min_length=1, max_length=120)
    team_b: str = Field(min_length=1, max_length=120)
    series_format: str = Field(default="BO1", pattern="^BO[135]$")
    score_a: int = Field(default=0, ge=0, le=5)
    score_b: int = Field(default=0, ge=0, le=5)
    patch: str | None = Field(default=None, max_length=32)
    league: str | None = Field(default=None, max_length=64)
    playoffs: bool = Field(default=False)


class MatchPredictResponse(BaseModel):
    winner: str
    confidence: float
    game_win_prob_a: float
    series_win_prob_a: float
    series_win_prob_b: float
    decimal_odds_a: float
    decimal_odds_b: float
    series_format: str
    series_score_a: int
    series_score_b: int
    key_factors: list[str] = Field(default_factory=list)
    flag: str | None = None
    model_type: str | None = None


class PipelineResponse(BaseModel):
    status: str
    message: str
    task_id: str | None = None


class CheckCompletedPydantic(BaseModel):
    status: str
    message: str | None = None
    checked: int | None = None
    found_in_db: int | None = None
    missing_count: int | None = None
    missing: list[dict[str, object]] | None = None


@router.post("/predict", response_model=PredictResponse)
def predict_legacy(request: PredictRequest) -> PredictResponse:
    from ml.predictor import predict_win_probability

    model_dir = Path(get_model_path())
    if not (model_dir / "win_probability_model.pt").exists():
        raise HTTPException(status_code=503, detail="Legacy model not trained. Use /ml/predict/match instead.")
    try:
        prob = predict_win_probability(team_name=request.team_name, picks=request.picks, stats=request.stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e!s}") from e
    return PredictResponse(
        win_probability=round(prob, 4),
        side=request.side if request.side in ("blue", "red") else None,
    )


@router.post("/predict/match", response_model=MatchPredictResponse)
def predict_match_v2(
    request: MatchPredictRequest,
    session: Session = Depends(get_db),
) -> MatchPredictResponse:
    from entity_resolution.resolver import EntityResolver
    from ml.predictor_v2 import predict_match

    resolver = EntityResolver(session)

    team_a = resolver.resolve_team(request.team_a, "api", allow_mutations=False)
    team_b = resolver.resolve_team(request.team_b, "api", allow_mutations=False)

    if not team_a:
        raise HTTPException(status_code=404, detail=f"Team not found: {request.team_a}")
    if not team_b:
        raise HTTPException(status_code=404, detail=f"Team not found: {request.team_b}")

    result = predict_match(
        session,
        team_a.id,
        team_b.id,
        series_format=request.series_format,
        score_a=request.score_a,
        score_b=request.score_b,
        patch=request.patch,
        league_slug=request.league,
        playoffs=request.playoffs,
        persist_prediction_log=False,
    )
    if not result:
        raise HTTPException(status_code=503, detail="No trained model available. Run the training pipeline first.")

    winner = "team_a" if result["series_win_prob_a"] >= 0.5 else "team_b"
    confidence = max(result["series_win_prob_a"], result["series_win_prob_b"])

    return MatchPredictResponse(
        winner=winner,
        confidence=round(confidence, 4),
        game_win_prob_a=round(result["game_win_prob_a"], 4),
        series_win_prob_a=round(result["series_win_prob_a"], 4),
        series_win_prob_b=round(result["series_win_prob_b"], 4),
        decimal_odds_a=result["decimal_odds_a"],
        decimal_odds_b=result["decimal_odds_b"],
        series_format=result["series_format"],
        series_score_a=result["series_score_a"],
        series_score_b=result["series_score_b"],
        key_factors=result.get("key_factors", []),
        flag=result.get("confidence_flag"),
        model_type=result.get("model_type"),
    )


@router.post("/pipeline/ingest", response_model=PipelineResponse)
def trigger_ingest(
    data_dir: Annotated[str, Query(min_length=1, max_length=500)] = "/data/matches",
    _: None = Depends(require_admin_api_key),
) -> PipelineResponse:
    from tasks import task_ingest_normalized
    result = task_ingest_normalized.delay(data_dir)
    return PipelineResponse(status="accepted", message="Ingestion started", task_id=result.id)


@router.post("/pipeline/features", response_model=PipelineResponse)
def trigger_feature_engineering(
    _: None = Depends(require_admin_api_key),
) -> PipelineResponse:
    from tasks import task_feature_engineering
    result = task_feature_engineering.delay()
    return PipelineResponse(status="accepted", message="Feature engineering started", task_id=result.id)


@router.post("/pipeline/train", response_model=PipelineResponse)
def trigger_training(
    _: None = Depends(require_admin_api_key),
) -> PipelineResponse:
    from tasks import task_model_training
    result = task_model_training.delay()
    return PipelineResponse(status="accepted", message="Model training started", task_id=result.id)


@router.post("/pipeline/full", response_model=PipelineResponse)
def trigger_full_pipeline(
    data_dir: Annotated[str, Query(min_length=1, max_length=500)] = "/data/matches",
    _: None = Depends(require_admin_api_key),
) -> PipelineResponse:
    from tasks import task_full_pipeline
    result = task_full_pipeline.delay(data_dir)
    return PipelineResponse(status="accepted", message="Full pipeline started", task_id=result.id)


@router.post("/pipeline/sync-rosters", response_model=PipelineResponse)
def trigger_roster_sync(
    _: None = Depends(require_admin_api_key),
) -> PipelineResponse:
    from tasks import task_sync_rosters
    result = task_sync_rosters.delay()
    return PipelineResponse(status="accepted", message="Roster sync started", task_id=result.id)


@router.post("/pipeline/refresh-data", response_model=PipelineResponse)
def trigger_data_refresh(
    _: None = Depends(require_admin_api_key),
) -> PipelineResponse:
    from tasks import task_refresh_data
    result = task_refresh_data.delay()
    return PipelineResponse(status="accepted", message="Data refresh started", task_id=result.id)


@router.post("/pipeline/check-completed", response_model=CheckCompletedPydantic)
def trigger_check_completed(
    _: None = Depends(require_admin_api_key),
) -> CheckCompletedPydantic:
    from tasks import task_check_completed_matches
    result = task_check_completed_matches()
    return CheckCompletedPydantic(**result)


@router.post("/pipeline/refresh-thunderpick", response_model=PipelineResponse)
def trigger_thunderpick_refresh(
    _: None = Depends(require_admin_api_key),
) -> PipelineResponse:
    from tasks import refresh_thunderpick_odds
    result = refresh_thunderpick_odds.delay()
    return PipelineResponse(status="accepted", message="Betting odds refresh started", task_id=result.id)
