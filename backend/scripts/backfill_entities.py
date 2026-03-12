
from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal, init_db
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backfill_entities")


def backfill_champions(session) -> int:
    logger.info("Backfilling canonical champions...")

    champ_names: set[str] = set()

    rows = session.execute(text(
        "SELECT DISTINCT champion FROM game_player WHERE champion IS NOT NULL AND champion != ''"
    )).fetchall()
    for r in rows:
        champ_names.add(r[0].strip())

    for col in ["pick1", "pick2", "pick3", "pick4", "pick5", "ban1", "ban2", "ban3", "ban4", "ban5"]:
        rows = session.execute(text(
            f"SELECT DISTINCT {col} FROM game_team WHERE {col} IS NOT NULL AND {col} != ''"
        )).fetchall()
        for r in rows:
            champ_names.add(r[0].strip())

    existing = {
        r[0] for r in
        session.execute(text("SELECT canonical_name FROM canonical_champion")).fetchall()
    }
    new_champs = champ_names - existing

    created = 0
    for name in sorted(new_champs):
        internal_key = name.replace(" ", "").replace("'", "").replace(".", "")
        session.execute(text(
            "INSERT INTO canonical_champion (canonical_name, internal_key, created_at) "
            "VALUES (:name, :key, NOW()) ON CONFLICT (canonical_name) DO NOTHING"
        ), {"name": name, "key": internal_key})
        created += 1

    session.commit()
    logger.info("Created %d canonical champions (total unique: %d)", created, len(champ_names))

    champ_map = {
        r[0]: r[1] for r in
        session.execute(text("SELECT canonical_name, id FROM canonical_champion")).fetchall()
    }

    alias_count = 0
    for name, cid in champ_map.items():
        for variant in _champion_variants(name):
            try:
                session.execute(text(
                    "INSERT INTO champion_alias (champion_id, alias, source, created_at) "
                    "VALUES (:cid, :alias, 'auto', NOW()) ON CONFLICT ON CONSTRAINT uq_champion_alias_alias_source DO NOTHING"
                ), {"cid": cid, "alias": variant})
                alias_count += 1
            except Exception:
                session.rollback()
                continue
    session.commit()
    logger.info("Created champion aliases: %d", alias_count)

    return created


def _champion_variants(name: str) -> list[str]:
    variants = [name, name.lower(), name.upper()]
    no_space = name.replace(" ", "")
    if no_space != name:
        variants.append(no_space)
        variants.append(no_space.lower())
    no_apost = name.replace("'", "")
    if no_apost != name:
        variants.append(no_apost)
        variants.append(no_apost.lower())
    if "&" in name:
        variants.append(name.split("&")[0].strip())
        variants.append(name.split("&")[0].strip().lower())
    return list(set(variants))


def backfill_rosters(session) -> int:
    logger.info("Backfilling roster entries from game_player data...")

    rows = session.execute(text("""
        SELECT
            gp.player_id,
            gp.team_id,
            gp.position,
            MIN(g.played_at)::date as first_game,
            MAX(g.played_at)::date as last_game,
            COUNT(*) as game_count
        FROM game_player gp
        JOIN game g ON g.id = gp.game_id
        GROUP BY gp.player_id, gp.team_id, gp.position
        ORDER BY first_game
    """)).fetchall()

    created = 0
    for r in rows:
        player_id, team_id, position, first_game, last_game, game_count = r
        existing = session.execute(text(
            "SELECT id FROM roster WHERE player_id = :pid AND team_id = :tid AND role = :role"
        ), {"pid": player_id, "tid": team_id, "role": position}).fetchone()

        if existing:
            session.execute(text(
                "UPDATE roster SET joined_at = LEAST(joined_at, :first), left_at = GREATEST(left_at, :last) "
                "WHERE id = :rid"
            ), {"first": first_game, "last": last_game, "rid": existing[0]})
        else:
            session.execute(text(
                "INSERT INTO roster (player_id, team_id, role, joined_at, left_at, source, created_at) "
                "VALUES (:pid, :tid, :role, :first, :last, 'csv_backfill', NOW())"
            ), {"pid": player_id, "tid": team_id, "role": position,
                "first": first_game, "last": last_game})
            created += 1

    session.commit()
    logger.info("Created %d roster entries from %d player-team combinations", created, len(rows))
    return created


def backfill_team_early_stats(session) -> int:
    logger.info("Backfilling game_team early-game stats from game_player aggregates...")

    result = session.execute(text("""
        UPDATE game_team gt
        SET
            goldat10 = agg.sum_goldat10,
            xpat10 = agg.sum_xpat10,
            csat10 = agg.sum_csat10,
            golddiffat10 = agg.sum_golddiffat10,
            xpdiffat10 = agg.sum_xpdiffat10,
            csdiffat10 = agg.sum_csdiffat10
        FROM (
            SELECT gp.game_id, gp.team_id,
                SUM(gp.goldat10) as sum_goldat10,
                SUM(gp.xpat10) as sum_xpat10,
                SUM(gp.csat10) as sum_csat10,
                SUM(gp.golddiffat10) as sum_golddiffat10,
                SUM(gp.xpdiffat10) as sum_xpdiffat10,
                SUM(gp.csdiffat10) as sum_csdiffat10
            FROM game_player gp
            WHERE gp.goldat10 IS NOT NULL
            GROUP BY gp.game_id, gp.team_id
        ) agg
        WHERE gt.game_id = agg.game_id AND gt.team_id = agg.team_id
          AND gt.goldat10 IS NULL
    """))
    session.commit()
    updated = result.rowcount
    logger.info("Updated %d game_team rows with early-game stats from player data", updated)
    return updated


