"""
百度智能云适配器

支持通过百度云图像识别 API 进行鸟类识别。
"""
import time
import base64
import httpx
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode
from datetime import datetime
from ..base import AbstractBirdRecognizer
from ..protocol import RecognizeRequest, RecognizeResponse, RecognitionResult
from ...utils.config_loader import get_config
import logging

logger = logging.getLogger(__name__)


class BaiduRecognizer(AbstractBirdRecognizer):
    """百度云视觉智能识别器"""

    # API 端点
    TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    BASE_URL = "https://aip.baidubce.com/rest/2.0/image-classify/v2"

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        timeout: int = 30
    ):
        """
        初始化百度云识别器

        Args:
            api_key: 百度云 API Key
            secret_key: 百度云 Secret Key
            timeout: 请求超时时间（秒）
        """
        self._config = get_config()
        self._api_key = api_key or self._get_config_value("api_key")
        self._secret_key = secret_key or self._get_config_value("secret_key")
        self._timeout = timeout
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    def _get_config_value(self, key: str) -> str:
        """获取配置值"""
        secrets = self._config.get("cloud", {}).get("baidu", {})
        value = secrets.get(key, "")
        if not value:
            raise ValueError(f"Baidu {key} not configured. Set in cloud.baidu.{key} in secrets.yaml")
        return value

    @property
    def platform(self) -> str:
        return "baidu"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key and self._secret_key)

    async def _get_access_token(self) -> str:
        """获取 access token（带缓存）"""
        # 检查缓存是否有效
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        # 请求新的 token
        params = {
            "grant_type": "client_credentials",
            "client_id": self._api_key,
            "client_secret": self._secret_key
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self.TOKEN_URL, data=params)
            response.raise_for_status()
            result = response.json()

        if "access_token" in result:
            self._access_token = result["access_token"]
            # 百度 token 有效期 30 天，设置 29 天过期
            self._token_expires_at = time.time() + 29 * 24 * 3600
            return self._access_token
        else:
            raise ValueError(f"Failed to get access token: {result}")

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

            # 获取 access token
            access_token = await self._get_access_token()

            # 构造请求
            url = f"{self.BASE_URL}/advanced_general?access_token={access_token}"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            data = {
                "image": image_base64,
                "baike_num": 0  # 不需要百科信息
            }

            # 发送请求
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, headers=headers, data=data)
                response.raise_for_status()
                raw_results = response.json()

            # 检查错误
            if "error_code" in raw_results:
                error_msg = f"Baidu API Error: {raw_results.get('error_msg', raw_results.get('error_code'))}"
                logger.error(error_msg)
                return self._create_error_response(request, error_msg)

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
            logger.error(f"Baidu API error: {error_msg}")
            return self._create_error_response(request, error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Baidu recognition error: {error_msg}")
            return self._create_error_response(request, error_msg)

    def _parse_raw_results(self, raw: Any, top_k: int) -> List[RecognitionResult]:
        """解析百度云原始响应"""
        results = []

        # 百度返回格式: {"result": [{"keyword": "...", "score": 0.95}, ...]}
        if isinstance(raw, dict):
            result_list = raw.get("result", raw.get("result_list", []))
            if isinstance(result_list, list):
                for item in result_list[:top_k]:
                    if isinstance(item, dict):
                        results.append(RecognitionResult(
                            label=item.get("keyword", item.get("label", "unknown")),
                            confidence=item.get("score", item.get("confidence", 0.0))
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
