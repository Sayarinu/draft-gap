from app.schemas.predict import PredictionRequest, PredictionResponse
from app.tasks import process_data_task
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/", response_model=PredictionResponse)
async def create_prediction(payload: PredictionRequest):
    task = process_data_task.delay(payload.data)
    return {"task_id": task.id, "status": "pending"}
