import logging
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import require_admin_api_key
from api.ingestion_paths import resolved_csv_path_under_data
from tasks import ingest_lol_data

router = APIRouter()
logger = logging.getLogger(__name__)


class IngestTriggerResponse(BaseModel):
    message: str
    task_id: str
    file: str


@router.post("/ingest", status_code=202, response_model=IngestTriggerResponse)
async def trigger_ingestion(
    _: Annotated[None, Depends(require_admin_api_key)],
    file_name: str = "input.csv",
) -> IngestTriggerResponse:
    safe_path = resolved_csv_path_under_data(file_name)
    try:
        task = ingest_lol_data.delay(safe_path)
        return IngestTriggerResponse(
            message="Ingestion task queued",
            task_id=task.id,
            file=PurePosixPath(safe_path).name,
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
