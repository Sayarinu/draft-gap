from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from database import SessionLocal
from env_defaults import get_int


TEAM_PARTICIPANT_IDS = ("100", "200")

RECENCY_HALFLIFE_DAYS = get_int("RECENCY_HALFLIFE_DAYS")

FEATURE_COLUMNS = [
    "goldat10", "xpat10", "csat10", "golddiffat10", "xpdiffat10", "csdiffat10",
    "goldat15", "xpat15", "csat15", "golddiffat15", "xpdiffat15", "csdiffat15",
    "firstdragon", "dragons", "elders", "firstherald", "heralds",
    "firstbaron", "barons", "firsttower", "towers", "inhibitors",
    "teamkills", "teamdeaths", "totalgold", "damagetochampions",
    "wardsplaced", "visionscore", "gamelength",
]
EXTRA_FEATURE_NAMES = ["team_winrate_prior", "champ_avg_winrate"]
TARGET_COLUMN = "result"
PICK_COLS = ["pick1", "pick2", "pick3", "pick4", "pick5"]


def _safe_float(val: object) -> float | None:
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: object) -> int | None:
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _safe_bool(val: object) -> bool | None:
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    if s in ("1", "true", "yes"):
        return True
    if s in ("0", "false", "no"):
        return False
    return None


def load_team_rows_from_db(session: Session) -> pd.DataFrame:
    from sqlalchemy import text

    q = text(
        "SELECT gameid, participantid, result, side, date, teamname, "
        "pick1, pick2, pick3, pick4, pick5, "
        "goldat10, xpat10, csat10, golddiffat10, xpdiffat10, csdiffat10, "
        "goldat15, xpat15, csat15, golddiffat15, xpdiffat15, csdiffat15, "
        "firstdragon, dragons, elders, firstherald, heralds, "
        "firstbaron, barons, firsttower, towers, inhibitors, "
        "teamkills, teamdeaths, totalgold, damagetochampions, "
        "wardsplaced, visionscore, gamelength "
        "FROM game_stats "
        "WHERE participantid IN ('100', '200')"
    )
    result = session.execute(q)
    rows = result.fetchall()
    cols = list(result.keys())
    return pd.DataFrame(rows, columns=cols)


def _parse_date(val: object) -> datetime | None:
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    s = str(val).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _champion_winrates_from_team_rows(df: pd.DataFrame) -> dict[str, float]:
    champ_wins: dict[str, float] = {}
    champ_games: dict[str, float] = {}
    result_ser = df[TARGET_COLUMN].map(_safe_float)
    for pc in PICK_COLS:
        if pc not in df.columns:
            continue
        for champ, res in zip(df[pc].astype(str).str.strip(), result_ser):
            if not champ or champ == "nan" or pd.isna(res):
                continue
            champ_games[champ] = champ_games.get(champ, 0.0) + 1.0
            champ_wins[champ] = champ_wins.get(champ, 0.0) + (float(res) if res in (0.0, 1.0) else 0.0)
    out: dict[str, float] = {}
    for c, n in champ_games.items():
        if n > 0:
            out[c] = champ_wins.get(c, 0.0) / n
    return out


def _team_prior_winrate_per_row(df: pd.DataFrame) -> np.ndarray:
    if "date" not in df.columns or "teamname" not in df.columns:
        return np.full(len(df), 0.5, dtype=np.float32)
    d = df.copy()
    d["_parsed_date"] = d["date"].map(_parse_date)
    d = d.sort_values(["_parsed_date", "gameid"], na_position="last")
    prior_series = d.groupby("teamname", sort=False)["result"].transform(
        lambda s: s.astype(float).expanding().mean().shift(1)
    )
    prior_series = prior_series.reindex(df.index).fillna(0.5)
    return prior_series.astype(np.float32).values


