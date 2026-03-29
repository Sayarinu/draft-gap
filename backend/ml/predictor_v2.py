from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from ml.feature_engineer import (
    LEAGUE_TIER_WEIGHTS,
    _patch_to_float,
    _rolling_team_stats,
    _h2h_stats,
    load_game_data,
)
from ml.series_probability import (
    compute_live_series_odds,
    number_of_games_to_format,
    prob_to_decimal_odds,
)
from ml.model_manifest import read_model_manifest
from models_ml import MLModelRun, PredictionLog
from models_ml import Game

logger = logging.getLogger(__name__)

_cached_model: dict[str, object] = {}
_cached_game_data: dict[str, object] = {}


def _clamp_probability(value: float) -> float:
    return max(0.01, min(0.99, value))


def _compute_mid_series_adjustments(
    *,
    base_game_win_prob: float,
    score_a: int,
    score_b: int,
    games_to_win: int,
    blue_stats: dict[str, float],
    red_stats: dict[str, float],
    h2h: dict[str, float],
    league_slug: str | None,
) -> dict[str, float | bool | str]:
    score_delta = score_a - score_b
    win_rate_delta = float(blue_stats.get("win_rate", 0.5) - red_stats.get("win_rate", 0.5))
    early_game_delta = float(blue_stats.get("avg_golddiffat15", 0.0) - red_stats.get("avg_golddiffat15", 0.0))
    h2h_delta = float(h2h.get("h2h_win_rate", 0.5) - 0.5)
    league_weight = LEAGUE_TIER_WEIGHTS.get((league_slug or "").lower(), 0.5)

    # Heuristic v1: blend series momentum with recent strength and mild H2H context.
    momentum_adjustment = 0.055 * score_delta
    form_adjustment = max(-0.05, min(0.05, win_rate_delta * 0.12))
    early_game_adjustment = max(-0.03, min(0.03, early_game_delta / 10000.0))
    h2h_adjustment = max(-0.02, min(0.02, h2h_delta * 0.08))
    confidence = min(
        0.92,
        0.45
        + min(float(blue_stats.get("games_played", 0.0)), 10.0) * 0.02
        + min(float(red_stats.get("games_played", 0.0)), 10.0) * 0.02
        + min(float(h2h.get("h2h_games", 0.0)), 5.0) * 0.03
        + abs(score_delta) * 0.05,
    )
    adjusted = _clamp_probability(
        base_game_win_prob
        + momentum_adjustment
        + form_adjustment
        + early_game_adjustment
        + h2h_adjustment
        + ((league_weight - 0.5) * 0.04)
    )
    return {
        "adjusted_game_win_prob_a": adjusted,
        "confidence": confidence,
        "mid_series_delta": adjusted - base_game_win_prob,
        "rebet_allowed": games_to_win > 1 and (score_a > 0 or score_b > 0),
    }


def clear_prediction_caches() -> None:
    _cached_model.clear()
    _cached_game_data.clear()


def _artifact_is_available(path: Path, model_type: str) -> bool:
    required_paths = {
        "xgboost": [path.with_suffix(".xgb"), path.with_suffix(".meta")],
        "logistic_regression": [path],
        "mlp": [path.with_suffix(".pt"), path.with_suffix(".scaler")],
    }.get(model_type, [path])
    return all(candidate.exists() for candidate in required_paths)


def _load_model_run(run: MLModelRun) -> dict[str, object]:
    artifact_path = Path(run.artifact_path)
    model_type = run.model_type
    next_cache: dict[str, object] = {
        "run_id": run.id,
        "artifact_path": run.artifact_path,
        "model_version": run.model_version,
        "model_type": model_type,
    }

    if model_type == "xgboost":
        from ml.model_registry import load_xgboost
        model, fnames = load_xgboost(artifact_path)
        next_cache.update({
            "loaded": True,
            "model": model,
            "type": "xgboost",
            "feature_names": fnames,
        })
    elif model_type == "logistic_regression":
        from ml.model_registry import load_logistic
        model, scaler, fnames = load_logistic(artifact_path)
        next_cache.update({
            "loaded": True,
            "model": model,
            "scaler": scaler,
            "type": "logistic_regression",
            "feature_names": fnames,
        })
    elif model_type == "mlp":
        from ml.model_registry import load_mlp
        model, scaler, fnames = load_mlp(artifact_path)
        next_cache.update({
            "loaded": True,
            "model": model,
            "scaler": scaler,
            "type": "mlp",
            "feature_names": fnames,
        })
    else:
        raise ValueError(f"Unknown model type: {model_type}")

    return next_cache


