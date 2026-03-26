"""
Recognition API routes.
"""
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from src.recognition.batch import BatchRecognitionService
from src.recognition.cloud.factory import RecognizerFactory
from src.recognition.platform_catalog import build_platforms_response
from src.recognition.protocol import (
    BatchJobStatus,
    BatchRecognizeRequest,
    BatchRecognizeResponse,
    BatchResultResponse,
    HealthResponse,
    ListPlatformsResponse,
    RecognizeRequest,
    RecognizeResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recognition", tags=["recognition"])

batch_service: Optional[BatchRecognitionService] = None
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_batch_service() -> BatchRecognitionService:
    global batch_service
    if batch_service is None:
        batch_service = BatchRecognitionService()
    return batch_service


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> bool:
    if api_key is None:
        return True
    return True


@router.post("/recognize", response_model=RecognizeResponse)
async def recognize(
    request: RecognizeRequest,
    _auth: bool = Depends(verify_api_key),
) -> RecognizeResponse:
    try:
        recognizer = RecognizerFactory.create(request.platform.value)
        return await recognizer.recognize(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Recognition error: {e}")
        raise HTTPException(status_code=500, detail=f"Recognition failed: {str(e)}")


@router.post("/batch", response_model=BatchRecognizeResponse)
async def create_batch(
    request: BatchRecognizeRequest,
    background_tasks: BackgroundTasks,
    _auth: bool = Depends(verify_api_key),
) -> BatchRecognizeResponse:
    service = get_batch_service()

    if not request.images:
        raise HTTPException(status_code=400, detail="No images provided")

    if len(request.images) > 1000:
        raise HTTPException(status_code=400, detail="Max 1000 images per batch")

    response = service.create_batch(request)
    background_tasks.add_task(service.start_batch, response.batch_id)
    return response


@router.post("/batch/{batch_id}/start")
async def start_batch(
    batch_id: str,
    background_tasks: BackgroundTasks,
    _auth: bool = Depends(verify_api_key),
) -> dict:
    service = get_batch_service()
    success = await service.start_batch(batch_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start batch {batch_id}. Check if it exists and is not already processing.",
        )

    return {"status": "started", "batch_id": batch_id}


@router.get("/batch/{batch_id}", response_model=BatchRecognizeResponse)
async def get_batch_status(
    batch_id: str,
    _auth: bool = Depends(verify_api_key),
) -> BatchRecognizeResponse:
    service = get_batch_service()
    status = service.get_status(batch_id)

    if status is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")

    return status


@router.get("/batch/{batch_id}/result", response_model=BatchResultResponse)
async def get_batch_result(
    batch_id: str,
    _auth: bool = Depends(verify_api_key),
) -> BatchResultResponse:
    service = get_batch_service()
    result = service.get_result(batch_id)

    if result is None:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")

    return result


@router.delete("/batch/{batch_id}")
async def cancel_batch(
    batch_id: str,
    _auth: bool = Depends(verify_api_key),
) -> dict:
    service = get_batch_service()
    success = service.cancel_job(batch_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")

    return {"status": "cancelled", "batch_id": batch_id}


@router.get("/batch", response_model=list)
async def list_batches(
    status: Optional[BatchJobStatus] = None,
    limit: int = 20,
    _auth: bool = Depends(verify_api_key),
) -> list:
    service = get_batch_service()
    return service.list_jobs(status=status, limit=limit)


@router.get("/platforms", response_model=ListPlatformsResponse)
async def list_platforms(
    _auth: bool = Depends(verify_api_key),
) -> ListPlatformsResponse:
    return build_platforms_response()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    import torch

    return HealthResponse(
        status="healthy",
        version="2.0.0",
        platform="wingscribe",
        gpu_available=torch.cuda.is_available(),
        gpu_device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        models_loaded=["bioclip"],
    )
