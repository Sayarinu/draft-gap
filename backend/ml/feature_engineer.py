from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import SessionLocal
from models_ml import Game, GameTeam, GamePlayer, MatchFeature

logger = logging.getLogger(__name__)

FEATURE_VERSION = "v1"

LAMBDA_DATE = 0.005
LAMBDA_PATCH = 0.15

WINDOW_SHORT = 10
WINDOW_LONG = 20

ERA_BOUNDARIES: dict[str, str] = {
    "2022-01-01": "season_12_start",
    "2023-01-11": "season_13_start",
    "2024-01-10": "season_14_start",
    "2024-09-25": "worlds_2024_patch",
    "2025-01-08": "season_15_start",
    "2026-01-07": "season_16_start",
}

LEAGUE_TIER_WEIGHTS: dict[str, float] = {
    "lck": 1.0, "lpl": 1.0,
    "lec": 0.90, "lcs": 0.85,
    "ltan": 0.80, "ltas": 0.75,
    "pcs": 0.75, "vcs": 0.70, "ljl": 0.65,
    "cblol": 0.75, "lla": 0.70,
    "lcp": 0.70,
    "worlds": 1.0, "msi": 1.0, "ewc": 0.95,
}


def _patch_to_float(patch: str | None) -> float:
    if not patch:
        return 0.0
    parts = str(patch).strip().split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return major + minor / 100.0
    except (ValueError, IndexError):
        return 0.0


def _temporal_weight(game_date: datetime, ref_date: datetime, game_patch: str | None, ref_patch: str | None) -> float:
    days_ago = max(0, (ref_date - game_date).days)
    date_weight = math.exp(-LAMBDA_DATE * days_ago)

    patch_dist = abs(_patch_to_float(ref_patch) - _patch_to_float(game_patch))
    patch_weight = math.exp(-LAMBDA_PATCH * patch_dist * 10)

    return date_weight * patch_weight


def load_game_data(session: Session) -> pd.DataFrame:
    query = text("""
        SELECT
            g.id as game_id, g.gameid_oe, g.played_at, g.patch, g.split,
            g.playoffs, g.gamelength_sec, g.blue_team_id, g.red_team_id,
            g.blue_win, g.year, g.league_id,
            l.slug as league_slug, l.tier_weight as league_tier_weight,
            bt.goldat10 as blue_goldat10, bt.xpat10 as blue_xpat10,
            bt.csat10 as blue_csat10, bt.golddiffat10 as blue_golddiffat10,
            bt.xpdiffat10 as blue_xpdiffat10, bt.csdiffat10 as blue_csdiffat10,
            bt.golddiffat15 as blue_golddiffat15,
            bt.firstdragon as blue_firstdragon, bt.dragons as blue_dragons,
            bt.elders as blue_elders, bt.firstherald as blue_firstherald,
            bt.heralds as blue_heralds, bt.void_grubs as blue_void_grubs,
            bt.firstbaron as blue_firstbaron, bt.barons as blue_barons,
            bt.atakhans as blue_atakhans,
            bt.firsttower as blue_firsttower, bt.towers as blue_towers,
            bt.turretplates as blue_turretplates, bt.inhibitors as blue_inhibitors,
            bt.teamkills as blue_teamkills, bt.teamdeaths as blue_teamdeaths,
            bt.firstblood as blue_firstblood,
            bt.totalgold as blue_totalgold, bt.earnedgold as blue_earnedgold,
            bt.damagetochampions as blue_damagetochampions,
            bt.wardsplaced as blue_wardsplaced, bt.wardskilled as blue_wardskilled,
            bt.controlwardsbought as blue_controlwardsbought,
            bt.visionscore as blue_visionscore,
            bt.pick1 as blue_pick1, bt.pick2 as blue_pick2,
            bt.pick3 as blue_pick3, bt.pick4 as blue_pick4, bt.pick5 as blue_pick5,
            rt.goldat10 as red_goldat10, rt.xpat10 as red_xpat10,
            rt.csat10 as red_csat10, rt.golddiffat10 as red_golddiffat10,
            rt.xpdiffat10 as red_xpdiffat10, rt.csdiffat10 as red_csdiffat10,
            rt.golddiffat15 as red_golddiffat15,
            rt.firstdragon as red_firstdragon, rt.dragons as red_dragons,
            rt.elders as red_elders, rt.firstherald as red_firstherald,
            rt.heralds as red_heralds, rt.void_grubs as red_void_grubs,
            rt.firstbaron as red_firstbaron, rt.barons as red_barons,
            rt.atakhans as red_atakhans,
            rt.firsttower as red_firsttower, rt.towers as red_towers,
            rt.turretplates as red_turretplates, rt.inhibitors as red_inhibitors,
            rt.teamkills as red_teamkills, rt.teamdeaths as red_teamdeaths,
            rt.firstblood as red_firstblood,
            rt.totalgold as red_totalgold, rt.earnedgold as red_earnedgold,
            rt.damagetochampions as red_damagetochampions,
            rt.wardsplaced as red_wardsplaced, rt.wardskilled as red_wardskilled,
            rt.controlwardsbought as red_controlwardsbought,
            rt.visionscore as red_visionscore,
            rt.pick1 as red_pick1, rt.pick2 as red_pick2,
            rt.pick3 as red_pick3, rt.pick4 as red_pick4, rt.pick5 as red_pick5
        FROM game g
        JOIN league l ON g.league_id = l.id
        JOIN game_team bt ON bt.game_id = g.id AND bt.side = 'blue'
        JOIN game_team rt ON rt.game_id = g.id AND rt.side = 'red'
        ORDER BY g.played_at
    """)
    result = session.execute(query)
    cols = list(result.keys())
    rows = result.fetchall()
    return pd.DataFrame(rows, columns=cols)


