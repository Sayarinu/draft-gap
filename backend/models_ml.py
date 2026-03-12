from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime
from uuid import UUID as UUIDType, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class League(Base):
    __tablename__ = "league"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(8), nullable=True)
    tier_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    aliases: Mapped[list[LeagueAlias]] = relationship("LeagueAlias", back_populates="league", lazy="selectin")
    games: Mapped[list[Game]] = relationship("Game", back_populates="league", lazy="selectin")


class LeagueAlias(Base):
    __tablename__ = "league_alias"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("league.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    league: Mapped[League] = relationship("League", back_populates="aliases")

    __table_args__ = (UniqueConstraint("alias", "source", name="uq_league_alias_alias_source"),)


class Team(Base):
    __tablename__ = "team"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    abbreviation: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    oe_team_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    pandascore_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True, index=True)
    active_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    aliases: Mapped[list[TeamAlias]] = relationship("TeamAlias", back_populates="team", lazy="selectin")
    ratings: Mapped[list[TeamRating]] = relationship("TeamRating", back_populates="team", lazy="selectin")
    roster_entries: Mapped[list[Roster]] = relationship("Roster", back_populates="team", lazy="selectin")


class TeamAlias(Base):
    __tablename__ = "team_alias"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    team: Mapped[Team] = relationship("Team", back_populates="aliases")

    __table_args__ = (UniqueConstraint("alias", "source", name="uq_team_alias_alias_source"),)


class Player(Base):
    __tablename__ = "player"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    real_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    oe_player_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    pandascore_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True, index=True)
    active_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    aliases: Mapped[list[PlayerAlias]] = relationship("PlayerAlias", back_populates="player", lazy="selectin")
    roster_entries: Mapped[list[Roster]] = relationship("Roster", back_populates="player", lazy="selectin")


class PlayerAlias(Base):
    __tablename__ = "player_alias"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    player: Mapped[Player] = relationship("Player", back_populates="aliases")

    __table_args__ = (UniqueConstraint("alias", "source", name="uq_player_alias_alias_source"),)


class Roster(Base):
    __tablename__ = "roster"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    joined_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    left_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="csv")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    team: Mapped[Team] = relationship("Team", back_populates="roster_entries")
    player: Mapped[Player] = relationship("Player", back_populates="roster_entries")

    __table_args__ = (
        Index("ix_roster_team_active", "team_id", "left_at"),
        Index("ix_roster_player_active", "player_id", "left_at"),
    )


class CanonicalChampion(Base):
    __tablename__ = "canonical_champion"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    internal_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    aliases: Mapped[list[ChampionAlias]] = relationship("ChampionAlias", back_populates="champion", lazy="selectin")


class ChampionAlias(Base):
    __tablename__ = "champion_alias"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    champion_id: Mapped[int] = mapped_column(ForeignKey("canonical_champion.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    champion: Mapped[CanonicalChampion] = relationship("CanonicalChampion", back_populates="aliases")

    __table_args__ = (UniqueConstraint("alias", "source", name="uq_champion_alias_alias_source"),)


class EntityResolutionLog(Base):
    __tablename__ = "entity_resolution_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_value: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resolved_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_system: Mapped[str] = mapped_column(String(32), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        Index("ix_er_log_unresolved", "entity_type", "resolved"),
        Index("ix_er_log_raw", "raw_value", "entity_type", "source_system"),
    )


class Game(Base):
    __tablename__ = "game"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    gameid_oe: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("league.id", ondelete="RESTRICT"), nullable=False, index=True)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    patch: Mapped[str | None] = mapped_column(String(16), nullable=True)
    split: Mapped[str | None] = mapped_column(String(64), nullable=True)
    playoffs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gamelength_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blue_team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="RESTRICT"), nullable=False, index=True)
    red_team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="RESTRICT"), nullable=False, index=True)
    blue_win: Mapped[bool] = mapped_column(Boolean, nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="oracles_elixir")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    league: Mapped[League] = relationship("League", back_populates="games")
    game_teams: Mapped[list[GameTeam]] = relationship("GameTeam", back_populates="game", lazy="selectin")
    game_players: Mapped[list[GamePlayer]] = relationship("GamePlayer", back_populates="game", lazy="selectin")

    __table_args__ = (
        Index("ix_game_league_played", "league_id", "played_at"),
        Index("ix_game_blue_played", "blue_team_id", "played_at"),
        Index("ix_game_red_played", "red_team_id", "played_at"),
    )


