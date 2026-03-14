from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
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
from models_ml import MLModelRun, PredictionLog

logger = logging.getLogger(__name__)

_cached_model: dict[str, object] = {}


def _load_active_model(session: Session) -> dict[str, object] | None:
    if _cached_model.get("loaded"):
        return _cached_model
    if _cached_model.get("load_failed"):
        return None

    run = (
        session.query(MLModelRun)
        .filter(MLModelRun.is_active == True)
        .order_by(MLModelRun.created_at.desc())
        .first()
    )
    if not run:
        return None

    artifact_path = Path(run.artifact_path)
    feature_names = json.loads(run.feature_names_json) if run.feature_names_json else []
    model_type = run.model_type

    try:
        if model_type == "xgboost":
            from ml.model_registry import load_xgboost
            model, fnames = load_xgboost(artifact_path)
            _cached_model.update({
                "loaded": True, "model": model, "type": "xgboost",
                "feature_names": fnames, "run_id": run.id,
            })
        elif model_type == "logistic_regression":
            from ml.model_registry import load_logistic
            model, scaler, fnames = load_logistic(artifact_path)
            _cached_model.update({
                "loaded": True, "model": model, "scaler": scaler,
                "type": "logistic_regression", "feature_names": fnames, "run_id": run.id,
            })
        elif model_type == "mlp":
            from ml.model_registry import load_mlp
            model, scaler, fnames = load_mlp(artifact_path)
            _cached_model.update({
                "loaded": True, "model": model, "scaler": scaler,
                "type": "mlp", "feature_names": fnames, "run_id": run.id,
            })
        else:
            logger.warning("Unknown model type: %s", model_type)
            _cached_model["load_failed"] = True
            return None
    except Exception as e:
        _cached_model["load_failed"] = True
        err_msg = str(e).split("\n")[0].strip() if str(e) else type(e).__name__
        logger.warning(
            "Model not available (artifact_path=%s): %s. Copy .xgb/.meta to server backend/models/ or run training.",
            artifact_path,
            err_msg,
        )
        return None

    return _cached_model


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
) -> dict[str, object] | None:
    model_info = _load_active_model(session)
    if not model_info:
        return None

    feature_names = model_info["feature_names"]
    df = load_game_data(session)
    if df.empty:
        return None

    from datetime import datetime, timezone
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
    series_prob_a, series_prob_b = compute_live_series_odds(prob, score_a, score_b, number_of_games)

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
        "game_win_prob_a": prob,
        "series_format": series_format.upper(),
        "series_score_a": score_a,
        "series_score_b": score_b,
        "series_win_prob_a": series_prob_a,
        "series_win_prob_b": series_prob_b,
        "decimal_odds_a": prob_to_decimal_odds(series_prob_a),
        "decimal_odds_b": prob_to_decimal_odds(series_prob_b),
        "confidence_flag": confidence_flag,
        "key_factors": top_features,
        "model_type": model_type,
        "model_run_id": model_info.get("run_id"),
    }

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
) -> tuple[float | None, float | None, float | None, float | None]:
    fmt = number_of_games_to_format(number_of_games)

    result = predict_match(
        session, team_a_id, team_b_id,
        series_format=fmt,
        score_a=score_a, score_b=score_b,
        league_slug=league_slug,
    )
    if not result:
        return (None, None, None, None)

    model_odds_a = result["decimal_odds_a"]
    model_odds_b = result["decimal_odds_b"]

    pre_match = predict_match(
        session, team_a_id, team_b_id,
        series_format=fmt,
        score_a=0, score_b=0,
        league_slug=league_slug,
    )
    pre_odds_a = pre_match["decimal_odds_a"] if pre_match else None
    pre_odds_b = pre_match["decimal_odds_b"] if pre_match else None

    return (model_odds_a, model_odds_b, pre_odds_a, pre_odds_b)
