from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from models_ml import (
    CanonicalChampion,
    ChampionAlias,
    League,
    LeagueAlias,
    Player,
    PlayerAlias,
    Roster,
    Team,
    TeamAlias,
)

logger = logging.getLogger(__name__)


def get_or_create_team(
    session: Session,
    canonical_name: str,
    *,
    abbreviation: str | None = None,
    region: str | None = None,
    oe_team_id: str | None = None,
    pandascore_id: int | None = None,
) -> Team:
    team = session.query(Team).filter(Team.canonical_name == canonical_name).first()
    if team:
        if pandascore_id and not team.pandascore_id:
            team.pandascore_id = pandascore_id
        if abbreviation and not team.abbreviation:
            team.abbreviation = abbreviation
        if region and not team.region:
            team.region = region
        if oe_team_id and not team.oe_team_id:
            team.oe_team_id = oe_team_id
        return team
    team = Team(
        canonical_name=canonical_name,
        abbreviation=abbreviation,
        region=region,
        oe_team_id=oe_team_id,
        pandascore_id=pandascore_id,
    )
    session.add(team)
    session.flush()
    return team


def add_team_alias(session: Session, team_id: int, alias: str, source: str) -> TeamAlias | None:
    existing = (
        session.query(TeamAlias)
        .filter(TeamAlias.alias == alias, TeamAlias.source == source)
        .first()
    )
    if existing:
        return existing
    ta = TeamAlias(team_id=team_id, alias=alias, source=source)
    session.add(ta)
    return ta


def find_team_by_alias(session: Session, alias: str) -> Team | None:
    ta = (
        session.query(TeamAlias)
        .filter(TeamAlias.alias.ilike(alias.strip()))
        .first()
    )
    if ta:
        return session.query(Team).get(ta.team_id)
    return session.query(Team).filter(Team.canonical_name.ilike(alias.strip())).first()


def normalize_team_for_settlement(session: Session, raw: str) -> str:
    from entity_resolution.aliases import TEAM_ALIASES

    stripped = raw.strip()
    lowered = stripped.lower()

    canonical = TEAM_ALIASES.get(lowered)
    if canonical:
        return canonical.lower()

    team = find_team_by_alias(session, stripped)
    if team:
        return team.canonical_name.lower()

    return lowered


def find_team_by_pandascore_id(session: Session, pandascore_id: int) -> Team | None:
    return session.query(Team).filter(Team.pandascore_id == pandascore_id).first()


def find_team_by_abbreviation(session: Session, abbreviation: str) -> Team | None:
    return (
        session.query(Team)
        .filter(Team.abbreviation.ilike(abbreviation.strip()))
        .first()
    )


def get_all_teams(session: Session) -> list[Team]:
    return session.query(Team).order_by(Team.canonical_name).all()


def get_or_create_player(
    session: Session,
    canonical_name: str,
    *,
    primary_role: str | None = None,
    oe_player_id: str | None = None,
    pandascore_id: int | None = None,
    nationality: str | None = None,
    real_name: str | None = None,
) -> Player:
    player = session.query(Player).filter(Player.canonical_name == canonical_name).first()
    if player:
        if pandascore_id and not player.pandascore_id:
            player.pandascore_id = pandascore_id
        if primary_role and not player.primary_role:
            player.primary_role = primary_role
        if oe_player_id and not player.oe_player_id:
            player.oe_player_id = oe_player_id
        return player
    player = Player(
        canonical_name=canonical_name,
        primary_role=primary_role,
        oe_player_id=oe_player_id,
        pandascore_id=pandascore_id,
        nationality=nationality,
        real_name=real_name,
    )
    session.add(player)
    session.flush()
    return player


def add_player_alias(session: Session, player_id: int, alias: str, source: str) -> PlayerAlias | None:
    existing = (
        session.query(PlayerAlias)
        .filter(PlayerAlias.alias == alias, PlayerAlias.source == source)
        .first()
    )
    if existing:
        return existing
    pa = PlayerAlias(player_id=player_id, alias=alias, source=source)
    session.add(pa)
    return pa


