"""
HuggingFace Inference API 适配器

支持通过 HuggingFace Inference API 调用云端模型进行鸟类识别。
"""
import time
import base64
import httpx
from pathlib import Path
from typing import List, Dict, Any, Optional
from ..base import AbstractBirdRecognizer
from ..protocol import RecognizeRequest, RecognizeResponse, RecognitionResult
from ...utils.config_loader import get_config
import logging

logger = logging.getLogger(__name__)


class HuggingFaceRecognizer(AbstractBirdRecognizer):
    """HuggingFace 云端识别器"""

    ENDPOINT_TEMPLATE = "https://api-inference.huggingface.co/models/{model_id}"

    # 默认鸟类分类模型
    DEFAULT_MODELS = {
        "bioclip": "hf-hub:imageomics/bioclip",
        "resnet50": "microsoft/resnet-50",
        "vit": "google/vit-base-patch16-224",
    }

    def __init__(
        self,
        api_token: Optional[str] = None,
        model_id: Optional[str] = None,
        timeout: int = 60
    ):
        """
        初始化 HuggingFace 识别器

        Args:
            api_token: HuggingFace API Token
            model_id: 模型 ID，不提供则使用默认模型
            timeout: 请求超时时间（秒）
        """
        self._config = get_config()
        self._api_token = api_token or self._get_api_token()
        self._model_id = model_id or self._get_default_model()
        self._timeout = timeout
        self._client: Optional[httpx.Client] = None

    def _get_api_token(self) -> str:
        """获取 API Token"""
        secrets = self._config.get("cloud", {}).get("huggingface", {})
        token = secrets.get("api_token", "")
        if not token:
            raise ValueError("HuggingFace API token not configured. Set HF_TOKEN env var or cloud.huggingface.api_token in secrets.yaml")
        return token

    def _get_default_model(self) -> str:
        """获取默认模型"""
        secrets = self._config.get("cloud", {}).get("huggingface", {})
        return secrets.get("model_id", self.DEFAULT_MODELS["bioclip"])

    @property
    def platform(self) -> str:
        return "huggingface"

    @property
    def is_available(self) -> bool:
        """检查 API Token 是否有效"""
        if not self._api_token:
            return False
        # 尝试获取模型信息来验证 Token
        try:
            url = f"https://api-inference.huggingface.co/status/{self._model_id}"
            response = httpx.get(url, headers=self._get_headers(), timeout=5)
            return response.status_code in [200, 403]  # 403 表示存在但需要认证
        except Exception:
            return False

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

    def _get_endpoint(self) -> str:
        """获取 API 端点"""
        return self.ENDPOINT_TEMPLATE.format(model_id=self._model_id)

    def _load_image(self, request: RecognizeRequest) -> bytes:
        """加载图片数据"""
        if request.image_base64:
            return base64.b64decode(request.image_base64)
        elif request.image_url:
            response = httpx.get(request.image_url, timeout=request.timeout)
            response.raise_for_status()
            return response.content
        elif request.image_path:
            return Path(request.image_path).read_bytes()
        else:
            raise ValueError("No image source provided")

    async def recognize(self, request: RecognizeRequest) -> RecognizeResponse:
        """识别单张图片"""
        start_time = time.time()

        try:
            # 加载图片
            image_data = self._load_image(request)

            # 发送请求
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._get_endpoint(),
                    headers=self._get_headers(),
                    content=image_data,  # 直接发送二进制数据
                )

                if response.status_code == 401:
                    return self._create_error_response(
                        request,
                        "HuggingFace API token invalid or expired"
                    )

                response.raise_for_status()
                raw_results = response.json()

            # 解析结果
            results = self._parse_raw_results(raw_results, request.top_k)
            processing_time_ms = int((time.time() - start_time) * 1000)

            return RecognizeResponse(
                success=True,
                image_path=request.image_path,
                image_url=request.image_url,
                results=results,
                platform=self.platform,
                processing_time_ms=processing_time_ms
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP Error: {e.response.status_code} - {e.response.text[:200]}"
            logger.error(f"HuggingFace API error: {error_msg}")
            return self._create_error_response(request, error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"HuggingFace recognition error: {error_msg}")
            return self._create_error_response(request, error_msg)

    def _parse_raw_results(self, raw: Any, top_k: int) -> List[RecognitionResult]:
        """解析 HuggingFace 原始响应"""
        results = []

        # HuggingFace 图像分类返回格式: [{"label": "...", "score": 0.xx}, ...]
        if isinstance(raw, list):
            for item in raw[:top_k]:
                results.append(RecognitionResult(
                    label=item.get("label", "unknown"),
                    confidence=item.get("score", 0.0)
                ))
        # 其他可能的格式
        elif isinstance(raw, dict):
            if "predictions" in raw:
                for item in raw["predictions"][:top_k]:
                    results.append(RecognitionResult(
                        label=item.get("class", "unknown"),
                        confidence=item.get("score", 0.0)
                    ))

        return results

    def _create_error_response(self, request: RecognizeRequest, error: str) -> RecognizeResponse:
        return RecognizeResponse(
            success=False,
            image_path=request.image_path,
            image_url=request.image_url,
            results=[],
            platform=self.platform,
            processing_time_ms=0,
            error=error
        )

    async def recognize_batch(
        self,
        requests: List[RecognizeRequest],
        max_concurrent: int = 5
    ) -> List[RecognizeResponse]:
        """批量识别（使用并发加速）"""
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_limit(req: RecognizeRequest) -> RecognizeResponse:
            async with semaphore:
                return await self.recognize(req)

        tasks = [process_with_limit(req) for req in requests]
        return await asyncio.gather(*tasks)
