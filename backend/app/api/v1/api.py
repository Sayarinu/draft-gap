from app.api.v1.endpoints import ingest, predict
from fastapi import APIRouter

api_router = APIRouter()
api_router.include_router(predict.router, prefix="/predict", tags=["predictions"])
api_router.include_router(ingest.router, prefix="/ingest", tags=["data"])
