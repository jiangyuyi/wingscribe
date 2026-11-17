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
from .region_filter import DEFAULT_CHINA, DEFAULT_FOREIGN, RegionSelector, RegionFilterError

logger = logging.getLogger(__name__)


class LocalRecognitionAdapter(AbstractBirdRecognizer):
    def __init__(self, *, model_name="bioclip-2", device="auto", hf_mirror=None,
                 catalogue_path=DEFAULT_CATALOGUE, china_path=DEFAULT_CHINA, foreign_path=DEFAULT_FOREIGN):
        self.model_options = dict(model_name=model_name, device=device, hf_mirror=hf_mirror)
        self.catalogue_path = Path(catalogue_path)
        self._backend = None
        self._rows = None
        self._lock = threading.Lock()
        self.china_path = china_path
        self.foreign_path = foreign_path
        self._region_selector = None

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
                rows, manifest = load_catalogue(self.catalogue_path)
                self._rows = {row["scientific_name"]: row for row in rows}
                self._region_selector = RegionSelector(self._rows, manifest['version'],
                    catalogue_path=self.catalogue_path, china_path=self.china_path, foreign_path=self.foreign_path)
            if self._region_selector is None:
                # Also support explicitly injected test backends without loading weights.
                self._region_selector = RegionSelector(self._rows, 'unversioned',
                    catalogue_path=self.catalogue_path, china_path=self.china_path, foreign_path=self.foreign_path)
            selection = self._region_selector.select(request.region_filter, request.location_tag)
            logger.info('Regional candidates: %s', selection.metadata)
            if self._backend is None:
                from .inference_local import LocalBirdRecognizer
                self._backend = LocalBirdRecognizer(**self.model_options)
            if time.monotonic() >= deadline:
                raise TimeoutError("Request expired while loading model")
            predictions = self._backend.predict(str(image_path), list(selection.labels), top_k=request.top_k)
            if not predictions:
                raise RuntimeError("本地模型未返回识别结果，请检查模型和运行日志")
            results = []
            for item in predictions[:request.top_k]:
                name = item["scientific_name"]
                if name not in selection.labels:
                    raise ValueError("模型返回了候选名录以外的名称")
                results.append(RecognitionResult(
                    label=name, scientific_name=name, source_label=name,
                    chinese_name=self._rows[name]["chinese_name"], confidence=item["confidence"],
                ))
            return results, selection.metadata

    async def recognize(self, request: RecognizeRequest) -> RecognizeResponse:
        started = time.monotonic()
        try:
            results, region = await asyncio.wait_for(asyncio.to_thread(self._predict, request, started + request.timeout), request.timeout)
            return RecognizeResponse(success=True, image_path=request.image_path,
                                     platform=self.platform, results=results,
                                     region_selection=region,
                                     processing_time_ms=int((time.monotonic() - started) * 1000))
        except asyncio.TimeoutError:
            return self._create_error_response(request, "本地识别等待超时；已开始的模型运算将在后台结束")
        except RegionFilterError as exc:
            return self._create_error_response(request, str(exc))
        except Exception as exc:
            logger.warning("Local recognition failed (%s)", type(exc).__name__)
            return self._create_error_response(request, "本地识别失败，请检查图片、模型文件和候选名录")
