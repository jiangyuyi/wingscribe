"""
Standalone recognition service.
"""
import logging
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.recognition.cloud.factory import RecognizerFactory
from src.recognition.platform_catalog import build_platforms_response
from src.recognition.protocol import (
    HealthResponse,
    ListPlatformsResponse,
    RecognizeRequest,
    RecognizeResponse,
)
from src.utils.config_loader import load_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load config
config = load_config(
    str(PROJECT_ROOT / "config" / "settings.yaml"),
    str(PROJECT_ROOT / "config" / "secrets.yaml"),
)

app = FastAPI(
    title="WingScribe Recognition Service",
    description="Bird recognition REST API service",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    import torch

    return HealthResponse(
        status="healthy",
        version="2.0.0",
        platform="recognition-service",
        gpu_available=torch.cuda.is_available(),
        gpu_device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        models_loaded=["bioclip"],
    )


@app.get("/platforms", response_model=ListPlatformsResponse)
async def list_platforms() -> ListPlatformsResponse:
    return build_platforms_response()


@app.post("/api/recognize", response_model=RecognizeResponse)
async def recognize(request: RecognizeRequest) -> RecognizeResponse:
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


if __name__ == "__main__":
    host = config.get("web", {}).get("host", "0.0.0.0")
    port = config.get("web", {}).get("port", 8000)

    logger.info(f"Starting Recognition Service on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
