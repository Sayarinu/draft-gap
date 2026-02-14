from api.v1 import ingestion
from fastapi import APIRouter

api_router = APIRouter()
api_router.include_router(ingestion.router, tags=["ingestion"])
