"""
Standalone recognition service.
"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
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

async def health_check(http_request: Request = None) -> HealthResponse:
    import torch

    return HealthResponse(
        status="healthy",
        version="2.0.0",
        platform="recognition-service",
        gpu_available=torch.cuda.is_available(),
        gpu_device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        models_loaded=(http_request.app.state.recognizer_factory if http_request else RecognizerFactory).loaded_local_models(),
    )


async def list_platforms() -> ListPlatformsResponse:
    return build_platforms_response()


async def recognize(request: RecognizeRequest, http_request: Request = None) -> RecognizeResponse:
    try:
        factory = http_request.app.state.recognizer_factory if http_request else RecognizerFactory
        recognizer = factory.create(request.platform.value)
        return await recognizer.recognize(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Recognition error: {e}")
        raise HTTPException(status_code=500, detail=f"Recognition failed: {str(e)}")


def create_app(base_dir: Path = PROJECT_ROOT, *, config_override=None) -> FastAPI:
    from copy import deepcopy
    config = (load_config(str(Path(base_dir) / "config/settings.yaml"),
                          str(Path(base_dir) / "config/secrets.yaml"))
              if config_override is None else deepcopy(config_override))
    @asynccontextmanager
    async def lifespan(application):
        try:
            yield
        finally:
            application.state.recognizer_factory.clear_local_cache()
    application = FastAPI(title="WingScribe Recognition Service", version="2.0.0", lifespan=lifespan)
    application.state.config = config
    application.state.recognizer_factory = RecognizerFactory.configured(config)
    application.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                               allow_methods=["*"], allow_headers=["*"])
    application.get("/health", response_model=HealthResponse)(health_check)
    application.get("/platforms", response_model=ListPlatformsResponse)(list_platforms)
    application.post("/api/recognize", response_model=RecognizeResponse)(recognize)
    return application


if __name__ == "__main__":
    application = create_app()
    config = application.state.config
    host = config.get("web", {}).get("host", "127.0.0.1")
    port = config.get("web", {}).get("port", 8000)
    uvicorn.run(application, host=host, port=port)
