"""
独立识别服务

用于分离部署场景，提供纯 REST API 识别服务。
"""
import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging

# Add project root to path
BASE_DIR = Path(__file__).parent.absolute()
sys.path.append(str(BASE_DIR))

from src.utils.config_loader import load_config
from src.recognition.protocol import (
    RecognizeRequest,
    RecognizeResponse,
    ListPlatformsResponse,
    PlatformInfo,
    HealthResponse,
)
from src.recognition.cloud.factory import RecognizerFactory

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load config
config = load_config(
    str(BASE_DIR / "config" / "settings.yaml"),
    str(BASE_DIR / "config" / "secrets.yaml")
)

app = FastAPI(
    title="WingScribe Recognition Service",
    description="鸟类识别 REST API 服务",
    version="2.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """健康检查"""
    import torch

    return HealthResponse(
        status="healthy",
        version="2.0.0",
        platform="recognition-service",
        gpu_available=torch.cuda.is_available(),
        gpu_device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        models_loaded=["bioclip"]
    )


@app.get("/platforms", response_model=ListPlatformsResponse)
async def list_platforms() -> ListPlatformsResponse:
    """列出可用的识别平台"""
    platforms = [
        PlatformInfo(
            id="local",
            name="本地 BioCLIP",
            description="使用本地部署的 BioCLIP 模型进行识别",
            requires_api_key=False,
            is_cloud=False
        ),
        PlatformInfo(
            id="huggingface",
            name="HuggingFace",
            description="通过 HuggingFace Inference API 调用云端模型",
            requires_api_key=True,
            is_cloud=True,
            max_image_size_mb=10
        ),
        PlatformInfo(
            id="modelscope",
            name="魔搭社区",
            description="通过魔搭社区 API-Inference 调用云端模型",
            requires_api_key=True,
            is_cloud=True
        ),
        PlatformInfo(
            id="dongniao",
            name="懂鸟",
            description="国内专业鸟类识别 API 服务",
            requires_api_key=True,
            is_cloud=True,
            supported_formats=["jpg", "jpeg", "png", "webp"],
            max_image_size_mb=10
        ),
        PlatformInfo(
            id="aliyun",
            name="阿里云视觉智能",
            description="阿里云图像标签识别服务",
            requires_api_key=True,
            is_cloud=True
        ),
        PlatformInfo(
            id="baidu",
            name="百度智能云",
            description="百度云图像识别服务",
            requires_api_key=True,
            is_cloud=True
        ),
    ]

    return ListPlatformsResponse(
        platforms=platforms,
        default_platform="local"
    )


@app.post("/api/recognize", response_model=RecognizeResponse)
async def recognize(request: RecognizeRequest) -> RecognizeResponse:
    """识别单张图片"""
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