def build_xy_from_dataframe(
    df: pd.DataFrame,
    halflife_days: int = RECENCY_HALFLIFE_DAYS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y_raw = df[TARGET_COLUMN].map(lambda v: _safe_float(v) if v is not None else None)
    valid_target = y_raw.notna() & (y_raw.isin([0.0, 1.0]))
    df = df.loc[valid_target].copy()
    y = np.asarray(df[TARGET_COLUMN].astype(float), dtype=np.float32)

    dates = df["date"].map(_parse_date) if "date" in df.columns else None
    if dates is not None and dates.notna().any():
        valid_dates = dates.dropna()
        if len(valid_dates):
            max_date = max(valid_dates)
            days_ago = np.array([(max_date - d).days for d in dates], dtype=np.float32)
            tau = halflife_days / 0.69314718056
            weights = np.exp(-np.maximum(days_ago, 0) / tau).astype(np.float32)
        else:
            weights = np.ones(len(df), dtype=np.float32)
    else:
        weights = np.ones(len(df), dtype=np.float32)

    available = [c for c in FEATURE_COLUMNS if c in df.columns]
    n_extra = len(EXTRA_FEATURE_NAMES)
    X = np.zeros((len(df), len(available) + n_extra), dtype=np.float32)

    for j, col in enumerate(available):
        raw = df[col]
        if col in ("firstdragon", "firstherald", "firstbaron", "firsttower"):
            vals = raw.map(_safe_bool).map(lambda b: 1.0 if b else 0.0)
        else:
            vals = raw.map(_safe_float)
        X[:, j] = vals.fillna(0.0).to_numpy(dtype=np.float32)

    team_prior = _team_prior_winrate_per_row(df)
    X[:, len(available)] = team_prior

    champ_wr = _champion_winrates_from_team_rows(df)
    champ_avg = np.zeros(len(df), dtype=np.float32)
    for idx in range(len(df)):
        row = df.iloc[idx]
        rates = []
        for pc in PICK_COLS:
            if pc not in df.columns:
                continue
            c = str(row.get(pc, "") or "").strip()
            if c and c != "nan":
                rates.append(champ_wr.get(c, 0.5))
        champ_avg[idx] = float(np.mean(rates)) if rates else 0.5
    X[:, len(available) + 1] = champ_avg

    return X, y, weights


def get_feature_names() -> list[str]:
    return list(FEATURE_COLUMNS) + list(EXTRA_FEATURE_NAMES)


def get_champ_winrates_from_db(session: Session) -> dict[str, float]:
    df = load_team_rows_from_db(session)
    if df.empty:
        return {}
    return _champion_winrates_from_team_rows(df)


def get_team_prior_winrate_from_db(
    session: Session,
    team_name: str,
    acronym: str | None = None,
) -> float:
    from sqlalchemy import text

    def lookup(name: str) -> float | None:
        if not (name and str(name).strip()):
            return None
        n = str(name).strip()
        q = text(
            "SELECT AVG(CAST(result AS FLOAT)) FROM game_stats "
            "WHERE participantid IN ('100', '200') AND LOWER(TRIM(teamname)) = LOWER(:team)"
        )
        row = session.execute(q, {"team": n}).fetchone()
        if row is None or row[0] is None:
            return None
        try:
            return max(0.0, min(1.0, float(row[0])))
        except (TypeError, ValueError):
            return None

    v = lookup(team_name)
    if v is not None:
        return v
    if acronym and str(acronym).strip():
        v = lookup(acronym)
        if v is not None:
            return v
    return 0.5


def team_has_history(
    session: Session,
    team_name: str,
    acronym: str | None = None,
) -> bool:
    from sqlalchemy import text

    def has_rows(name: str) -> bool:
        if not (name and str(name).strip()):
            return False
        n = str(name).strip()
        q = text(
            "SELECT 1 FROM game_stats "
            "WHERE participantid IN ('100', '200') AND LOWER(TRIM(teamname)) = LOWER(:team) LIMIT 1"
        )
        row = session.execute(q, {"team": n}).fetchone()
        return row is not None

    if has_rows(team_name):
        return True
    if acronym and str(acronym).strip():
        return has_rows(acronym)
    return False


def load_training_data() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    session = SessionLocal()
    try:
        df = load_team_rows_from_db(session)
        if df.empty:
            return (
                np.zeros((0, len(FEATURE_COLUMNS) + len(EXTRA_FEATURE_NAMES)), dtype=np.float32),
                np.array([], dtype=np.float32),
                np.array([], dtype=np.float32),
                list(FEATURE_COLUMNS) + list(EXTRA_FEATURE_NAMES),
            )
        X, y, weights = build_xy_from_dataframe(df)
        available = [c for c in FEATURE_COLUMNS if c in df.columns] + list(EXTRA_FEATURE_NAMES)
        return X, y, weights, available
    finally:
        session.close()
