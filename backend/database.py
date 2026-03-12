import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@db:5432/draftgap"
)
if DATABASE_URL.startswith("postgresql://") and "+" not in DATABASE_URL.split("://")[0]:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"connect_timeout": 5},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from models import GameStat
    from models_ml import (
        Bankroll,
        BankrollSnapshot,
        Bet,
        CanonicalChampion,
        ChampionAlias,
        EntityResolutionLog,
        Game,
        GamePlayer,
        GameTeam,
        League,
        LeagueAlias,
        MLModelRun,
        MatchFeature,
        Player,
        PlayerAlias,
        PredictionLog,
        Roster,
        Team,
        TeamAlias,
        TeamRating,
    )

    Base.metadata.create_all(bind=engine)
