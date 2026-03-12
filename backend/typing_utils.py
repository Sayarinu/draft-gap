from __future__ import annotations

from typing import TypedDict


class TaskResult(TypedDict, total=False):
    status: str
    message: str
    rows: int
    saved: list[dict[str, object]]
    errors: list[str] | list[dict[str, object]]
    results: list[dict[str, object]]
    task_id: str
    games: int
    game_teams: int
    game_players: int
    features_computed: int
    teams_synced: int
    downloaded: str
    ingest: dict[str, object]
    features: dict[str, object]
    training: dict[str, object]
    checked: int
    found_in_db: int
    missing_count: int
    missing: list[dict[str, object]]
    stage: str
    matches_with_odds: int
    total_games: int
    total_players: int
    files: list[dict[str, object]]
    features_created: int
    models_trained: int
    run_ids: list[int]
    best_model: str | None
    pandascore: dict[str, object]
    thunderpick: dict[str, object]
    auto_bets: dict[str, object]
    progress: int


class ModelMetrics(TypedDict, total=False):
    accuracy: float
    log_loss: float
    roc_auc: float


class ModelRunResult(TypedDict, total=False):
    model_type: str
    model_version: str
    artifact_path: str
    config: dict[str, object]
    feature_names: list[str]
    train_metrics: dict[str, float]
    val_metrics: dict[str, float]
    test_metrics: dict[str, float]
    train_samples: int
    val_samples: int
    test_samples: int
    is_active: bool


class CheckCompletedResponse(TypedDict, total=False):
    status: str
    message: str
    checked: int
    found_in_db: int
    missing_count: int
    missing: list[dict[str, object]]