def _rolling_team_stats(
    df: pd.DataFrame,
    team_id: int,
    before_date: datetime,
    window: int,
    side_col: str = "blue_team_id",
    prefix: str = "blue_",
) -> dict[str, float]:
    team_as_blue = df[(df["blue_team_id"] == team_id) & (df["played_at"] < before_date)]
    team_as_red = df[(df["red_team_id"] == team_id) & (df["played_at"] < before_date)]

    blue_games = team_as_blue.tail(window)
    red_games = team_as_red.tail(window)

    all_games_count = len(blue_games) + len(red_games)
    if all_games_count == 0:
        return {}

    blue_wins = blue_games["blue_win"].sum() if len(blue_games) > 0 else 0
    red_wins = (~red_games["blue_win"]).sum() if len(red_games) > 0 else 0
    total_wins = blue_wins + red_wins
    win_rate = total_wins / all_games_count

    blue_side_wr = blue_games["blue_win"].mean() if len(blue_games) > 0 else 0.5
    red_side_wr = (~red_games["blue_win"]).mean() if len(red_games) > 0 else 0.5

    stat_cols = [
        "golddiffat10", "xpdiffat10", "csdiffat10", "golddiffat15",
        "dragons", "elders", "heralds", "barons", "towers",
        "turretplates", "inhibitors", "teamkills", "teamdeaths",
        "totalgold", "damagetochampions", "wardsplaced",
        "wardskilled", "visionscore", "void_grubs",
    ]
    bool_cols = ["firstdragon", "firstherald", "firstbaron", "firsttower", "firstblood"]

    stats: dict[str, float] = {
        "win_rate": win_rate,
        "blue_side_wr": float(blue_side_wr),
        "red_side_wr": float(red_side_wr),
        "games_played": float(all_games_count),
    }

    early_game_cols = {"golddiffat10", "xpdiffat10", "csdiffat10", "golddiffat15"}

    for col in stat_cols:
        blue_vals = pd.to_numeric(blue_games[f"blue_{col}"], errors="coerce") if len(blue_games) > 0 else pd.Series(dtype=float)
        red_vals = pd.to_numeric(red_games[f"red_{col}"], errors="coerce") if len(red_games) > 0 else pd.Series(dtype=float)
        all_vals = pd.concat([blue_vals, red_vals]).dropna()
        if len(all_vals) == 0 and col in early_game_cols:
            wider_blue = df[(df["blue_team_id"] == team_id) & (df["played_at"] < before_date)].tail(window * 5)
            wider_red = df[(df["red_team_id"] == team_id) & (df["played_at"] < before_date)].tail(window * 5)
            wb = pd.to_numeric(wider_blue[f"blue_{col}"], errors="coerce") if len(wider_blue) > 0 else pd.Series(dtype=float)
            wr = pd.to_numeric(wider_red[f"red_{col}"], errors="coerce") if len(wider_red) > 0 else pd.Series(dtype=float)
            all_vals = pd.concat([wb, wr]).dropna()
        stats[f"avg_{col}"] = float(all_vals.mean()) if len(all_vals) > 0 else 0.0

    for col in bool_cols:
        blue_vals = blue_games[f"blue_{col}"].map(lambda v: 1.0 if v else 0.0) if len(blue_games) > 0 else pd.Series(dtype=float)
        red_vals = red_games[f"red_{col}"].map(lambda v: 1.0 if v else 0.0) if len(red_games) > 0 else pd.Series(dtype=float)
        all_vals = pd.concat([blue_vals, red_vals]).dropna()
        stats[f"rate_{col}"] = float(all_vals.mean()) if len(all_vals) > 0 else 0.5

    return stats