def get_game_data_cache_key(session: Session) -> tuple[int | None, datetime | None]:
    max_id, max_played_at = session.query(
        func.max(Game.id),
        func.max(Game.played_at),
    ).one()
    return max_id, max_played_at


def get_prediction_dataset(session: Session) -> object:
    cache_key = get_game_data_cache_key(session)
    if (
        _cached_game_data.get("cache_key") == cache_key
        and _cached_game_data.get("data") is not None
    ):
        return _cached_game_data["data"]

    df = load_game_data(session)
    _cached_game_data.clear()
    _cached_game_data.update({
        "cache_key": cache_key,
        "data": df,
        "row_count": len(df),
    })
    return df


def get_prediction_runtime_status(session: Session) -> dict[str, object]:
    model_info = _load_active_model(session)
    cache_key = get_game_data_cache_key(session)
    row_count = None
    if _cached_game_data.get("cache_key") == cache_key:
        row_count = _cached_game_data.get("row_count")
    return {
        "active_model_id": model_info.get("run_id") if model_info else None,
        "active_model_version": model_info.get("model_version") if model_info else None,
        "active_model_path": model_info.get("artifact_path") if model_info else None,
        "game_data_row_count": row_count,
    }


def _load_active_model(session: Session) -> dict[str, object] | None:
    manifest = read_model_manifest()
    if manifest:
        run_id = manifest.get("source_run_id")
        if isinstance(run_id, int):
            manifest_run = session.query(MLModelRun).filter(MLModelRun.id == run_id).first()
            if manifest_run is not None:
                cached_run_id = _cached_model.get("run_id")
                cached_artifact_path = _cached_model.get("artifact_path")
                if (
                    _cached_model.get("loaded")
                    and cached_run_id == manifest_run.id
                    and cached_artifact_path == manifest_run.artifact_path
                ):
                    return _cached_model

                artifact_path = Path(manifest_run.artifact_path)
                if _artifact_is_available(artifact_path, manifest_run.model_type):
                    try:
                        next_cache = _load_model_run(manifest_run)
                        _cached_model.clear()
                        _cached_model.update(next_cache)
                        return _cached_model
                    except Exception as e:
                        logger.warning(
                            "Failed to load manifest-selected model run_id=%s artifact_path=%s: %s",
                            manifest_run.id,
                            artifact_path,
                            str(e).split("\n")[0].strip() if str(e) else type(e).__name__,
                        )

    runs = (
        session.query(MLModelRun)
        .filter(MLModelRun.is_active == True)
        .order_by(MLModelRun.created_at.desc())
        .all()
    )
    if not runs:
        _cached_model.clear()
        return None

    for run in runs:
        cached_run_id = _cached_model.get("run_id")
        cached_artifact_path = _cached_model.get("artifact_path")
        if (
            _cached_model.get("loaded")
            and cached_run_id == run.id
            and cached_artifact_path == run.artifact_path
        ):
            return _cached_model

        artifact_path = Path(run.artifact_path)
        if not _artifact_is_available(artifact_path, run.model_type):
            logger.warning(
                "Skipping active model run_id=%s type=%s artifact_path=%s because required artifact files are missing.",
                run.id,
                run.model_type,
                artifact_path,
            )
            continue

        try:
            next_cache = _load_model_run(run)
        except Exception as e:
            err_msg = str(e).split("\n")[0].strip() if str(e) else type(e).__name__
            logger.warning(
                "Model not available (artifact_path=%s): %s. Copy model artifacts to backend/models/ or run training.",
                artifact_path,
                err_msg,
            )
            continue

        if runs[0].id != run.id:
            logger.warning(
                "Falling back to loadable active model run_id=%s version=%s after skipping newer active runs.",
                run.id,
                run.model_version,
            )

        _cached_model.clear()
        _cached_model.update(next_cache)
        return _cached_model

    _cached_model.clear()
    return None


