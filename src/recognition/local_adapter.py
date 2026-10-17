"""Async API boundary for the synchronous local inference engine."""
import asyncio
import base64
import logging
import tempfile
import threading
import time
from pathlib import Path

from .base import AbstractBirdRecognizer
from .protocol import RecognizeRequest, RecognizeResponse, RecognitionResult
from ..metadata.avilist import DEFAULT_CATALOGUE, load_catalogue

logger = logging.getLogger(__name__)


class LocalRecognitionAdapter(AbstractBirdRecognizer):
    def __init__(self, *, model_name="bioclip-2", device="auto", hf_mirror=None,
                 catalogue_path=DEFAULT_CATALOGUE):
        self.model_options = dict(model_name=model_name, device=device, hf_mirror=hf_mirror)
        self.catalogue_path = Path(catalogue_path)
        self._backend = None
        self._rows = None
        self._lock = threading.Lock()

    @property
    def platform(self) -> str:
        return "local"

    @property
    def is_available(self) -> bool:
        # Readiness is proven only by inference; this does not download/load weights.
        return self.catalogue_path.is_file()

    def _predict(self, request: RecognizeRequest, deadline: float):
        # Keep the lock and temporary input alive even if the async caller times out.
        with self._lock, tempfile.TemporaryDirectory(prefix="wingscribe-recognition-") as temporary:
            if time.monotonic() >= deadline:
                raise TimeoutError("Request expired while queued")
            if request.image_url:
                raise ValueError("本地识别暂不支持 URL，请提供本地文件或 Base64 图片")
            if request.image_base64:
                image_path = Path(temporary) / "input.jpg"
                image_path.write_bytes(base64.b64decode(request.image_base64, validate=True))
            else:
                image_path = Path(request.image_path)
            from PIL import Image
            with Image.open(image_path) as image:
                image.verify()
            if self._rows is None:
                rows, _ = load_catalogue(self.catalogue_path)
                self._rows = {row["scientific_name"]: row for row in rows}
            if request.region_filter in ("china", "auto"):
                logger.warning("API regional filtering is not verified for AviList; using full catalogue")
            if self._backend is None:
                from .inference_local import LocalBirdRecognizer
                self._backend = LocalBirdRecognizer(**self.model_options)
            if time.monotonic() >= deadline:
                raise TimeoutError("Request expired while loading model")
            predictions = self._backend.predict(str(image_path), list(self._rows), top_k=request.top_k)
            if not predictions:
                raise RuntimeError("本地模型未返回识别结果，请检查模型和运行日志")
            results = []
            for item in predictions[:request.top_k]:
                name = item["scientific_name"]
                if name not in self._rows:
                    raise ValueError("模型返回了候选名录以外的名称")
                results.append(RecognitionResult(
                    label=name, scientific_name=name, source_label=name,
                    chinese_name=self._rows[name]["chinese_name"], confidence=item["confidence"],
                ))
            return results

    async def recognize(self, request: RecognizeRequest) -> RecognizeResponse:
        started = time.monotonic()
        try:
            results = await asyncio.wait_for(asyncio.to_thread(self._predict, request, started + request.timeout), request.timeout)
            return RecognizeResponse(success=True, image_path=request.image_path,
                                     platform=self.platform, results=results,
                                     processing_time_ms=int((time.monotonic() - started) * 1000))
        except asyncio.TimeoutError:
            return self._create_error_response(request, "本地识别等待超时；已开始的模型运算将在后台结束")
        except Exception as exc:
            logger.warning("Local recognition failed (%s)", type(exc).__name__)
            return self._create_error_response(request, "本地识别失败，请检查图片、模型文件和候选名录")
