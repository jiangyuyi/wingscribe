import asyncio
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from src.recognition.protocol import (
    BatchJobStatus,
    BatchRecognizeRequest,
    BatchRecognizeResponse,
    RecognizeRequest,
    RecognizeResponse,
    RecognitionPlatform,
)
from src.web.routes import recognition


def test_recognize_maps_value_error_to_400(monkeypatch):
    class FailingFactory:
        @staticmethod
        def create(_platform):
            raise ValueError("bad request")

    monkeypatch.setattr(recognition, "RecognizerFactory", FailingFactory)

    request = RecognizeRequest(image_path="bird.jpg", platform=RecognitionPlatform.local)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recognition.recognize(request))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "bad request"


def test_recognize_maps_runtime_error_to_503(monkeypatch):
    class FailingFactory:
        @staticmethod
        def create(_platform):
            raise RuntimeError("service unavailable")

    monkeypatch.setattr(recognition, "RecognizerFactory", FailingFactory)

    request = RecognizeRequest(image_path="bird.jpg", platform=RecognitionPlatform.local)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recognition.recognize(request))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "service unavailable"


def test_create_batch_rejects_empty_images(monkeypatch):
    monkeypatch.setattr(recognition, "get_batch_service", lambda: SimpleNamespace())
    request = BatchRecognizeRequest.model_construct(images=[], webhook_url=None, notify_email=None, batch_id=None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recognition.create_batch(request, BackgroundTasks()))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "No images provided"


def test_create_batch_rejects_more_than_1000_images(monkeypatch):
    monkeypatch.setattr(recognition, "get_batch_service", lambda: SimpleNamespace())
    image_request = RecognizeRequest(image_path="bird.jpg", platform=RecognitionPlatform.local)
    request = BatchRecognizeRequest.model_construct(
        images=[image_request] * 1001,
        webhook_url=None,
        notify_email=None,
        batch_id=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recognition.create_batch(request, BackgroundTasks()))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Max 1000 images per batch"


def test_create_batch_schedules_background_start(monkeypatch):
    created_requests = []

    class StubBatchService:
        def create_batch(self, request):
            created_requests.append(request)
            return BatchRecognizeResponse(
                batch_id="batch_123",
                total=len(request.images),
                completed=0,
                failed=0,
                status=BatchJobStatus.pending,
                progress_percent=0.0,
                webhook_url=request.webhook_url,
            )

        async def start_batch(self, batch_id):
            return True

    service = StubBatchService()
    monkeypatch.setattr(recognition, "get_batch_service", lambda: service)

    request = BatchRecognizeRequest(
        images=[RecognizeRequest(image_path="bird.jpg", platform=RecognitionPlatform.local)],
        webhook_url="https://example.com/webhook",
    )
    background_tasks = BackgroundTasks()

    response = asyncio.run(recognition.create_batch(request, background_tasks))

    assert response.batch_id == "batch_123"
    assert created_requests == [request]
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func == service.start_batch
    assert task.args == ("batch_123",)


def test_list_platforms_uses_shared_catalog():
    response = asyncio.run(recognition.list_platforms())

    assert response.default_platform == "local"
    assert [platform.id for platform in response.platforms] == [
        "local",
        "huggingface",
        "modelscope",
        "dongniao",
        "aliyun",
        "baidu",
    ]
    assert response.platforms[0].name == "本地 BioCLIP"
    assert response.platforms[4].name == "阿里云视觉智能"
