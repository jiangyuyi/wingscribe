import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_recognition_service_loads_config_from_project_root(monkeypatch):
    import src.utils.config_loader as config_loader
    import src.recognition_service as recognition_service

    captured = {}

    def fake_load_config(settings_path, secrets_path):
        captured["settings_path"] = settings_path
        captured["secrets_path"] = secrets_path
        return {"web": {"host": "127.0.0.1", "port": 9000}}

    monkeypatch.setattr(config_loader, "load_config", fake_load_config)

    reloaded = importlib.reload(recognition_service)

    try:
        project_root = Path(reloaded.__file__).resolve().parent.parent
        assert captured["settings_path"] == str(project_root / "config" / "settings.yaml")
        assert captured["secrets_path"] == str(project_root / "config" / "secrets.yaml")
        assert reloaded.PROJECT_ROOT == project_root
    finally:
        importlib.reload(reloaded)


def test_health_check_reports_gpu_when_available(monkeypatch):
    import src.recognition_service as recognition_service

    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: True,
            get_device_name=lambda index: "Test GPU",
        )
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    response = asyncio.run(recognition_service.health_check())

    assert response.status == "healthy"
    assert response.platform == "recognition-service"
    assert response.gpu_available is True
    assert response.gpu_device == "Test GPU"


def test_list_platforms_returns_expected_defaults():
    import src.recognition_service as recognition_service

    response = asyncio.run(recognition_service.list_platforms())

    platform_ids = [platform.id for platform in response.platforms]
    assert response.default_platform == "local"
    assert platform_ids == [
        "local",
        "huggingface",
        "modelscope",
        "dongniao",
        "aliyun",
        "baidu",
    ]
    assert response.platforms[0].name == "本地 BioCLIP"
    assert response.platforms[3].supported_formats == ["jpg", "jpeg", "png", "webp"]


def test_recognize_maps_value_error_to_400(monkeypatch):
    import src.recognition_service as recognition_service
    from src.recognition.protocol import RecognizeRequest, RecognitionPlatform

    class FailingFactory:
        @staticmethod
        def create(_platform):
            raise ValueError("bad request")

    monkeypatch.setattr(recognition_service, "RecognizerFactory", FailingFactory)
    request = RecognizeRequest(image_path="bird.jpg", platform=RecognitionPlatform.local)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recognition_service.recognize(request))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "bad request"


def test_recognize_maps_runtime_error_to_503(monkeypatch):
    import src.recognition_service as recognition_service
    from src.recognition.protocol import RecognizeRequest, RecognitionPlatform

    class FailingFactory:
        @staticmethod
        def create(_platform):
            raise RuntimeError("service unavailable")

    monkeypatch.setattr(recognition_service, "RecognizerFactory", FailingFactory)
    request = RecognizeRequest(image_path="bird.jpg", platform=RecognitionPlatform.local)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recognition_service.recognize(request))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "service unavailable"


def test_recognize_returns_recognizer_result(monkeypatch):
    import src.recognition_service as recognition_service
    from src.recognition.protocol import RecognizeRequest, RecognizeResponse, RecognitionPlatform

    expected = RecognizeResponse(
        success=True,
        image_path="bird.jpg",
        results=[],
        platform="local",
        processing_time_ms=12,
    )

    class StubRecognizer:
        async def recognize(self, request):
            assert request.image_path == "bird.jpg"
            return expected

    class StubFactory:
        @staticmethod
        def create(_platform):
            return StubRecognizer()

    monkeypatch.setattr(recognition_service, "RecognizerFactory", StubFactory)
    request = RecognizeRequest(image_path="bird.jpg", platform=RecognitionPlatform.local)

    response = asyncio.run(recognition_service.recognize(request))

    assert response == expected
