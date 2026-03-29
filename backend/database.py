import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://draftgap:changeme@db:5432/draftgap_db",
)
if DATABASE_URL.startswith("postgresql://") and "+" not in DATABASE_URL.split("://")[0]:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

ALEMBIC_HEAD_REVISION = "20260329_01"
REQUIRED_RUNTIME_TABLES = {
    "bankroll",
    "bet",
    "bankroll_snapshot",
    "bet_event",
    "upcoming_with_odds_snapshot",
    "live_with_odds_snapshot",
    "betting_results_snapshot",
    "bankroll_summary_snapshot",
    "power_rankings_snapshot",
    "homepage_snapshot_manifest",
}

engine_kwargs: dict[str, object] = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["connect_args"] = {"connect_timeout": 5}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    import models  # noqa: F401
    import models_ml  # noqa: F401


def validate_runtime_schema() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    missing_tables = sorted(REQUIRED_RUNTIME_TABLES - table_names)
    if missing_tables:
        raise RuntimeError(
            "Database schema is missing required tables: "
            + ", ".join(missing_tables)
            + ". Run `alembic upgrade head`."
        )

    if engine.dialect.name == "sqlite":
        return

    if "alembic_version" not in table_names:
        raise RuntimeError(
            "Database schema is missing the alembic_version table. "
            "Run `alembic stamp 20260308_01` followed by `alembic upgrade head` "
            "if this is an existing pre-migration database."
        )

    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision != ALEMBIC_HEAD_REVISION:
        raise RuntimeError(
            f"Database schema revision is {revision or 'missing'}, expected {ALEMBIC_HEAD_REVISION}. "
            "Run `alembic upgrade head`."
        )