def enrich_from_pandascore(session) -> dict:
    logger.info("Enriching teams and players from PandaScore...")

    import os
    import time as _time
    import httpx

    token = os.environ.get("PANDA_SCORE_KEY", "").strip()
    if not token:
        logger.warning("PANDA_SCORE_KEY not set, skipping PandaScore enrichment")
        return {"status": "skipped", "reason": "no_token"}

    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    enriched_players = 0
    matched_teams = 0
    errors: list[str] = []

    our_teams: dict[str, int] = {}
    for r in session.execute(text("SELECT id, LOWER(canonical_name) FROM team")).fetchall():
        our_teams[r[1]] = r[0]
    our_abbrs: dict[str, int] = {}
    for r in session.execute(text("SELECT id, LOWER(abbreviation) FROM team WHERE abbreviation IS NOT NULL")).fetchall():
        our_abbrs[r[1]] = r[0]
    our_aliases: dict[str, int] = {}
    for r in session.execute(text("SELECT team_id, LOWER(alias) FROM team_alias")).fetchall():
        our_aliases[r[1]] = r[0]

    def _find_our_team(ps_name: str, ps_acronym: str | None) -> int | None:
        key = ps_name.lower().strip()
        if key in our_teams:
            return our_teams[key]
        if key in our_aliases:
            return our_aliases[key]
        if ps_acronym:
            acr = ps_acronym.lower().strip()
            if acr in our_abbrs:
                return our_abbrs[acr]
            if acr in our_aliases:
                return our_aliases[acr]
        return None

    def _enrich_player(p: dict, our_team_id: int | None) -> bool:
        nonlocal enriched_players
        p_name = (p.get("name") or "").strip()
        if not p_name:
            return False
        first_name = (p.get("first_name") or "").strip()
        last_name = (p.get("last_name") or "").strip()
        real_name = f"{first_name} {last_name}".strip() if first_name or last_name else None
        nationality = p.get("nationality")
        ps_id = p.get("id")
        role = (p.get("role") or "").lower()
        role_map = {"jun": "jng", "adc": "bot"}
        role = role_map.get(role, role)

        player_row = None
        if ps_id:
            player_row = session.execute(text(
                "SELECT id FROM player WHERE pandascore_id = :psid"
            ), {"psid": ps_id}).fetchone()
        if not player_row:
            player_row = session.execute(text(
                "SELECT id FROM player WHERE LOWER(canonical_name) = LOWER(:name)"
            ), {"name": p_name}).fetchone()
        if not player_row:
            player_row = session.execute(text(
                "SELECT p.id FROM player p JOIN player_alias pa ON pa.player_id = p.id "
                "WHERE LOWER(pa.alias) = LOWER(:name) LIMIT 1"
            ), {"name": p_name}).fetchone()

        if not player_row:
            return False

        pid = player_row[0]
        parts: list[str] = []
        params: dict = {"pid": pid}
        if real_name:
            parts.append("real_name = COALESCE(real_name, :real_name)")
            params["real_name"] = real_name
        if nationality:
            parts.append("nationality = COALESCE(nationality, :nationality)")
            params["nationality"] = nationality
        if ps_id:
            parts.append("pandascore_id = COALESCE(pandascore_id, :psid)")
            params["psid"] = ps_id
        if role:
            parts.append("primary_role = COALESCE(primary_role, :role)")
            params["role"] = role
        if parts:
            session.execute(text(f"UPDATE player SET {', '.join(parts)} WHERE id = :pid"), params)
            enriched_players += 1
        return True

    with httpx.Client(timeout=20.0) as client:
        ps_teams_seen: set[int] = set()

        for endpoint in [
            "/lol/tournaments/running",
            "/lol/tournaments/past",
        ]:
            page = 1
            max_pages = 5 if "past" in endpoint else 3
            while page <= max_pages:
                try:
                    r = client.get(
                        f"https://api.pandascore.co{endpoint}",
                        params={"per_page": 10, "page": page, "sort": "-begin_at"},
                        headers=headers,
                    )
                    if r.status_code != 200:
                        break
                    tournaments = r.json()
                    if not tournaments:
                        break

                    for tourney in tournaments:
                        teams = tourney.get("teams") or []
                        for tm in teams:
                            ps_tid = tm.get("id")
                            if not ps_tid or ps_tid in ps_teams_seen:
                                continue
                            ps_teams_seen.add(ps_tid)

                            ps_name = tm.get("name", "")
                            ps_acr = tm.get("acronym")
                            our_tid = _find_our_team(ps_name, ps_acr)

                            if our_tid:
                                matched_teams += 1
                                session.execute(text(
                                    "UPDATE team SET pandascore_id = :psid WHERE id = :tid AND pandascore_id IS NULL"
                                ), {"psid": ps_tid, "tid": our_tid})
                                location = tm.get("location")
                                if location:
                                    session.execute(text(
                                        "UPDATE team SET region = COALESCE(region, :loc) WHERE id = :tid"
                                    ), {"loc": location, "tid": our_tid})

                            for p in tm.get("players") or []:
                                _enrich_player(p, our_tid)

                    page += 1
                    _time.sleep(0.3)

                except Exception as e:
                    errors.append(f"tournament fetch p{page}: {e}")
                    break

        logger.info(
            "Phase 1 (tournaments): %d PS teams seen, %d matched, %d players enriched",
            len(ps_teams_seen), matched_teams, enriched_players,
        )
        session.commit()

        active_teams = session.execute(text("""
            SELECT DISTINCT t.id, t.canonical_name, t.abbreviation
            FROM team t
            JOIN game_team gt ON gt.team_id = t.id
            JOIN game g ON g.id = gt.game_id
            WHERE g.played_at >= '2025-01-01'
              AND t.pandascore_id IS NULL
        """)).fetchall()
        logger.info("Phase 2: searching PandaScore for %d active teams without PS ID...", len(active_teams))

        for tid, tname, tabbr in active_teams:
            try:
                r = client.get(
                    "https://api.pandascore.co/lol/teams",
                    params={"search[name]": tname, "per_page": 5},
                    headers=headers,
                )
                if r.status_code != 200:
                    continue
                results = r.json()
                for tm in results:
                    if tm["name"].lower().strip() == tname.lower().strip():
                        ps_tid = tm["id"]
                        session.execute(text(
                            "UPDATE team SET pandascore_id = :psid WHERE id = :tid AND pandascore_id IS NULL"
                        ), {"psid": ps_tid, "tid": tid})
                        matched_teams += 1
                        for p in tm.get("players") or []:
                            _enrich_player(p, tid)
                        break
                    elif tabbr and (tm.get("acronym") or "").lower() == tabbr.lower():
                        ps_tid = tm["id"]
                        session.execute(text(
                            "UPDATE team SET pandascore_id = :psid WHERE id = :tid AND pandascore_id IS NULL"
                        ), {"psid": ps_tid, "tid": tid})
                        matched_teams += 1
                        for p in tm.get("players") or []:
                            _enrich_player(p, tid)
                        break
                _time.sleep(0.5)
            except Exception as e:
                errors.append(f"search {tname}: {e}")
                continue

        session.commit()

    logger.info(
        "PandaScore enrichment done: %d teams matched, %d players enriched, %d errors",
        matched_teams, enriched_players, len(errors),
    )
    if errors:
        for e in errors[:5]:
            logger.warning("  error: %s", e)
    return {
        "status": "success",
        "teams_matched": matched_teams,
        "players_enriched": enriched_players,
        "errors": len(errors),
    }


