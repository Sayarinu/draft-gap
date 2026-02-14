import os

from api.v1.api import api_router
from api.v1.ingestion import router as ingest_router
from database import init_db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="ML Fullstack API",
    description="FastAPI backend with Celery/Redis for heavy ML tasks",
    version="1.0.0",
)

origins = [
    os.getenv("FRONTEND_URL", "http://localhost:3000"),
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


app.include_router(api_router, prefix="/api/v1")
app.include_router(ingest_router, prefix="/api/v1", tags=["ingestion"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}
