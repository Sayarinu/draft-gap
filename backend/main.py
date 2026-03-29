from __future__ import annotations

import logging
import os
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.v1.api import api_router
from database import validate_runtime_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
for _name in ("services.pandascore", "api.v1.pandascore"):
    logging.getLogger(_name).setLevel(logging.INFO)

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").strip()
APP_ENV = (
    os.getenv("APP_ENV")
    or os.getenv("ENV")
    or os.getenv("ENVIRONMENT")
    or os.getenv("NODE_ENV")
    or ""
).strip().lower()

DATA_CACHE_PATHS = (
    "/api/v1/pandascore/lol/upcoming",
    "/api/v1/pandascore/lol/upcoming-with-odds",
    "/api/v1/pandascore/lol/live-with-odds",
)
CACHE_CONTROL_HEADER = "public, max-age=600, s-maxage=900"


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_production_runtime(app_env: str) -> bool:
    return app_env in {"prod", "production"}


IS_PRODUCTION_RUNTIME = _is_production_runtime(APP_ENV)
ENABLE_API_DOCS = _env_flag("ENABLE_API_DOCS", default=not IS_PRODUCTION_RUNTIME)
WARM_ODDS_CACHE_ON_STARTUP = _env_flag("WARM_ODDS_CACHE_ON_STARTUP", default=False)


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        response = await call_next(request)
        if request.method == "GET" and request.url.path in DATA_CACHE_PATHS:
            response.headers["Cache-Control"] = CACHE_CONTROL_HEADER
        return response


def _schedule_warm_odds_cache() -> None:
    delay_seconds = 15
    try:
        delay_str = os.getenv("ODDS_CACHE_WARM_DELAY_SECONDS", "").strip()
        if delay_str:
            delay_seconds = max(0, int(delay_str))
    except ValueError:
        logger.warning("Invalid ODDS_CACHE_WARM_DELAY_SECONDS=%s", delay_str)

    def _run_warm() -> None:
        if delay_seconds > 0:
            threading.Event().wait(delay_seconds)
        try:
            from api.v1.pandascore import warm_upcoming_odds_cache

            warm_upcoming_odds_cache()
        except Exception as exc:
            logger.warning(
                "warm_odds_cache failed: error_type=%s error=%s",
                type(exc).__name__,
                str(exc),
            )

    threading.Thread(target=_run_warm, daemon=True).start()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_runtime_schema()
    if WARM_ODDS_CACHE_ON_STARTUP:
        _schedule_warm_odds_cache()
    yield


app = FastAPI(
    title="ML Fullstack API",
    version="1.0.0",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    lifespan=lifespan,
)

app.add_middleware(CacheControlMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL] if FRONTEND_URL else [],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-Admin-Key"],
)

app.include_router(api_router, prefix="/api/v1")


class HealthResponse(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="healthy", version="1.0.0")