class GameTeam(Base):
    __tablename__ = "game_team"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("game.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="RESTRICT"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    win: Mapped[bool] = mapped_column(Boolean, nullable=False)

    goldat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    xpat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    csat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    golddiffat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    xpdiffat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    csdiffat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    goldat15: Mapped[float | None] = mapped_column(Float, nullable=True)
    xpat15: Mapped[float | None] = mapped_column(Float, nullable=True)
    csat15: Mapped[float | None] = mapped_column(Float, nullable=True)
    golddiffat15: Mapped[float | None] = mapped_column(Float, nullable=True)
    xpdiffat15: Mapped[float | None] = mapped_column(Float, nullable=True)
    csdiffat15: Mapped[float | None] = mapped_column(Float, nullable=True)

    firstdragon: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dragons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    firstherald: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    heralds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    void_grubs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opp_void_grubs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    firstbaron: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    barons: Mapped[int | None] = mapped_column(Integer, nullable=True)
    atakhans: Mapped[int | None] = mapped_column(Integer, nullable=True)
    firsttower: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    towers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turretplates: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inhibitors: Mapped[int | None] = mapped_column(Integer, nullable=True)

    teamkills: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teamdeaths: Mapped[int | None] = mapped_column(Integer, nullable=True)
    firstblood: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    totalgold: Mapped[float | None] = mapped_column(Float, nullable=True)
    earnedgold: Mapped[float | None] = mapped_column(Float, nullable=True)
    damagetochampions: Mapped[float | None] = mapped_column(Float, nullable=True)
    wardsplaced: Mapped[float | None] = mapped_column(Float, nullable=True)
    wardskilled: Mapped[float | None] = mapped_column(Float, nullable=True)
    controlwardsbought: Mapped[float | None] = mapped_column(Float, nullable=True)
    visionscore: Mapped[float | None] = mapped_column(Float, nullable=True)

    pick1: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pick2: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pick3: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pick4: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pick5: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ban1: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ban2: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ban3: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ban4: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ban5: Mapped[str | None] = mapped_column(String(64), nullable=True)

    game: Mapped[Game] = relationship("Game", back_populates="game_teams")

    __table_args__ = (
        UniqueConstraint("game_id", "side", name="uq_game_team_game_side"),
        Index("ix_game_team_team_game", "team_id", "game_id"),
    )


class GamePlayer(Base):
    __tablename__ = "game_player"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("game.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="RESTRICT"), nullable=False, index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id", ondelete="RESTRICT"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    position: Mapped[str] = mapped_column(String(16), nullable=False)
    champion: Mapped[str | None] = mapped_column(String(64), nullable=True)

    kills: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deaths: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assists: Mapped[int | None] = mapped_column(Integer, nullable=True)

    damagetochampions: Mapped[float | None] = mapped_column(Float, nullable=True)
    dpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    damageshare: Mapped[float | None] = mapped_column(Float, nullable=True)
    earnedgold: Mapped[float | None] = mapped_column(Float, nullable=True)
    earnedgoldshare: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cs: Mapped[float | None] = mapped_column(Float, nullable=True)
    cspm: Mapped[float | None] = mapped_column(Float, nullable=True)

    visionscore: Mapped[float | None] = mapped_column(Float, nullable=True)
    vspm: Mapped[float | None] = mapped_column(Float, nullable=True)
    wardsplaced: Mapped[float | None] = mapped_column(Float, nullable=True)
    wpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    wardskilled: Mapped[float | None] = mapped_column(Float, nullable=True)
    controlwardsbought: Mapped[float | None] = mapped_column(Float, nullable=True)

    goldat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    xpat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    csat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    golddiffat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    xpdiffat10: Mapped[float | None] = mapped_column(Float, nullable=True)
    csdiffat10: Mapped[float | None] = mapped_column(Float, nullable=True)

    game: Mapped[Game] = relationship("Game", back_populates="game_players")

    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_game_player_game_player"),
        Index("ix_game_player_player_game", "player_id", "game_id"),
    )


class MatchFeature(Base):

    __tablename__ = "match_feature"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("game.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    blue_team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="RESTRICT"), nullable=False, index=True)
    red_team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="RESTRICT"), nullable=False, index=True)
    blue_win: Mapped[bool] = mapped_column(Boolean, nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    patch: Mapped[str | None] = mapped_column(String(16), nullable=True)
    league_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    playoffs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    feature_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        Index("ix_match_feature_played", "played_at"),
        Index("ix_match_feature_version", "feature_version"),
    )


