from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Protocol

from rapidfuzz import fuzz


class RedisLike(Protocol):

    def get(self, name: str) -> bytes | None: ...
    def setex(self, name: str, time: int, value: str | bytes) -> None: ...
    def exists(self, *names: str) -> int: ...

from entity_resolution.aliases import (
    CHAMPION_ALIASES,
    LEAGUE_ALIASES,
    PLAYER_ALIASES,
    TEAM_ALIASES,
)
from entity_resolution.audit_log import log_resolution, log_unresolved
from entity_resolution.canonical_store import (
    add_champion_alias,
    add_league_alias,
    add_player_alias,
    add_team_alias,
    find_champion_by_alias,
    find_league_by_alias,
    find_player_by_alias,
    find_team_by_abbreviation,
    find_team_by_alias,
    find_team_by_pandascore_id,
    find_player_by_pandascore_id,
    get_all_teams,
    get_or_create_champion,
    get_or_create_league,
    get_or_create_player,
    get_or_create_team,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from models_ml import CanonicalChampion, League, Player, Team

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 88
REDIS_TTL_SECONDS = 86400


class EntityResolver:

    def __init__(self, session: Session, redis_client: RedisLike | None = None) -> None:
        self._session = session
        self._redis = redis_client
        self._team_cache: dict[str, int | None] = {}

    def _cache_key(self, entity_type: str, raw: str) -> str:
        return f"er:{entity_type}:{raw.lower().strip()}"

    def _cache_get(self, entity_type: str, raw: str) -> int | None:
        if self._redis is None:
            return self._team_cache.get(f"{entity_type}:{raw.lower().strip()}")
        key = self._cache_key(entity_type, raw)
        val = self._redis.get(key)
        if val is not None:
            return int(val) if val != b"null" else None
        return None

    def _cache_set(self, entity_type: str, raw: str, resolved_id: int | None) -> None:
        local_key = f"{entity_type}:{raw.lower().strip()}"
        self._team_cache[local_key] = resolved_id
        if self._redis is None:
            return
        key = self._cache_key(entity_type, raw)
        val = str(resolved_id) if resolved_id is not None else "null"
        self._redis.setex(key, REDIS_TTL_SECONDS, val)

    def _cache_has(self, entity_type: str, raw: str) -> bool:
        local_key = f"{entity_type}:{raw.lower().strip()}"
        if local_key in self._team_cache:
            return True
        if self._redis is None:
            return False
        return self._redis.exists(self._cache_key(entity_type, raw)) > 0

    def resolve_team(
        self,
        raw_name: str,
        source_system: str = "oracleselixir",
        *,
        pandascore_id: int | None = None,
        abbreviation: str | None = None,
        region: str | None = None,
    ) -> Team | None:
        raw = raw_name.strip()
        if not raw:
            return None

        if self._cache_has("team", raw):
            cached_id = self._cache_get("team", raw)
            if cached_id is not None:
                return self._session.query(
                    __import__("models_ml", fromlist=["Team"]).Team
                ).get(cached_id)
            return None

        team = self._resolve_team_inner(raw, source_system, pandascore_id=pandascore_id, abbreviation=abbreviation, region=region)
        self._cache_set("team", raw, team.id if team else None)
        return team

    def _resolve_team_inner(
        self,
        raw: str,
        source_system: str,
        *,
        pandascore_id: int | None = None,
        abbreviation: str | None = None,
        region: str | None = None,
    ) -> Team | None:
        from models_ml import Team as TeamModel

        canonical = TEAM_ALIASES.get(raw.lower().strip())
        if canonical:
            team = find_team_by_alias(self._session, canonical)
            if not team:
                team = get_or_create_team(
                    self._session, canonical, abbreviation=abbreviation, region=region,
                )
            add_team_alias(self._session, team.id, raw, source_system)
            log_resolution(
                self._session, raw_value=raw, entity_type="team",
                resolved_id=team.id, method="manual", confidence=1.0,
                source_system=source_system,
            )
            return team

        if pandascore_id is not None:
            team = find_team_by_pandascore_id(self._session, pandascore_id)
            if team:
                add_team_alias(self._session, team.id, raw, source_system)
                log_resolution(
                    self._session, raw_value=raw, entity_type="team",
                    resolved_id=team.id, method="pandascore_id", confidence=1.0,
                    source_system=source_system,
                )
                return team

        team = find_team_by_alias(self._session, raw)
        if team:
            add_team_alias(self._session, team.id, raw, source_system)
            log_resolution(
                self._session, raw_value=raw, entity_type="team",
                resolved_id=team.id, method="exact", confidence=1.0,
                source_system=source_system,
            )
            return team

        if abbreviation:
            team = find_team_by_abbreviation(self._session, abbreviation)
            if team:
                add_team_alias(self._session, team.id, raw, source_system)
                log_resolution(
                    self._session, raw_value=raw, entity_type="team",
                    resolved_id=team.id, method="abbreviation", confidence=0.95,
                    source_system=source_system,
                )
                return team

        all_teams = get_all_teams(self._session)
        best_score = 0.0
        best_team: Team | None = None
        for t in all_teams:
            score = fuzz.token_sort_ratio(raw.lower(), t.canonical_name.lower())
            if score > best_score:
                best_score = score
                best_team = t
            for alias in t.aliases:
                alias_score = fuzz.token_sort_ratio(raw.lower(), alias.alias.lower())
                if alias_score > best_score:
                    best_score = alias_score
                    best_team = t

        if best_score >= FUZZY_THRESHOLD and best_team is not None:
            add_team_alias(self._session, best_team.id, raw, source_system)
            log_resolution(
                self._session, raw_value=raw, entity_type="team",
                resolved_id=best_team.id, method="fuzzy",
                confidence=best_score / 100.0, source_system=source_system,
            )
            return best_team

        team = get_or_create_team(
            self._session, raw, abbreviation=abbreviation, region=region,
            pandascore_id=pandascore_id,
        )
        add_team_alias(self._session, team.id, raw, source_system)
        log_resolution(
            self._session, raw_value=raw, entity_type="team",
            resolved_id=team.id, method="auto_create", confidence=0.5,
            source_system=source_system,
        )
        return team

    def resolve_player(
        self,
        raw_name: str,
        source_system: str = "oracleselixir",
        *,
        pandascore_id: int | None = None,
        role: str | None = None,
        oe_player_id: str | None = None,
    ) -> Player | None:
        raw = raw_name.strip()
        if not raw:
            return None

        if self._cache_has("player", raw):
            cached_id = self._cache_get("player", raw)
            if cached_id is not None:
                from models_ml import Player as PlayerModel
                return self._session.query(PlayerModel).get(cached_id)
            return None

        player = self._resolve_player_inner(raw, source_system, pandascore_id=pandascore_id, role=role, oe_player_id=oe_player_id)
        self._cache_set("player", raw, player.id if player else None)
        return player

    def _resolve_player_inner(
        self,
        raw: str,
        source_system: str,
        *,
        pandascore_id: int | None = None,
        role: str | None = None,
        oe_player_id: str | None = None,
    ) -> Player | None:
        canonical = PLAYER_ALIASES.get(raw.lower().strip())
        if canonical:
            player = find_player_by_alias(self._session, canonical)
            if not player:
                player = get_or_create_player(self._session, canonical, primary_role=role, oe_player_id=oe_player_id)
            add_player_alias(self._session, player.id, raw, source_system)
            log_resolution(
                self._session, raw_value=raw, entity_type="player",
                resolved_id=player.id, method="manual", confidence=1.0,
                source_system=source_system,
            )
            return player

        if pandascore_id is not None:
            player = find_player_by_pandascore_id(self._session, pandascore_id)
            if player:
                add_player_alias(self._session, player.id, raw, source_system)
                log_resolution(
                    self._session, raw_value=raw, entity_type="player",
                    resolved_id=player.id, method="pandascore_id", confidence=1.0,
                    source_system=source_system,
                )
                return player

        player = find_player_by_alias(self._session, raw)
        if player:
            add_player_alias(self._session, player.id, raw, source_system)
            log_resolution(
                self._session, raw_value=raw, entity_type="player",
                resolved_id=player.id, method="exact", confidence=1.0,
                source_system=source_system,
            )
            return player

        player = get_or_create_player(
            self._session, raw, primary_role=role, oe_player_id=oe_player_id,
            pandascore_id=pandascore_id,
        )
        add_player_alias(self._session, player.id, raw, source_system)
        log_resolution(
            self._session, raw_value=raw, entity_type="player",
            resolved_id=player.id, method="auto_create", confidence=0.5,
            source_system=source_system,
        )
        return player

    def resolve_champion(
        self,
        raw_name: str,
        source_system: str = "oracleselixir",
    ) -> CanonicalChampion | None:
        raw = raw_name.strip()
        if not raw or raw.lower() == "nan":
            return None

        if self._cache_has("champion", raw):
            cached_id = self._cache_get("champion", raw)
            if cached_id is not None:
                from models_ml import CanonicalChampion as ChampModel
                return self._session.query(ChampModel).get(cached_id)
            return None

        champ = self._resolve_champion_inner(raw, source_system)
        self._cache_set("champion", raw, champ.id if champ else None)
        return champ

    def _resolve_champion_inner(
        self,
        raw: str,
        source_system: str,
    ) -> CanonicalChampion | None:
        canonical = CHAMPION_ALIASES.get(raw.lower().strip())
        if canonical:
            champ = find_champion_by_alias(self._session, canonical)
            if not champ:
                champ = get_or_create_champion(self._session, canonical)
            add_champion_alias(self._session, champ.id, raw, source_system)
            log_resolution(
                self._session, raw_value=raw, entity_type="champion",
                resolved_id=champ.id, method="manual", confidence=1.0,
                source_system=source_system,
            )
            return champ

        champ = find_champion_by_alias(self._session, raw)
        if champ:
            add_champion_alias(self._session, champ.id, raw, source_system)
            log_resolution(
                self._session, raw_value=raw, entity_type="champion",
                resolved_id=champ.id, method="exact", confidence=1.0,
                source_system=source_system,
            )
            return champ

        champ = get_or_create_champion(self._session, raw)
        add_champion_alias(self._session, champ.id, raw, source_system)
        log_resolution(
            self._session, raw_value=raw, entity_type="champion",
            resolved_id=champ.id, method="auto_create", confidence=0.8,
            source_system=source_system,
        )
        return champ

    def resolve_league(
        self,
        raw_name: str,
        source_system: str = "oracleselixir",
    ) -> League | None:
        raw = raw_name.strip()
        if not raw:
            return None

        if self._cache_has("league", raw):
            cached_id = self._cache_get("league", raw)
            if cached_id is not None:
                from models_ml import League as LeagueModel
                return self._session.query(LeagueModel).get(cached_id)
            return None

        league = self._resolve_league_inner(raw, source_system)
        self._cache_set("league", raw, league.id if league else None)
        return league

    def _resolve_league_inner(self, raw: str, source_system: str) -> League | None:
        canonical = LEAGUE_ALIASES.get(raw.lower().strip())
        if canonical:
            league = find_league_by_alias(self._session, canonical)
            if not league:
                league = get_or_create_league(self._session, canonical.lower(), name=canonical)
            add_league_alias(self._session, league.id, raw, source_system)
            log_resolution(
                self._session, raw_value=raw, entity_type="league",
                resolved_id=league.id, method="manual", confidence=1.0,
                source_system=source_system,
            )
            return league

        league = find_league_by_alias(self._session, raw)
        if league:
            add_league_alias(self._session, league.id, raw, source_system)
            log_resolution(
                self._session, raw_value=raw, entity_type="league",
                resolved_id=league.id, method="exact", confidence=1.0,
                source_system=source_system,
            )
            return league

        slug = raw.lower().strip().replace(" ", "_")
        league = get_or_create_league(self._session, slug, name=raw)
        add_league_alias(self._session, league.id, raw, source_system)
        log_resolution(
            self._session, raw_value=raw, entity_type="league",
            resolved_id=league.id, method="auto_create", confidence=0.5,
            source_system=source_system,
        )
        return league
