from fastapi import APIRouter, HTTPException
from tasks import ingest_lol_data

router = APIRouter()


@router.post("/ingest", status_code=202)
async def trigger_ingestion(file_name: str = "input.csv"):
    try:
        task = ingest_lol_data.delay(f"/data/{file_name}")
        return {
            "message": "Ingestion task queued",
            "task_id": task.id,
            "file": file_name,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
