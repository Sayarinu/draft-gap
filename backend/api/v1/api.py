from api.v1 import admin, betting, ingestion, ml, pandascore, rankings
from fastapi import APIRouter

api_router = APIRouter()
api_router.include_router(ingestion.router)
api_router.include_router(ml.router)
api_router.include_router(pandascore.router)
api_router.include_router(admin.router)
api_router.include_router(betting.router)
api_router.include_router(rankings.router)
