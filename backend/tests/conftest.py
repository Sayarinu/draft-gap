from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    f"sqlite:///{BACKEND_DIR / 'test.sqlite3'}",
)
TEST_SQLITE_PATH = BACKEND_DIR / "test.sqlite3"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("FRONTEND_API_SECRET", "test-admin-key")
os.environ.setdefault("FRONTEND_URL", "http://localhost:3000")
os.environ.setdefault("PANDA_SCORE_KEY", "test-token")
os.environ.setdefault("ENABLE_API_DOCS", "false")
os.environ.setdefault("WARM_ODDS_CACHE_ON_STARTUP", "false")
os.environ.setdefault("ODDS_CACHE_WARM_DELAY_SECONDS", "0")
os.environ.setdefault("REDIS_URL", "")

import models  # noqa: E402,F401
import models_ml  # noqa: E402,F401
from api.v1 import betting as betting_api  # noqa: E402
from api.v1 import pandascore as pandascore_api  # noqa: E402
from database import Base, SessionLocal, engine  # noqa: E402
import main as app_main  # noqa: E402

ALEMBIC_HEAD_REVISION = "20260329_01"


def _stamp_test_schema() -> None:
    if engine.dialect.name == "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS alembic_version (
                    version_num VARCHAR(32) NOT NULL PRIMARY KEY
                )
                """
            )
        )
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": ALEMBIC_HEAD_REVISION},
        )


def _truncate_all_tables() -> None:
    if engine.dialect.name == "sqlite":
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        return

    table_names = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
    if not table_names:
        return

    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session", autouse=True)
def test_database() -> Iterator[None]:
    if engine.dialect.name == "sqlite" and TEST_SQLITE_PATH.exists():
        engine.dispose()
        TEST_SQLITE_PATH.unlink()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _stamp_test_schema()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    pandascore_api._odds_response_cache.clear()
    _truncate_all_tables()
    yield
    pandascore_api._odds_response_cache.clear()
    _truncate_all_tables()


@pytest.fixture(autouse=True)
def isolated_model_artifact_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    model_dir = tmp_path / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ML_MODEL_PATH", str(model_dir))
    yield


@pytest.fixture
def db_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    monkeypatch.setattr(app_main, "_schedule_warm_odds_cache", lambda: None)
    monkeypatch.setattr(pandascore_api, "_manual_refresh_redis_init_attempted", True)
    monkeypatch.setattr(pandascore_api, "_manual_refresh_redis_client", None)
    monkeypatch.setattr(pandascore_api, "_manual_refresh_next_available_local", None)

    app_main.app.dependency_overrides[pandascore_api.require_pandascore_token] = (
        lambda: "test-token"
    )
    yield app_main.app
    app_main.app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": os.environ["ADMIN_API_KEY"]}
