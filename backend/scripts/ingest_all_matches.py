
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal, init_db
from entity_resolution.resolver import EntityResolver
from models_ml import Game, GamePlayer, GameTeam, Roster

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingest_matches")

TEAM_PARTICIPANT_IDS = {"100", "200"}
PLAYER_POSITIONS = {"top", "jng", "mid", "bot", "sup"}


def _safe_float(val: object) -> float | None:
    if val is None or (isinstance(val, str) and val.strip() in ("", "-")):
        return None
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: object) -> int | None:
    f = _safe_float(val)
    return int(f) if f is not None else None


def _safe_bool(val: object) -> bool | None:
    if val is None or (isinstance(val, str) and val.strip() in ("", "-")):
        return None
    if pd.isna(val):
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(int(val))
    s = str(val).strip().lower()
    if s in ("1", "true", "yes"):
        return True
    if s in ("0", "false", "no"):
        return False
    return None


def _parse_datetime(val: object) -> datetime | None:
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    return None


def _col(row: pd.Series, name: str) -> object:
    return row.get(name)


def ingest_csv_file(csv_path: Path, session: Session, resolver: EntityResolver) -> dict[str, int]:
    logger.info("Reading %s ...", csv_path.name)
    df = pd.read_csv(csv_path, low_memory=False)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    games_created = 0
    game_teams_created = 0
    game_players_created = 0
    champions_resolved = 0
    rosters_created = 0
    skipped = 0

    game_ids_in_file = df["gameid"].dropna().unique()
    logger.info("  %d unique games in %s", len(game_ids_in_file), csv_path.name)

    for gameid in game_ids_in_file:
        game_rows = df[df["gameid"] == gameid]
        if game_rows.empty:
            continue

        team_rows = game_rows[game_rows["participantid"].astype(str).isin(TEAM_PARTICIPANT_IDS)]
        player_rows = game_rows[~game_rows["participantid"].astype(str).isin(TEAM_PARTICIPANT_IDS)]

        if len(team_rows) < 2:
            skipped += 1
            continue

        blue_team_row = team_rows[team_rows["side"].astype(str).str.lower() == "blue"]
        red_team_row = team_rows[team_rows["side"].astype(str).str.lower() == "red"]

        if blue_team_row.empty or red_team_row.empty:
            skipped += 1
            continue

        blue_row = blue_team_row.iloc[0]
        red_row = red_team_row.iloc[0]

        existing = session.query(Game).filter(Game.gameid_oe == str(gameid)).first()
        if existing:
            continue

        league_raw = str(_col(blue_row, "league") or "unknown").strip()
        league = resolver.resolve_league(league_raw)
        if not league:
            skipped += 1
            continue

        blue_team_name = str(_col(blue_row, "teamname") or "").strip()
        red_team_name = str(_col(red_row, "teamname") or "").strip()
        if not blue_team_name or not red_team_name:
            skipped += 1
            continue

        blue_team_id_raw = str(_col(blue_row, "teamid") or "").strip() or None
        red_team_id_raw = str(_col(red_row, "teamid") or "").strip() or None

        blue_team = resolver.resolve_team(
            blue_team_name, "oracleselixir", region=league_raw,
        )
        red_team = resolver.resolve_team(
            red_team_name, "oracleselixir", region=league_raw,
        )
        if not blue_team or not red_team:
            skipped += 1
            continue

        if blue_team_id_raw and not blue_team.oe_team_id:
            blue_team.oe_team_id = blue_team_id_raw
        if red_team_id_raw and not red_team.oe_team_id:
            red_team.oe_team_id = red_team_id_raw

        played_at = _parse_datetime(_col(blue_row, "date"))
        if not played_at:
            skipped += 1
            continue

        blue_result = _safe_int(_col(blue_row, "result"))
        blue_win = blue_result == 1 if blue_result is not None else None
        if blue_win is None:
            skipped += 1
            continue

        patch = str(_col(blue_row, "patch") or "").strip() or None
        split = str(_col(blue_row, "split") or "").strip() or None
        playoffs = _safe_bool(_col(blue_row, "playoffs")) or False
        gamelength = _safe_int(_col(blue_row, "gamelength"))
        year = _safe_int(_col(blue_row, "year"))

        game = Game(
            gameid_oe=str(gameid),
            league_id=league.id,
            played_at=played_at,
            patch=patch,
            split=split,
            playoffs=playoffs,
            gamelength_sec=gamelength,
            blue_team_id=blue_team.id,
            red_team_id=red_team.id,
            blue_win=blue_win,
            year=year,
        )
        session.add(game)
        session.flush()
        games_created += 1

        for side_row, team, side in [(blue_row, blue_team, "blue"), (red_row, red_team, "red")]:
            win = blue_win if side == "blue" else not blue_win
            gt = GameTeam(
                game_id=game.id,
                team_id=team.id,
                side=side,
                win=win,
                goldat10=_safe_float(_col(side_row, "goldat10")),
                xpat10=_safe_float(_col(side_row, "xpat10")),
                csat10=_safe_float(_col(side_row, "csat10")),
                golddiffat10=_safe_float(_col(side_row, "golddiffat10")),
                xpdiffat10=_safe_float(_col(side_row, "xpdiffat10")),
                csdiffat10=_safe_float(_col(side_row, "csdiffat10")),
                goldat15=_safe_float(_col(side_row, "goldat15")),
                xpat15=_safe_float(_col(side_row, "xpat15")),
                csat15=_safe_float(_col(side_row, "csat15")),
                golddiffat15=_safe_float(_col(side_row, "golddiffat15")),
                xpdiffat15=_safe_float(_col(side_row, "xpdiffat15")),
                csdiffat15=_safe_float(_col(side_row, "csdiffat15")),
                firstdragon=_safe_bool(_col(side_row, "firstdragon")),
                dragons=_safe_int(_col(side_row, "dragons")),
                elders=_safe_int(_col(side_row, "elders")),
                firstherald=_safe_bool(_col(side_row, "firstherald")),
                heralds=_safe_int(_col(side_row, "heralds")),
                void_grubs=_safe_int(_col(side_row, "void_grubs")),
                opp_void_grubs=_safe_int(_col(side_row, "opp_void_grubs")),
                firstbaron=_safe_bool(_col(side_row, "firstbaron")),
                barons=_safe_int(_col(side_row, "barons")),
                atakhans=_safe_int(_col(side_row, "atakhans")),
                firsttower=_safe_bool(_col(side_row, "firsttower")),
                towers=_safe_int(_col(side_row, "towers")),
                turretplates=_safe_int(_col(side_row, "turretplates")),
                inhibitors=_safe_int(_col(side_row, "inhibitors")),
                teamkills=_safe_int(_col(side_row, "teamkills")),
                teamdeaths=_safe_int(_col(side_row, "teamdeaths")),
                firstblood=_safe_bool(_col(side_row, "firstblood")),
                totalgold=_safe_float(_col(side_row, "totalgold")),
                earnedgold=_safe_float(_col(side_row, "earnedgold")),
                damagetochampions=_safe_float(_col(side_row, "damagetochampions")),
                wardsplaced=_safe_float(_col(side_row, "wardsplaced")),
                wardskilled=_safe_float(_col(side_row, "wardskilled")),
                controlwardsbought=_safe_float(_col(side_row, "controlwardsbought")),
                visionscore=_safe_float(_col(side_row, "visionscore")),
                pick1=str(_col(side_row, "pick1") or "").strip() or None,
                pick2=str(_col(side_row, "pick2") or "").strip() or None,
                pick3=str(_col(side_row, "pick3") or "").strip() or None,
                pick4=str(_col(side_row, "pick4") or "").strip() or None,
                pick5=str(_col(side_row, "pick5") or "").strip() or None,
                ban1=str(_col(side_row, "ban1") or "").strip() or None,
                ban2=str(_col(side_row, "ban2") or "").strip() or None,
                ban3=str(_col(side_row, "ban3") or "").strip() or None,
                ban4=str(_col(side_row, "ban4") or "").strip() or None,
                ban5=str(_col(side_row, "ban5") or "").strip() or None,
            )
            if gt.goldat10 is None:
                side_player_rows = player_rows[
                    player_rows["position"].astype(str).str.lower().isin(PLAYER_POSITIONS)
                    & (player_rows["side"].astype(str).str.lower() == side)
                ]
                agg_cols = [
                    ("goldat10", _safe_float), ("xpat10", _safe_float),
                    ("csat10", _safe_float), ("golddiffat10", _safe_float),
                    ("xpdiffat10", _safe_float), ("csdiffat10", _safe_float),
                ]
                for col_name, converter in agg_cols:
                    vals = [converter(_col(r, col_name)) for _, r in side_player_rows.iterrows()]
                    vals = [v for v in vals if v is not None]
                    if vals:
                        setattr(gt, col_name, sum(vals))

            session.add(gt)
            game_teams_created += 1

            for champ_col in [gt.pick1, gt.pick2, gt.pick3, gt.pick4, gt.pick5,
                              gt.ban1, gt.ban2, gt.ban3, gt.ban4, gt.ban5]:
                if champ_col and champ_col.strip():
                    resolver.resolve_champion(champ_col, "oracleselixir")
                    champions_resolved += 1

        seen_game_players: set[tuple[int, int]] = set()
        side_players = player_rows[player_rows["position"].astype(str).str.lower().isin(PLAYER_POSITIONS)]
        for _, p_row in side_players.iterrows():
            player_name = str(_col(p_row, "playername") or "").strip()
            if not player_name:
                continue

            position = str(_col(p_row, "position") or "").strip().lower()
            player_side = str(_col(p_row, "side") or "").strip().lower()
            oe_pid = str(_col(p_row, "playerid") or "").strip() or None

            player = resolver.resolve_player(
                player_name, "oracleselixir", role=position, oe_player_id=oe_pid,
            )
            if not player:
                continue

            pair_key = (game.id, player.id)
            if pair_key in seen_game_players:
                continue
            seen_game_players.add(pair_key)

            p_team = blue_team if player_side == "blue" else red_team

            champ_raw = str(_col(p_row, "champion") or "").strip() or None
            if champ_raw:
                resolver.resolve_champion(champ_raw, "oracleselixir")
                champions_resolved += 1

            gp = GamePlayer(
                game_id=game.id,
                team_id=p_team.id,
                player_id=player.id,
                side=player_side,
                position=position,
                champion=champ_raw,
                kills=_safe_int(_col(p_row, "kills")),
                deaths=_safe_int(_col(p_row, "deaths")),
                assists=_safe_int(_col(p_row, "assists")),
                damagetochampions=_safe_float(_col(p_row, "damagetochampions")),
                dpm=_safe_float(_col(p_row, "dpm")),
                damageshare=_safe_float(_col(p_row, "damageshare")),
                earnedgold=_safe_float(_col(p_row, "earnedgold")),
                earnedgoldshare=_safe_float(_col(p_row, "earnedgoldshare")),
                total_cs=_safe_float(_col(p_row, "total_cs")),
                cspm=_safe_float(_col(p_row, "cspm")),
                visionscore=_safe_float(_col(p_row, "visionscore")),
                vspm=_safe_float(_col(p_row, "vspm")),
                wardsplaced=_safe_float(_col(p_row, "wardsplaced")),
                wpm=_safe_float(_col(p_row, "wpm")),
                wardskilled=_safe_float(_col(p_row, "wardskilled")),
                controlwardsbought=_safe_float(_col(p_row, "controlwardsbought")),
                goldat10=_safe_float(_col(p_row, "goldat10")),
                xpat10=_safe_float(_col(p_row, "xpat10")),
                csat10=_safe_float(_col(p_row, "csat10")),
                golddiffat10=_safe_float(_col(p_row, "golddiffat10")),
                xpdiffat10=_safe_float(_col(p_row, "xpdiffat10")),
                csdiffat10=_safe_float(_col(p_row, "csdiffat10")),
            )
            session.add(gp)
            game_players_created += 1

            game_date = played_at.date() if played_at else None
            if game_date:
                existing_roster = (
                    session.query(Roster)
                    .filter(Roster.player_id == player.id, Roster.team_id == p_team.id, Roster.role == position)
                    .first()
                )
                if existing_roster:
                    if existing_roster.joined_at is None or game_date < existing_roster.joined_at:
                        existing_roster.joined_at = game_date
                    if existing_roster.left_at is None or game_date > existing_roster.left_at:
                        existing_roster.left_at = game_date
                else:
                    session.add(Roster(
                        player_id=player.id,
                        team_id=p_team.id,
                        role=position,
                        joined_at=game_date,
                        left_at=game_date,
                        source="csv",
                    ))
                    rosters_created += 1

        if games_created % 500 == 0:
            session.commit()
            logger.info("  Committed %d games so far...", games_created)

    session.commit()
    return {
        "file": csv_path.name,
        "games": games_created,
        "game_teams": game_teams_created,
        "game_players": game_players_created,
        "champions_resolved": champions_resolved,
        "rosters_created": rosters_created,
        "skipped": skipped,
    }