def _h2h_stats(
    df: pd.DataFrame,
    team_a_id: int,
    team_b_id: int,
    before_date: datetime,
    window: int = 10,
) -> dict[str, float]:
    a_blue = df[
        (df["blue_team_id"] == team_a_id) & (df["red_team_id"] == team_b_id) & (df["played_at"] < before_date)
    ].tail(window)
    a_red = df[
        (df["red_team_id"] == team_a_id) & (df["blue_team_id"] == team_b_id) & (df["played_at"] < before_date)
    ].tail(window)

    total = len(a_blue) + len(a_red)
    if total == 0:
        return {"h2h_win_rate": 0.5, "h2h_games": 0}

    wins = int(a_blue["blue_win"].sum()) + int((~a_red["blue_win"]).sum())
    return {
        "h2h_win_rate": wins / total,
        "h2h_games": float(total),
    }


def compute_features_for_game(
    df: pd.DataFrame,
    game_idx: int,
) -> dict[str, float] | None:
    row = df.iloc[game_idx]
    game_date = row["played_at"]
    if pd.isna(game_date):
        return None

    blue_id = row["blue_team_id"]
    red_id = row["red_team_id"]
    prior_df = df.iloc[:game_idx]

    blue_stats = _rolling_team_stats(prior_df, blue_id, game_date, WINDOW_SHORT)
    red_stats = _rolling_team_stats(prior_df, red_id, game_date, WINDOW_SHORT)

    if not blue_stats or not red_stats:
        return None

    features: dict[str, float] = {}

    for key, val in blue_stats.items():
        features[f"blue_{key}"] = val
    for key, val in red_stats.items():
        features[f"red_{key}"] = val

    for key in blue_stats:
        if key in red_stats and key not in ("games_played",):
            features[f"diff_{key}"] = blue_stats[key] - red_stats[key]

    h2h = _h2h_stats(prior_df, blue_id, red_id, game_date)
    features.update(h2h)

    league_slug = str(row.get("league_slug") or "").lower()
    features["league_tier_weight"] = LEAGUE_TIER_WEIGHTS.get(league_slug, 0.5)
    features["is_playoffs"] = 1.0 if row.get("playoffs") else 0.0
    features["patch_float"] = _patch_to_float(row.get("patch"))
    features["year"] = float(row.get("year") or 0)

    era_flag = 0
    game_date_naive = game_date.replace(tzinfo=None) if hasattr(game_date, 'tzinfo') and game_date.tzinfo else game_date
    for boundary_date, boundary_name in ERA_BOUNDARIES.items():
        bd = datetime.strptime(boundary_date, "%Y-%m-%d")
        try:
            if game_date_naive > bd and game_date_naive < bd + timedelta(days=30):
                era_flag = 1
                break
        except TypeError:
            continue
    features["era_transition"] = float(era_flag)

    return features


