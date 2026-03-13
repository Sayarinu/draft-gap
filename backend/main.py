import logging
import os
from typing import Callable

from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
for _name in ("services.pandascore", "api.v1.pandascore"):
    logging.getLogger(_name).setLevel(logging.INFO)

from api.v1.api import api_router
from database import init_db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").strip()
FRONTEND_API_SECRET = (os.getenv("FRONTEND_API_SECRET") or "").strip()
API_KEY_HEADER = "X-Api-Key"
APP_ENV = (
    os.getenv("APP_ENV")
    or os.getenv("ENV")
    or os.getenv("ENVIRONMENT")
    or os.getenv("NODE_ENV")
    or ""
).strip().lower()


def _is_production_runtime(frontend_url: str, app_env: str) -> bool:
    if app_env in {"prod", "production"}:
        return True
    if not frontend_url:
        return False
    lowered = frontend_url.lower()
    return "localhost" not in lowered and "127.0.0.1" not in lowered


IS_PRODUCTION_RUNTIME = _is_production_runtime(FRONTEND_URL, APP_ENV)
if IS_PRODUCTION_RUNTIME and not FRONTEND_API_SECRET:
    raise RuntimeError(
        "FRONTEND_API_SECRET must be set in production to restrict backend access."
    )

app = FastAPI(
    title="ML Fullstack API",
    version="1.0.0",
    docs_url=None if IS_PRODUCTION_RUNTIME else "/docs",
    redoc_url=None if IS_PRODUCTION_RUNTIME else "/redoc",
)

origins = [FRONTEND_URL]

DATA_CACHE_PATHS = (
    "/api/v1/pandascore/lol/upcoming",
    "/api/v1/pandascore/lol/upcoming-with-odds",
    "/api/v1/pandascore/lol/live-with-odds",
)
CACHE_CONTROL_HEADER = "public, max-age=600, s-maxage=900"


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        response = await call_next(request)
        if request.method == "GET" and request.url.path in DATA_CACHE_PATHS:
            response.headers["Cache-Control"] = CACHE_CONTROL_HEADER
        return response


class FrontendKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        if not FRONTEND_API_SECRET:
            return await call_next(request)
        if request.url.path == "/health":
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        if not request.url.path.startswith("/api/v1"):
            return await call_next(request)
        key = (request.headers.get(API_KEY_HEADER) or "").strip()
        if key != FRONTEND_API_SECRET:
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden"},
            )
        return await call_next(request)


app.add_middleware(CacheControlMiddleware)
app.add_middleware(FrontendKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)


@app.on_event("startup")
def on_startup() -> None:
    try:
        init_db()
    except Exception as e:
        logger.warning(
            "startup failed: init_db error_type=%s error=%s",
            type(e).__name__,
            str(e),
            exc_info=True,
        )
    _maybe_bootstrap_data()


def _maybe_bootstrap_data() -> None:
    if os.getenv("BOOTSTRAP_ON_STARTUP", "true").strip().lower() in ("false", "0", "no"):
        return
    try:
        from database import SessionLocal
        from models_ml import MLModelRun

        session = SessionLocal()
        try:
            active = session.query(MLModelRun).filter(MLModelRun.is_active.is_(True)).first()
            if active is not None:
                return
            from tasks import task_refresh_data

            task_refresh_data.delay()
            logger.info("bootstrap: no active model found; triggered task_refresh_data")
        finally:
            session.close()
    except Exception as e:
        logger.warning(
            "bootstrap check failed: error_type=%s error=%s",
            type(e).__name__,
            str(e),
        )


app.include_router(api_router, prefix="/api/v1")


class HealthResponse(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="healthy", version="1.0.0")
