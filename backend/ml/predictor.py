from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from database import SessionLocal
from ml.config import get_device, get_model_path
from ml.data_loader import (
    FEATURE_COLUMNS,
    get_champ_winrates_from_db,
    get_team_prior_winrate_from_db,
)
from ml.model import WinProbabilityMLP, load_model

BOOL_FEATURES = {"firstdragon", "firstherald", "firstbaron", "firsttower"}


def _stat_float(val: object) -> float:
    if val is None:
        return 0.0
    if isinstance(val, bool):
        return 1.0 if val else 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().lower()
    if s in ("1", "true", "yes"):
        return 1.0
    if s in ("0", "false", "no"):
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def build_feature_row(
    feature_names: list[str],
    *,
    team_name: str | None = None,
    team_acronym: str | None = None,
    picks: list[str] | None = None,
    stats: dict[str, object] | None = None,
    session: Session | None = None,
) -> np.ndarray:
    stats = stats or {}
    close_session = False
    if session is None:
        session = SessionLocal()
        close_session = True
    try:
        champ_wr = get_champ_winrates_from_db(session) if (picks or "champ_avg_winrate" in feature_names) else {}
        team_wr = (
            get_team_prior_winrate_from_db(session, team_name or "", acronym=team_acronym)
            if (team_name is not None and "team_winrate_prior" in feature_names)
            else 0.5
        )
    finally:
        if close_session:
            session.close()

    row = np.zeros(len(feature_names), dtype=np.float32)
    for i, name in enumerate(feature_names):
        if name == "team_winrate_prior":
            row[i] = team_wr
        elif name == "champ_avg_winrate":
            if picks:
                rates = [champ_wr.get(c.strip(), 0.5) for c in picks if c and str(c).strip()]
                row[i] = float(np.mean(rates)) if rates else 0.5
            else:
                row[i] = 0.5
        elif name in FEATURE_COLUMNS:
            if name in BOOL_FEATURES:
                row[i] = _stat_float(stats.get(name, 0.0))
            else:
                v = stats.get(name)
                if v is None or (isinstance(v, str) and not v.strip()):
                    row[i] = 0.0
                else:
                    try:
                        row[i] = float(v)
                    except (ValueError, TypeError):
                        row[i] = 0.0
    return row


def predict_win_probability(
    team_name: str | None = None,
    picks: list[str] | None = None,
    stats: dict[str, object] | None = None,
    model_path: str | None = None,
) -> float:
    path = model_path or get_model_path()
    device = torch.device(get_device())
    model, feature_names = load_model(path, device)
    row = build_feature_row(
        feature_names,
        team_name=team_name,
        picks=picks or [],
        stats=stats,
    )
    model.eval()
    with torch.no_grad():
        x = torch.from_numpy(row).float().unsqueeze(0).to(device)
        prob = model(x).squeeze().cpu().item()
    return float(max(0.0, min(1.0, prob)))


def get_model_decimal_odds_for_match(
    team1_name: str,
    team2_name: str,
    model: WinProbabilityMLP,
    feature_names: list[str],
    device: torch.device,
    session: Session | None = None,
    team1_acronym: str | None = None,
    team2_acronym: str | None = None,
) -> tuple[float | None, float | None]:
    try:
        row = build_feature_row(
            feature_names,
            team_name=team1_name.strip() or None,
            team_acronym=(team1_acronym or "").strip() or None,
            picks=[],
            stats=None,
            session=session,
        )
        model.eval()
        with torch.no_grad():
            x = torch.from_numpy(row).float().unsqueeze(0).to(device)
            p = model(x).squeeze().cpu().item()
        p = max(0.05, min(0.95, float(p)))
        odds1 = round(1.0 / p, 2)
        odds2 = round(1.0 / (1.0 - p), 2)
        return (odds1, odds2)
    except Exception as e:
        logger.warning(
            "get_model_decimal_odds_for_match failed: team1=%s team2=%s acr1=%s acr2=%s error=%s",
            team1_name,
            team2_name,
            team1_acronym,
            team2_acronym,
            e,
        )
        return (None, None)


def try_load_model() -> tuple[WinProbabilityMLP | None, list[str] | None]:
    path = Path(get_model_path()) / "win_probability_model.pt"
    if not path.exists():
        return (None, None)
    try:
        device = torch.device(get_device())
        model, feature_names = load_model(get_model_path(), device)
        return (model, feature_names)
    except Exception:
        return (None, None)