def compute_all_features(session: Session, batch_size: int = 1000) -> int:
    logger.info("Loading game data...")
    df = load_game_data(session)
    logger.info("Loaded %d games", len(df))

    if df.empty:
        return 0

    df = df.sort_values("played_at").reset_index(drop=True)

    existing_game_ids = {
        row[0] for row in
        session.execute(text("SELECT game_id FROM match_feature")).fetchall()
    }
    logger.info("Existing features: %d, total games: %d", len(existing_game_ids), len(df))

    created = 0
    min_history = 20

    for idx in range(min_history, len(df)):
        game_id = int(df.iloc[idx]["game_id"])
        if game_id in existing_game_ids:
            continue

        features = compute_features_for_game(df, idx)
        if features is None:
            continue

        row = df.iloc[idx]
        mf = MatchFeature(
            game_id=game_id,
            blue_team_id=int(row["blue_team_id"]),
            red_team_id=int(row["red_team_id"]),
            blue_win=bool(row["blue_win"]),
            played_at=row["played_at"],
            patch=str(row["patch"]) if row.get("patch") else None,
            league_slug=str(row.get("league_slug") or ""),
            playoffs=bool(row.get("playoffs")),
            year=int(row["year"]) if row.get("year") else None,
            features=features,
            feature_version=FEATURE_VERSION,
        )
        session.add(mf)
        created += 1

        if created % batch_size == 0:
            session.commit()
            logger.info("  Feature computation: %d/%d done", created + min_history, len(df))

    session.commit()
    logger.info("Feature computation complete: %d new features created", created)
    return created


def load_feature_matrix(session: Session) -> tuple[np.ndarray, np.ndarray, list[str], pd.DataFrame]:
    query = text("""
        SELECT id, game_id, blue_team_id, red_team_id, blue_win,
               played_at, patch, league_slug, playoffs, year, features
        FROM match_feature
        WHERE features IS NOT NULL
        ORDER BY played_at
    """)
    result = session.execute(query)
    cols = list(result.keys())
    rows = result.fetchall()
    df = pd.DataFrame(rows, columns=cols)

    if df.empty:
        return np.array([]), np.array([]), [], df

    all_feature_keys: set[str] = set()
    for feat_dict in df["features"]:
        if isinstance(feat_dict, dict):
            all_feature_keys.update(feat_dict.keys())

    feature_names = sorted(all_feature_keys)

    X = np.zeros((len(df), len(feature_names)), dtype=np.float32)
    y = np.array(df["blue_win"].astype(float).values, dtype=np.float32)

    for i, feat_dict in enumerate(df["features"]):
        if not isinstance(feat_dict, dict):
            continue
        for j, key in enumerate(feature_names):
            val = feat_dict.get(key)
            if val is not None:
                try:
                    X[i, j] = float(val)
                except (ValueError, TypeError):
                    pass

    nan_mask = np.isnan(X)
    if nan_mask.any():
        col_means = np.nanmean(X, axis=0)
        col_means = np.where(np.isnan(col_means), 0.0, col_means)
        for j in range(X.shape[1]):
            X[nan_mask[:, j], j] = col_means[j]

    metadata = df[["id", "game_id", "played_at", "patch", "league_slug", "playoffs", "year"]].copy()
    return X, y, feature_names, metadata