class MLModelRun(Base):
    __tablename__ = "ml_model_run"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    train_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    val_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    train_log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    val_log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    train_roc_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    val_roc_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_roc_auc: Mapped[float | None] = mapped_column(Float, nullable=True)

    train_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    val_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feature_names_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PredictionLog(Base):
    __tablename__ = "prediction_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_run_id: Mapped[int | None] = mapped_column(ForeignKey("ml_model_run.id", ondelete="SET NULL"), nullable=True)
    team_a_id: Mapped[int | None] = mapped_column(ForeignKey("team.id", ondelete="SET NULL"), nullable=True)
    team_b_id: Mapped[int | None] = mapped_column(ForeignKey("team.id", ondelete="SET NULL"), nullable=True)
    team_a_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    team_b_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    game_win_prob_a: Mapped[float] = mapped_column(Float, nullable=False)
    series_format: Mapped[str | None] = mapped_column(String(8), nullable=True)
    series_score_a: Mapped[int | None] = mapped_column(Integer, nullable=True)
    series_score_b: Mapped[int | None] = mapped_column(Integer, nullable=True)
    series_win_prob_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_flag: Mapped[str | None] = mapped_column(String(16), nullable=True)
    key_factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    pandascore_match_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)


class TeamRating(Base):
    __tablename__ = "team_rating"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("team.id", ondelete="CASCADE"), nullable=False, index=True)
    league_id: Mapped[int | None] = mapped_column(ForeignKey("league.id", ondelete="CASCADE"), nullable=True, index=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    rating: Mapped[float] = mapped_column(Float, nullable=False)
    rd: Mapped[float | None] = mapped_column(Float, nullable=True)
    games_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    team: Mapped[Team] = relationship("Team", back_populates="ratings")

    __table_args__ = (
        UniqueConstraint("team_id", "league_id", "as_of_date", name="uq_team_rating_team_league_date"),
        Index("ix_team_rating_latest", "team_id", "league_id", "as_of_date"),
    )


class Bankroll(Base):
    __tablename__ = "bankroll"

    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    initial_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    staking_model: Mapped[str] = mapped_column(String(32), nullable=False, default="kelly_quarter")
    kelly_fraction: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=Decimal("0.250"))
    max_bet_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0500"))
    min_edge_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.0300"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    bets: Mapped[list[Bet]] = relationship("Bet", back_populates="bankroll", lazy="selectin")
    snapshots: Mapped[list[BankrollSnapshot]] = relationship("BankrollSnapshot", back_populates="bankroll", lazy="selectin")


class Bet(Base):
    __tablename__ = "bet"

    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    bankroll_id: Mapped[UUIDType] = mapped_column(ForeignKey("bankroll.id", ondelete="CASCADE"), nullable=False, index=True)
    pandascore_match_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    model_run_id: Mapped[int | None] = mapped_column(ForeignKey("ml_model_run.id", ondelete="SET NULL"), nullable=True, index=True)
    team_a: Mapped[str] = mapped_column(String(255), nullable=False)
    team_b: Mapped[str] = mapped_column(String(255), nullable=False)
    league: Mapped[str | None] = mapped_column(String(255), nullable=True)
    series_format: Mapped[str | None] = mapped_column(String(8), nullable=True)
    bet_on: Mapped[str] = mapped_column(String(255), nullable=False)
    model_prob: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    book_odds_locked: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    book_prob_adj: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    edge: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    ev: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    recommended_stake: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    actual_stake: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PLACED", index=True)
    profit_loss: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    closing_odds: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    bankroll: Mapped[Bankroll] = relationship("Bankroll", back_populates="bets")

    __table_args__ = (
        Index("ix_bet_status_placed", "status", "placed_at"),
        Index("ix_bet_bankroll_status", "bankroll_id", "status"),
    )


class BankrollSnapshot(Base):
    __tablename__ = "bankroll_snapshot"

    id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    bankroll_id: Mapped[UUIDType] = mapped_column(ForeignKey("bankroll.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=datetime.utcnow)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_bets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    roi_pct: Mapped[Decimal] = mapped_column(Numeric(8, 5), nullable=False, default=Decimal("0.00000"))
    peak_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    bankroll: Mapped[Bankroll] = relationship("Bankroll", back_populates="snapshots")