def ingest_all(data_dir: str | Path) -> list[dict[str, int]]:
    data_path = Path(data_dir)
    csv_files = sorted(data_path.glob("*_LoL_esports_match_data_from_OraclesElixir.csv"))
    if not csv_files:
        logger.error("No CSV files found in %s", data_path)
        return []

    logger.info("Found %d CSV files to ingest", len(csv_files))

    init_db()
    session = SessionLocal()
    resolver = EntityResolver(session)
    results: list[dict[str, int]] = []

    try:
        for csv_file in csv_files:
            t0 = time.time()
            stats = ingest_csv_file(csv_file, session, resolver)
            elapsed = time.time() - t0
            logger.info(
                "  Done: %s — %d games, %d game_teams, %d game_players, "
                "%d champions, %d rosters, %d skipped (%.1fs)",
                stats["file"], stats["games"], stats["game_teams"],
                stats["game_players"], stats.get("champions_resolved", 0),
                stats.get("rosters_created", 0), stats["skipped"], elapsed,
            )
            results.append(stats)

        from entity_resolution.audit_log import get_unresolved_count
        unresolved = get_unresolved_count(session)
        if unresolved:
            logger.warning("Unresolved entities: %s", unresolved)
        else:
            logger.info("Entity resolution complete — 0 unresolved entities")

    finally:
        session.close()

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest OraclesElixir match CSVs")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("MATCH_DATA_DIR", "/data/matches"),
        help="Directory containing yearly CSV files",
    )
    args = parser.parse_args()
    results = ingest_all(args.data_dir)
    total_games = sum(r["games"] for r in results)
    total_players = sum(r["game_players"] for r in results)
    logger.info("TOTAL: %d games, %d player records ingested", total_games, total_players)