def find_player_by_alias(session: Session, alias: str) -> Player | None:
    pa = (
        session.query(PlayerAlias)
        .filter(PlayerAlias.alias.ilike(alias.strip()))
        .first()
    )
    if pa:
        return session.query(Player).get(pa.player_id)
    return session.query(Player).filter(Player.canonical_name.ilike(alias.strip())).first()


def find_player_by_pandascore_id(session: Session, pandascore_id: int) -> Player | None:
    return session.query(Player).filter(Player.pandascore_id == pandascore_id).first()


def get_or_create_champion(
    session: Session,
    canonical_name: str,
    *,
    internal_key: str | None = None,
) -> CanonicalChampion:
    champ = session.query(CanonicalChampion).filter(CanonicalChampion.canonical_name == canonical_name).first()
    if champ:
        if internal_key and not champ.internal_key:
            champ.internal_key = internal_key
        return champ
    champ = CanonicalChampion(canonical_name=canonical_name, internal_key=internal_key)
    session.add(champ)
    session.flush()
    return champ


def add_champion_alias(session: Session, champion_id: int, alias: str, source: str) -> ChampionAlias | None:
    existing = (
        session.query(ChampionAlias)
        .filter(ChampionAlias.alias == alias, ChampionAlias.source == source)
        .first()
    )
    if existing:
        return existing
    ca = ChampionAlias(champion_id=champion_id, alias=alias, source=source)
    session.add(ca)
    return ca


def find_champion_by_alias(session: Session, alias: str) -> CanonicalChampion | None:
    ca = (
        session.query(ChampionAlias)
        .filter(ChampionAlias.alias.ilike(alias.strip()))
        .first()
    )
    if ca:
        return session.query(CanonicalChampion).get(ca.champion_id)
    return session.query(CanonicalChampion).filter(CanonicalChampion.canonical_name.ilike(alias.strip())).first()


def get_or_create_league(
    session: Session,
    slug: str,
    *,
    name: str | None = None,
    tier: str | None = None,
    tier_weight: float | None = None,
    region: str | None = None,
) -> League:
    league = session.query(League).filter(League.slug == slug).first()
    if league:
        if name and not league.name:
            league.name = name
        if tier and not league.tier:
            league.tier = tier
        if region and not league.region:
            league.region = region
        return league
    league = League(slug=slug, name=name, tier=tier, tier_weight=tier_weight, region=region)
    session.add(league)
    session.flush()
    return league


def add_league_alias(session: Session, league_id: int, alias: str, source: str) -> LeagueAlias | None:
    existing = (
        session.query(LeagueAlias)
        .filter(LeagueAlias.alias == alias, LeagueAlias.source == source)
        .first()
    )
    if existing:
        return existing
    la = LeagueAlias(league_id=league_id, alias=alias, source=source)
    session.add(la)
    return la


def find_league_by_alias(session: Session, alias: str) -> League | None:
    la = (
        session.query(LeagueAlias)
        .filter(LeagueAlias.alias.ilike(alias.strip()))
        .first()
    )
    if la:
        return session.query(League).get(la.league_id)
    return session.query(League).filter(League.slug.ilike(alias.strip())).first()


def set_roster_entry(
    session: Session,
    team_id: int,
    player_id: int,
    role: str,
    source: str = "csv",
    joined_at: "date | None" = None,
) -> Roster:
    from datetime import date as date_type

    existing = (
        session.query(Roster)
        .filter(
            Roster.team_id == team_id,
            Roster.player_id == player_id,
            Roster.role == role,
            Roster.left_at.is_(None),
        )
        .first()
    )
    if existing:
        return existing
    entry = Roster(
        team_id=team_id,
        player_id=player_id,
        role=role,
        source=source,
        joined_at=joined_at,
    )
    session.add(entry)
    return entry


def get_active_roster(session: Session, team_id: int) -> list[Roster]:
    return (
        session.query(Roster)
        .filter(Roster.team_id == team_id, Roster.left_at.is_(None))
        .order_by(Roster.role)
        .all()
    )


def deactivate_roster(session: Session, team_id: int) -> int:
    from datetime import date as date_type

    count = (
        session.query(Roster)
        .filter(Roster.team_id == team_id, Roster.left_at.is_(None))
        .update({"left_at": date_type.today()})
    )
    return count