def predict_match(
    session: Session,
    team_a_id: int,
    team_b_id: int,
    *,
    series_format: str = "BO1",
    score_a: int = 0,
    score_b: int = 0,
    patch: str | None = None,
    league_slug: str | None = None,
    playoffs: bool = False,
    model_info: dict[str, object] | None = None,
    game_data_df: object | None = None,
    persist_prediction_log: bool = True,
) -> dict[str, object] | None:
    model_info = model_info or _load_active_model(session)
    if not model_info:
        return None

    feature_names = model_info["feature_names"]
    df = game_data_df if game_data_df is not None else get_prediction_dataset(session)
    if df.empty:
        return None

    now = datetime.now(timezone.utc)

    blue_stats = _rolling_team_stats(df, team_a_id, now, 10)
    red_stats = _rolling_team_stats(df, team_b_id, now, 10)
    h2h = _h2h_stats(df, team_a_id, team_b_id, now)

    features: dict[str, float] = {}
    for key, val in blue_stats.items():
        features[f"blue_{key}"] = val
    for key, val in red_stats.items():
        features[f"red_{key}"] = val
    for key in blue_stats:
        if key in red_stats and key != "games_played":
            features[f"diff_{key}"] = blue_stats[key] - red_stats[key]
    features.update(h2h)
    features["league_tier_weight"] = LEAGUE_TIER_WEIGHTS.get((league_slug or "").lower(), 0.5)
    features["is_playoffs"] = 1.0 if playoffs else 0.0
    features["patch_float"] = _patch_to_float(patch)
    features["year"] = float(now.year)
    features["era_transition"] = 0.0

    X = np.zeros((1, len(feature_names)), dtype=np.float32)
    for j, key in enumerate(feature_names):
        X[0, j] = features.get(key, 0.0)

    model_type = model_info["type"]
    if model_type == "xgboost":
        from ml.model_registry import predict_xgboost
        prob = float(predict_xgboost(model_info["model"], X, feature_names)[0])
    elif model_type == "logistic_regression":
        from ml.model_registry import predict_logistic
        prob = float(predict_logistic(model_info["model"], model_info["scaler"], X)[0])
    elif model_type == "mlp":
        from ml.model_registry import predict_mlp
        prob = float(predict_mlp(model_info["model"], model_info["scaler"], X)[0])
    else:
        return None

    prob = max(0.25, min(0.75, prob))

    number_of_games = {"BO1": 1, "BO3": 3, "BO5": 5}.get(series_format.upper(), 1)
    games_to_win = 1 if number_of_games <= 1 else (2 if number_of_games == 3 else 3)
    live_adjustment = _compute_mid_series_adjustments(
        base_game_win_prob=prob,
        score_a=score_a,
        score_b=score_b,
        games_to_win=games_to_win,
        blue_stats=blue_stats,
        red_stats=red_stats,
        h2h=h2h,
        league_slug=league_slug,
    )
    adjusted_game_prob_a = float(live_adjustment["adjusted_game_win_prob_a"])
    series_prob_a, series_prob_b = compute_live_series_odds(adjusted_game_prob_a, score_a, score_b, number_of_games)

    confidence_flag = None
    if max(series_prob_a, series_prob_b) < 0.55:
        confidence_flag = "coin_flip"

    top_features = []
    if model_type == "xgboost":
        try:
            importance = model_info["model"].get_score(importance_type="gain")
            sorted_feats = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:5]
            top_features = [f"{name} ({val:.0f})" for name, val in sorted_feats]
        except Exception:
            pass
    elif model_type == "logistic_regression":
        try:
            coefs = model_info["model"].coef_[0]
            sorted_idx = np.argsort(np.abs(coefs))[::-1][:5]
            top_features = [f"{feature_names[i]} ({coefs[i]:.3f})" for i in sorted_idx]
        except Exception:
            pass

    result = {
        "game_win_prob_a": adjusted_game_prob_a,
        "base_game_win_prob_a": prob,
        "series_format": series_format.upper(),
        "series_score_a": score_a,
        "series_score_b": score_b,
        "series_win_prob_a": series_prob_a,
        "series_win_prob_b": series_prob_b,
        "decimal_odds_a": prob_to_decimal_odds(series_prob_a),
        "decimal_odds_b": prob_to_decimal_odds(series_prob_b),
        "confidence_flag": confidence_flag,
        "confidence": float(live_adjustment["confidence"]),
        "mid_series_delta": float(live_adjustment["mid_series_delta"]),
        "rebet_allowed": bool(live_adjustment["rebet_allowed"]),
        "key_factors": top_features,
        "model_type": model_type,
        "model_run_id": model_info.get("run_id"),
    }

    if persist_prediction_log:
        try:
            log_entry = PredictionLog(
                model_run_id=model_info.get("run_id"),
                team_a_id=team_a_id,
                team_b_id=team_b_id,
                game_win_prob_a=prob,
                series_format=series_format.upper(),
                series_score_a=score_a,
                series_score_b=score_b,
                series_win_prob_a=series_prob_a,
                confidence_flag=confidence_flag,
                key_factors_json=json.dumps(top_features),
                source="api",
            )
            session.add(log_entry)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.warning("Failed to log prediction: %s", e)

    return result


