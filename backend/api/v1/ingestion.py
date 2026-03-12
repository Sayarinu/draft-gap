import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from tasks import ingest_lol_data

router = APIRouter()
logger = logging.getLogger(__name__)


class IngestTriggerResponse(BaseModel):
    message: str
    task_id: str
    file: str


@router.post("/ingest", status_code=202, response_model=IngestTriggerResponse)
async def trigger_ingestion(file_name: str = "input.csv") -> IngestTriggerResponse:
    try:
        task = ingest_lol_data.delay(f"/data/{file_name}")
        return IngestTriggerResponse(
            message="Ingestion task queued",
            task_id=task.id,
            file=file_name,
        )
    except Exception as e:
        logger.error(
            "ingestion.trigger_ingestion failed: endpoint=POST /ingest file_name=%s error_type=%s error=%s",
            file_name,
            type(e).__name__,
            str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e)) from e
