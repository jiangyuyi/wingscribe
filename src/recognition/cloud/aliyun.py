"""
阿里云视觉智能开放平台适配器

支持通过阿里云图像标签识别 API 进行鸟类识别。
使用 REST API 直接调用，避免额外的 SDK 依赖。
"""
import time
import base64
import hashlib
import hmac
import httpx
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode, quote
from datetime import datetime
from ..base import AbstractBirdRecognizer
from ..protocol import RecognizeRequest, RecognizeResponse, RecognitionResult
from ...utils.config_loader import get_config
import logging

logger = logging.getLogger(__name__)


class AliyunRecognizer(AbstractBirdRecognizer):
    """阿里云视觉智能识别器"""

    ENDPOINT = "imagerecog.cn-shanghai.aliyuncs.com"
    API_VERSION = "2019-09-30"
    ACTION = "DetectImageTags"

    def __init__(
        self,
        access_key_id: Optional[str] = None,
        access_key_secret: Optional[str] = None,
        timeout: int = 30
    ):
        """
        初始化阿里云识别器

        Args:
            access_key_id: 阿里云 AccessKey ID
            access_key_secret: 阿里云 AccessKey Secret
            timeout: 请求超时时间（秒）
        """
        self._config = get_config()
        self._access_key_id = access_key_id or self._get_config_value("access_key_id")
        self._access_key_secret = access_key_secret or self._get_config_value("access_key_secret")
        self._timeout = timeout

    def _get_config_value(self, key: str) -> str:
        """获取配置值"""
        secrets = self._config.get("cloud", {}).get("aliyun", {})
        value = secrets.get(key, "")
        if not value:
            raise ValueError(f"Aliyun {key} not configured. Set in cloud.aliyun.{key} in secrets.yaml")
        return value

    @property
    def platform(self) -> str:
        return "aliyun"

    @property
    def is_available(self) -> bool:
        return bool(self._access_key_id and self._access_key_secret)

    def _get_signature(self, params: Dict[str, str]) -> str:
        """计算签名"""
        # 1. 参数排序
        sorted_params = sorted(params.items(), key=lambda x: x[0])
        # 2. 构造待签名字符串
        string_to_sign = "GET&%2F&" + quote(
            urlencode(sorted_params),
            safe=''
        )
        # 3. HMAC-SHA1 签名
        key = f"{self._access_key_secret}&"
        signature = hmac.new(
            key.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            hashlib.sha1
        ).digest()
        return base64.b64encode(signature).decode('utf-8')

    def _build_request_url(self, image_data: bytes) -> str:
        """构建请求 URL"""
        # 公共参数
        params = {
            "AccessKeyId": self._access_key_id,
            "Action": self.ACTION,
            "Format": "JSON",
            "Version": self.API_VERSION,
            "Timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "SignatureNonce": str(int(time.time() * 1000)),
            "ImageURL": f"data:image/jpeg;base64,{base64.b64encode(image_data).decode()}",
        }

        # 计算签名
        params["Signature"] = self._get_signature(params)

        # 构造完整 URL
        query_string = urlencode(params)
        return f"https://{self.ENDPOINT}/?{query_string}"

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

            # 构建请求 URL
            url = self._build_request_url(image_data)

            # 发送请求
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
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
            logger.error(f"Aliyun API error: {error_msg}")
            return self._create_error_response(request, error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Aliyun recognition error: {error_msg}")
            return self._create_error_response(request, error_msg)

    def _parse_raw_results(self, raw: Any, top_k: int) -> List[RecognitionResult]:
        """解析阿里云原始响应"""
        results = []

        # 阿里云返回格式: {"Tag": [{"Value": "...", "Confidence": 95.6}, ...]}
        if isinstance(raw, dict):
            tags = raw.get("Tag", raw.get("data", {}).get("tags", []))
            if isinstance(tags, list):
                for item in tags[:top_k]:
                    if isinstance(item, dict):
                        confidence = item.get("Confidence", item.get("confidence", 0))
                        # 阿里云返回的是百分比，转为 0-1
                        if confidence > 1:
                            confidence = confidence / 100.0
                        results.append(RecognitionResult(
                            label=item.get("Value", item.get("label", "unknown")),
                            confidence=confidence
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
        max_concurrent: int = 3  # 阿里云限流，降低并发
    ) -> List[RecognizeResponse]:
        """批量识别"""
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_limit(req: RecognizeRequest) -> RecognizeResponse:
            async with semaphore:
                return await self.recognize(req)

        tasks = [process_with_limit(req) for req in requests]
        return await asyncio.gather(*tasks)