def predict_for_pandascore_match(
    session: Session,
    team_a_id: int,
    team_b_id: int,
    number_of_games: int = 1,
    score_a: int = 0,
    score_b: int = 0,
    league_slug: str | None = None,
) -> tuple[float | None, float | None, float | None, float | None, int | None]:
    fmt = number_of_games_to_format(number_of_games)
    model_info = _load_active_model(session)
    if not model_info:
        return (None, None, None, None, None)
    game_data_df = get_prediction_dataset(session)
    if game_data_df.empty:
        return (None, None, None, None, None)

    result = predict_match(
        session, team_a_id, team_b_id,
        series_format=fmt,
        score_a=score_a, score_b=score_b,
        league_slug=league_slug,
        model_info=model_info,
        game_data_df=game_data_df,
    )
    if not result:
        return (None, None, None, None, None)

    model_odds_a = result["decimal_odds_a"]
    model_odds_b = result["decimal_odds_b"]

    pre_match = predict_match(
        session, team_a_id, team_b_id,
        series_format=fmt,
        score_a=0, score_b=0,
        league_slug=league_slug,
        model_info=model_info,
        game_data_df=game_data_df,
    )
    pre_odds_a = pre_match["decimal_odds_a"] if pre_match else None
    pre_odds_b = pre_match["decimal_odds_b"] if pre_match else None

    return (model_odds_a, model_odds_b, pre_odds_a, pre_odds_b, model_info.get("run_id"))


def predict_live_rebet_context(
    session: Session,
    team_a_id: int,
    team_b_id: int,
    *,
    number_of_games: int = 1,
    score_a: int = 0,
    score_b: int = 0,
    league_slug: str | None = None,
    bookie_odds_a: float | None = None,
    bookie_odds_b: float | None = None,
) -> dict[str, object] | None:
    fmt = number_of_games_to_format(number_of_games)
    model_info = _load_active_model(session)
    if not model_info:
        return None
    game_data_df = get_prediction_dataset(session)
    if game_data_df.empty:
        return None
    result = predict_match(
        session,
        team_a_id,
        team_b_id,
        series_format=fmt,
        score_a=score_a,
        score_b=score_b,
        league_slug=league_slug,
        model_info=model_info,
        game_data_df=game_data_df,
        persist_prediction_log=False,
    )
    if not result:
        return None

    recommendation = {
        "rebet_allowed": bool(result.get("rebet_allowed")),
        "confidence": float(result.get("confidence") or 0.0),
        "base_game_win_prob_a": float(result.get("base_game_win_prob_a") or 0.0),
        "adjusted_game_win_prob_a": float(result.get("game_win_prob_a") or 0.0),
        "series_win_prob_a": float(result.get("series_win_prob_a") or 0.0),
        "series_win_prob_b": float(result.get("series_win_prob_b") or 0.0),
        "mid_series_delta": float(result.get("mid_series_delta") or 0.0),
        "edge_vs_market_team1": None,
        "edge_vs_market_team2": None,
        "incremental_ev_team1": None,
        "incremental_ev_team2": None,
    }
    if bookie_odds_a and bookie_odds_b and bookie_odds_a > 1 and bookie_odds_b > 1:
        market_prob_a = 1.0 / bookie_odds_a
        market_prob_b = 1.0 / bookie_odds_b
        total = market_prob_a + market_prob_b
        if total > 0:
            market_prob_a /= total
            market_prob_b /= total
            series_prob_a = float(result.get("series_win_prob_a") or 0.0)
            series_prob_b = float(result.get("series_win_prob_b") or 0.0)
            recommendation["edge_vs_market_team1"] = round(series_prob_a - market_prob_a, 5)
            recommendation["edge_vs_market_team2"] = round(series_prob_b - market_prob_b, 5)
            recommendation["incremental_ev_team1"] = round((series_prob_a * (bookie_odds_a - 1.0)) - (1.0 - series_prob_a), 5)
            recommendation["incremental_ev_team2"] = round((series_prob_b * (bookie_odds_b - 1.0)) - (1.0 - series_prob_b), 5)
            recommendation["rebet_allowed"] = bool(recommendation["rebet_allowed"]) and (
                recommendation["confidence"] >= 0.58
                and (
                    recommendation["edge_vs_market_team1"] is not None
                    and max(recommendation["edge_vs_market_team1"], recommendation["edge_vs_market_team2"]) >= 0.03
                )
            )
    return recommendation
