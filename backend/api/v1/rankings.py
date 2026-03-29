from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.dependencies import get_db
from database import SessionLocal, init_db
from models_ml import PowerRankingsSnapshot
from services.homepage_snapshots import apply_snapshot_headers, get_active_snapshot

router = APIRouter(prefix="/rankings", tags=["rankings"])

MAJOR_REGION_SLUGS: tuple[str, ...] = (
    "lck",
    "lpl",
    "lec",
    "lcs",
    "cblol",
    "lcp",
)

LEAGUE_BASE_WEIGHTS: dict[str, float] = {
    "lck": 1.0,
    "lpl": 1.0,
    "lec": 0.90,
    "lcs": 0.85,
    "cblol": 0.75,
    "lcp": 0.70,
}


@dataclass
class _RankingRowRaw:
    team_id: int
    team: str
    abbreviation: str | None
    league: str
    league_slug: str
    games_played: int
    wins: int
    losses: int
    avg_game_duration_min: float
    avg_gold_diff_15: float
    first_blood_pct: float
    first_dragon_pct: float
    first_tower_pct: float
    kda: float
    opp_avg_win_rate: float
    playoff_games: int
    playoff_wins: int
    playoff_losses: int
    split_titles: int


class PowerRankingRow(BaseModel):
    rank: int
    team: str
    league_slug: str
    wins: int
    losses: int
    win_rate: float
    avg_game_duration_min: float
    avg_gold_diff_15: float
    first_blood_pct: float
    first_dragon_pct: float
    first_tower_pct: float
    games_played: int


def _region_weight(league_slug: str) -> float:
    base = float(LEAGUE_BASE_WEIGHTS.get(league_slug, 0.75))
    if league_slug in {"lck", "lpl"}:
        return base * 1.18
    if league_slug in {"lec", "lcs"}:
        return base * 1.00
    return base * 0.95


def _composite_score(row: _RankingRowRaw, win_rate: float) -> tuple[float, float, float]:
    region_weight = _region_weight(row.league_slug)
    sos = row.opp_avg_win_rate
    strength_of_schedule = max(0.0, min(1.0, sos))
    playoff_win_rate = (
        float(row.playoff_wins / row.playoff_games) if row.playoff_games > 0 else 0.0
    )

    playoff_bonus = 0.0
    if row.playoff_games > 0:
        playoff_bonus += (playoff_win_rate - 0.5) * 100.0 * 0.30
        playoff_bonus += float(row.split_titles) * 8.0

        if row.playoff_games >= 3 and playoff_win_rate <= 0.40:
            playoff_bonus -= 6.0
        if row.playoff_games <= 5 and row.playoff_losses >= 3:
            playoff_bonus -= 4.0

    base_score = (
        win_rate * 100.0 * 0.45
        + row.avg_gold_diff_15 * 0.01 * 0.18
        + row.first_blood_pct * 100.0 * 0.06
        + row.first_dragon_pct * 100.0 * 0.10
        + row.first_tower_pct * 100.0 * 0.08
        + min(row.kda, 5.0) * 10.0 * 0.05
        + (strength_of_schedule - 0.50) * 100.0 * 0.08
        + playoff_bonus
    )
    return base_score * region_weight, strength_of_schedule, region_weight


