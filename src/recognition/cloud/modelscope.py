"""
魔搭社区 (ModelScope) API 适配器

支持通过魔搭社区 API-Inference 调用云端模型进行鸟类识别。
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


class ModelScopeRecognizer(AbstractBirdRecognizer):
    """魔搭社区云端识别器"""

    # 鸟类分类模型
    DEFAULT_MODELS = {
        "birds": "damo/cv_resnet50_image-classification_birds",
        "general": "damo/cv_resnet50_image-classification_general",
    }

    def __init__(
        self,
        api_token: Optional[str] = None,
        model_id: Optional[str] = None,
        timeout: int = 60
    ):
        """
        初始化魔搭识别器

        Args:
            api_token: 魔搭 API Token
            model_id: 模型 ID
            timeout: 请求超时时间（秒）
        """
        self._config = get_config()
        self._api_token = api_token or self._get_api_token()
        self._model_id = model_id or self._get_default_model()
        self._timeout = timeout

    def _get_api_token(self) -> str:
        """获取 API Token"""
        secrets = self._config.get("cloud", {}).get("modelscope", {})
        token = secrets.get("api_token", "")
        if not token:
            raise ValueError("ModelScope API token not configured. Set MODELSCOPE_TOKEN env var or cloud.modelscope.api_token in secrets.yaml")
        return token

    def _get_default_model(self) -> str:
        """获取默认模型"""
        secrets = self._config.get("cloud", {}).get("modelscope", {})
        return secrets.get("model_id", self.DEFAULT_MODELS["birds"])

    @property
    def platform(self) -> str:
        return "modelscope"

    @property
    def is_available(self) -> bool:
        if not self._api_token:
            return False
        # 简单验证 Token 格式
        return len(self._api_token) > 10

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Access-Token": self._api_token,
            "Content-Type": "application/json",
        }

    def _get_endpoint(self) -> str:
        """获取 API 端点"""
        return f"https://api.modelscope.cn/api/v1/models/{self._model_id}"

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
            image_base64 = base64.b64encode(image_data).decode()

            # 构造请求体
            payload = {
                "input": {
                    "image": image_base64
                }
            }

            # 发送请求
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._get_endpoint(),
                    headers=self._get_headers(),
                    json=payload
                )

                if response.status_code == 401:
                    return self._create_error_response(
                        request,
                        "ModelScope API token invalid or expired"
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
            logger.error(f"ModelScope API error: {error_msg}")
            return self._create_error_response(request, error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"ModelScope recognition error: {error_msg}")
            return self._create_error_response(request, error_msg)

    def _parse_raw_results(self, raw: Any, top_k: int) -> List[RecognitionResult]:
        """解析魔搭社区原始响应"""
        results = []

        # ModelScope 图像分类返回格式
        if isinstance(raw, dict):
            output = raw.get("output", raw)
            if isinstance(output, list):
                for item in output[:top_k]:
                    if isinstance(item, dict):
                        results.append(RecognitionResult(
                            label=item.get("label", item.get("class", "unknown")),
                            confidence=item.get("score", item.get("confidence", 0.0))
                        ))
            elif isinstance(output, dict):
                scores = output.get("scores", [])
                labels = output.get("labels", output.get("classes", []))
                for i, (label, score) in enumerate(zip(labels[:top_k], scores[:top_k])):
                    results.append(RecognitionResult(
                        label=label,
                        confidence=float(score) if isinstance(score, (int, float)) else 0.0
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
        """批量识别"""
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_limit(req: RecognizeRequest) -> RecognizeResponse:
            async with semaphore:
                return await self.recognize(req)

        tasks = [process_with_limit(req) for req in requests]
        return await asyncio.gather(*tasks)