def backfill_team_regions_from_league(session) -> int:
    logger.info("Backfilling team regions from league data...")

    result = session.execute(text("""
        UPDATE team t
        SET region = sub.region
        FROM (
            SELECT gt.team_id, l.region,
                ROW_NUMBER() OVER (PARTITION BY gt.team_id ORDER BY COUNT(*) DESC) as rn
            FROM game_team gt
            JOIN game g ON g.id = gt.game_id
            JOIN league l ON l.id = g.league_id
            WHERE l.region IS NOT NULL
            GROUP BY gt.team_id, l.region
        ) sub
        WHERE t.id = sub.team_id AND sub.rn = 1 AND t.region IS NULL
    """))
    session.commit()
    updated = result.rowcount
    logger.info("Updated %d teams with region from most-played league", updated)
    return updated


def report_coverage(session) -> None:
    stats = {}
    for tbl, col in [
        ("canonical_champion", "id"),
        ("champion_alias", "id"),
        ("player", "id"),
        ("player", "real_name"),
        ("player", "nationality"),
        ("player", "pandascore_id"),
        ("team", "id"),
        ("team", "region"),
        ("team", "pandascore_id"),
        ("roster", "id"),
    ]:
        total = session.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
        if col == "id":
            stats[f"{tbl}"] = total
        else:
            has = session.execute(text(f"SELECT COUNT(*) FROM {tbl} WHERE {col} IS NOT NULL")).scalar()
            stats[f"{tbl}.{col}"] = f"{has}/{total} ({has*100//max(total,1)}%)"

    logger.info("=== Final Coverage Report ===")
    for key, val in stats.items():
        logger.info("  %s: %s", key, val)


def main() -> None:
    init_db()
    session = SessionLocal()

    try:
        backfill_champions(session)
        backfill_rosters(session)
        backfill_team_early_stats(session)
        backfill_team_regions_from_league(session)
        enrich_from_pandascore(session)
        report_coverage(session)
    finally:
        session.close()


if __name__ == "__main__":
    main()