def compute_power_rankings(league: str | None = None) -> list[PowerRankingRow]:
    init_db()
    session = SessionLocal()
    try:
        major_slugs_sql = ", ".join(f"'{slug}'" for slug in MAJOR_REGION_SLUGS)
        params: dict[str, object] = {}
        where_parts: list[str] = [
            "g.played_at >= NOW() - INTERVAL '90 days'",
            f"l.slug IN ({major_slugs_sql})",
        ]
        if league:
            where_parts.append("l.slug = :league_slug")
            params["league_slug"] = league.strip().lower()
        query = text(
            f"""
            WITH filtered_games AS (
                SELECT
                    g.id AS game_id,
                    g.gamelength_sec AS gamelength_sec,
                    g.playoffs AS playoffs,
                    g.split AS split,
                    g.year AS year,
                    l.slug AS league_slug
                FROM game g
                JOIN league l ON l.id = g.league_id
                WHERE {" AND ".join(where_parts)}
            ),
            team_base AS (
                SELECT
                    t.id AS team_id,
                    t.canonical_name AS team,
                    t.abbreviation AS abbreviation,
                    l.name AS league,
                    l.slug AS league_slug,
                    COUNT(*)::int AS games_played,
                    SUM(CASE WHEN gt.win THEN 1 ELSE 0 END)::int AS wins,
                    SUM(CASE WHEN gt.win THEN 0 ELSE 1 END)::int AS losses,
                    COALESCE(AVG(fg.gamelength_sec) / 60.0, 0)::float AS avg_game_duration_min,
                    COALESCE(AVG(gt.golddiffat15), 0)::float AS avg_gold_diff_15,
                    COALESCE(AVG(CASE WHEN gt.firstblood THEN 1 ELSE 0 END), 0)::float AS first_blood_pct,
                    COALESCE(AVG(CASE WHEN gt.firstdragon THEN 1 ELSE 0 END), 0)::float AS first_dragon_pct,
                    COALESCE(AVG(CASE WHEN gt.firsttower THEN 1 ELSE 0 END), 0)::float AS first_tower_pct,
                    COALESCE(
                        SUM(COALESCE(gt.teamkills, 0)) / NULLIF(SUM(COALESCE(gt.teamdeaths, 0)), 0),
                        SUM(COALESCE(gt.teamkills, 0))
                    )::float AS kda,
                    SUM(CASE WHEN fg.playoffs THEN 1 ELSE 0 END)::int AS playoff_games,
                    SUM(CASE WHEN fg.playoffs AND gt.win THEN 1 ELSE 0 END)::int AS playoff_wins,
                    SUM(CASE WHEN fg.playoffs AND NOT gt.win THEN 1 ELSE 0 END)::int AS playoff_losses
                FROM game_team gt
                JOIN filtered_games fg ON fg.game_id = gt.game_id
                JOIN team t ON t.id = gt.team_id
                JOIN game g ON g.id = gt.game_id
                JOIN league l ON l.id = g.league_id
                GROUP BY t.id, t.canonical_name, t.abbreviation, l.name, l.slug
                HAVING COUNT(*) >= 5
            ),
            team_win_rate AS (
                SELECT
                    gt.team_id AS team_id,
                    AVG(CASE WHEN gt.win THEN 1.0 ELSE 0.0 END)::float AS team_win_rate
                FROM game_team gt
                JOIN filtered_games fg ON fg.game_id = gt.game_id
                GROUP BY gt.team_id
            ),
            playoff_records AS (
                SELECT
                    gt.team_id AS team_id,
                    l.slug AS league_slug,
                    COALESCE(fg.year, EXTRACT(YEAR FROM NOW())::int) AS season_year,
                    COALESCE(fg.split, 'unknown') AS split,
                    SUM(CASE WHEN gt.win THEN 1 ELSE 0 END)::int AS wins,
                    COUNT(*)::int AS games,
                    AVG(CASE WHEN gt.win THEN 1.0 ELSE 0.0 END)::float AS win_rate
                FROM game_team gt
                JOIN filtered_games fg ON fg.game_id = gt.game_id
                JOIN game g ON g.id = gt.game_id
                JOIN league l ON l.id = g.league_id
                WHERE fg.playoffs
                GROUP BY
                    gt.team_id,
                    l.slug,
                    COALESCE(fg.year, EXTRACT(YEAR FROM NOW())::int),
                    COALESCE(fg.split, 'unknown')
            ),
            split_champs AS (
                SELECT
                    pr.team_id AS team_id,
                    COUNT(*)::int AS split_titles
                FROM (
                    SELECT
                        league_slug,
                        season_year,
                        split,
                        team_id,
                        wins,
                        games,
                        win_rate,
                        ROW_NUMBER() OVER (
                            PARTITION BY league_slug, season_year, split
                            ORDER BY wins DESC, win_rate DESC, games DESC
                        ) AS rk
                    FROM playoff_records
                    WHERE games >= 3
                ) pr
                WHERE pr.rk = 1
                GROUP BY pr.team_id
            ),
            team_opponents AS (
                SELECT
                    gt.team_id AS team_id,
                    opp.team_id AS opponent_team_id
                FROM game_team gt
                JOIN filtered_games fg ON fg.game_id = gt.game_id
                JOIN game_team opp ON opp.game_id = gt.game_id
                WHERE opp.team_id <> gt.team_id
            )
            SELECT
                tb.team_id,
                tb.team,
                tb.abbreviation,
                tb.league,
                tb.league_slug,
                tb.games_played,
                tb.wins,
                tb.losses,
                tb.avg_game_duration_min,
                tb.avg_gold_diff_15,
                tb.first_blood_pct,
                tb.first_dragon_pct,
                tb.first_tower_pct,
                tb.kda,
                COALESCE(AVG(twr.team_win_rate), 0.5)::float AS opp_avg_win_rate,
                tb.playoff_games,
                tb.playoff_wins,
                tb.playoff_losses,
                COALESCE(sc.split_titles, 0)::int AS split_titles
            FROM team_base tb
            LEFT JOIN team_opponents to2 ON to2.team_id = tb.team_id
            LEFT JOIN team_win_rate twr ON twr.team_id = to2.opponent_team_id
            LEFT JOIN split_champs sc ON sc.team_id = tb.team_id
            GROUP BY
                tb.team_id,
                tb.team,
                tb.abbreviation,
                tb.league,
                tb.league_slug,
                tb.games_played,
                tb.wins,
                tb.losses,
                tb.avg_game_duration_min,
                tb.avg_gold_diff_15,
                tb.first_blood_pct,
                tb.first_dragon_pct,
                tb.first_tower_pct,
                tb.kda,
                tb.playoff_games,
                tb.playoff_wins,
                tb.playoff_losses,
                sc.split_titles
            ORDER BY tb.games_played DESC, tb.wins DESC
            """
        )
        rows = session.execute(query, params).fetchall()
        base_rows = [
            _RankingRowRaw(
                team_id=int(row.team_id),
                team=str(row.team),
                abbreviation=str(row.abbreviation) if row.abbreviation is not None else None,
                league=str(row.league),
                league_slug=str(row.league_slug),
                games_played=int(row.games_played),
                wins=int(row.wins),
                losses=int(row.losses),
                avg_game_duration_min=float(row.avg_game_duration_min),
                avg_gold_diff_15=float(row.avg_gold_diff_15),
                first_blood_pct=float(row.first_blood_pct),
                first_dragon_pct=float(row.first_dragon_pct),
                first_tower_pct=float(row.first_tower_pct),
                kda=float(row.kda),
                opp_avg_win_rate=float(row.opp_avg_win_rate),
                playoff_games=int(row.playoff_games),
                playoff_wins=int(row.playoff_wins),
                playoff_losses=int(row.playoff_losses),
                split_titles=int(row.split_titles),
            )
            for row in rows
        ]

        ranked = []
        for row in base_rows:
            win_rate = float(row.wins / row.games_played) if row.games_played > 0 else 0.0
            score, strength_of_schedule, region_weight = _composite_score(row, win_rate)
            ranked.append((row, win_rate, score, strength_of_schedule, region_weight))
        ranked.sort(key=lambda entry: (entry[2], entry[1], entry[0].wins), reverse=True)

        return [
            PowerRankingRow(
                rank=index + 1,
                team=row.team,
                league_slug=row.league_slug,
                wins=row.wins,
                losses=row.losses,
                win_rate=round(win_rate, 4),
                avg_game_duration_min=round(row.avg_game_duration_min, 2),
                avg_gold_diff_15=round(row.avg_gold_diff_15, 2),
                first_blood_pct=round(row.first_blood_pct, 4),
                first_dragon_pct=round(row.first_dragon_pct, 4),
                first_tower_pct=round(row.first_tower_pct, 4),
                games_played=row.games_played,
            )
            for index, (row, win_rate, score, strength_of_schedule, region_weight) in enumerate(ranked)
        ]
    finally:
        session.close()


@router.get("/power", response_model=list[PowerRankingRow])
def get_power_rankings(
    response: Response,
    league: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> list[PowerRankingRow]:
    snapshot = get_active_snapshot(session, PowerRankingsSnapshot)
    apply_snapshot_headers(response, snapshot, key="rankings")
    items = list((snapshot.payload_json if snapshot else {}).get("items", []))
    if len(items) == 0:
        items = [row.model_dump() for row in compute_power_rankings(None)]
    items = [
        item
        for item in items
        if str(item.get("league_slug") or "").strip().lower() in MAJOR_REGION_SLUGS
    ]
    if league:
        items = [item for item in items if str(item.get("league_slug") or "") == league.strip().lower()]
    return [PowerRankingRow.model_validate(item) for item in items]
