import asyncio
import base64
import threading
from pathlib import Path

import pytest
from PIL import Image

from src.recognition.local_adapter import LocalRecognitionAdapter
from src.recognition.protocol import RecognizeRequest


@pytest.fixture
def image_path(tmp_path):
    path = tmp_path / "bird.jpg"
    Image.new("RGB", (32, 32), "white").save(path)
    return path


@pytest.mark.parametrize("source", ["path", "base64"])
def test_local_adapter_uses_avilist_and_converts_results(image_path, monkeypatch, source):
    calls = []
    class Backend:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def predict(self, path, labels, top_k):
            assert len(labels) == 11131
            assert "Parus major" in labels
            assert top_k == 2
            assert Path(path).is_file()
            return [{"scientific_name": "Parus major", "confidence": 0.9}]
    monkeypatch.setattr("src.recognition.inference_local.LocalBirdRecognizer", Backend)
    kwargs = ({"image_path": str(image_path)} if source == "path" else
              {"image_base64": base64.b64encode(image_path.read_bytes()).decode()})
    adapter = LocalRecognitionAdapter(device="cpu")
    request = RecognizeRequest(platform="local", top_k=2, **kwargs)
    async def run():
        return await adapter.recognize_batch([request, request])
    responses = asyncio.run(run())
    assert all(response.success for response in responses)
    assert responses[0].results[0].label == "Parus major"
    assert responses[0].results[0].chinese_name
    assert len(calls) == 1


def test_backend_empty_result_is_failure(image_path):
    adapter = LocalRecognitionAdapter()
    adapter._rows = {"Parus major": {"chinese_name": "大山雀"}}
    class Backend:
        def predict(self, *args, **kwargs):
            return []
    adapter._backend = Backend()
    result = asyncio.run(adapter.recognize(RecognizeRequest(platform="local", image_path=str(image_path))))
    assert not result.success
    assert result.error


def test_invalid_image_does_not_load_model(tmp_path, monkeypatch):
    path = tmp_path / "invalid.jpg"
    path.write_bytes(b"invalid")
    monkeypatch.setattr("src.recognition.inference_local.LocalBirdRecognizer", lambda **kw: pytest.fail("Unexpected model loading"))
    result = asyncio.run(LocalRecognitionAdapter().recognize(RecognizeRequest(platform="local", image_path=str(path))))
    assert not result.success


@pytest.mark.parametrize("kwargs", [{}, {"image_path": ""}, {"image_path": "a", "image_url": "b"}])
def test_exactly_one_image_source_required(kwargs):
    with pytest.raises(ValueError, match="exactly one"):
        RecognizeRequest(platform="local", **kwargs)


def test_sync_inference_does_not_block_event_loop(image_path):
    adapter = LocalRecognitionAdapter()
    adapter._rows = {"Parus major": {"chinese_name": "大山雀"}}
    release = threading.Event()
    entered = threading.Event()
    class Backend:
        def predict(self, *args, **kwargs):
            entered.set()
            assert release.wait(5)
            return [{"scientific_name": "Parus major", "confidence": 0.9}]
    adapter._backend = Backend()
    async def run():
        task = asyncio.create_task(adapter.recognize(RecognizeRequest(platform="local", image_path=str(image_path))))
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set()
        finally:
            release.set()
        return await task
    assert asyncio.run(run()).success


def test_unverified_dongniao_fails_explicitly():
    from src.recognition.cloud.factory import RecognizerFactory
    with pytest.raises(RuntimeError, match="尚未验收"):
        RecognizerFactory.create("dongniao")


def test_real_http_local_route_uses_factory_adapter(image_path, monkeypatch):
    from fastapi.testclient import TestClient
    from src.recognition.cloud.factory import RecognizerFactory
    from src.recognition_service import app
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(RecognizerFactory, "_local_instances", {})
    monkeypatch.setattr("src.recognition.cloud.factory.get_config", lambda: {})
    class Backend:
        def __init__(self, **kwargs):
            assert kwargs["model_name"] == "bioclip-2"
        def predict(self, path, labels, top_k):
            return [{"scientific_name": "Parus major", "confidence": 0.9}]
    monkeypatch.setattr("src.recognition.inference_local.LocalBirdRecognizer", Backend)
    with TestClient(app) as client:
        assert client.get("/health").json()["models_loaded"] == []
        result = client.post("/api/recognize", json={"platform": "local", "image_path": str(image_path)})
        assert result.status_code == 200
        assert result.json()["success"] is True
        assert result.json()["results"][0]["scientific_name"] == "Parus major"
        assert client.get("/health").json()["models_loaded"] == ["bioclip-2"]
        assert client.post("/api/recognize", json={"platform": "local"}).status_code == 422


def test_expired_queued_work_does_not_start_model(image_path, monkeypatch):
    import time
    adapter = LocalRecognitionAdapter()
    monkeypatch.setattr("src.recognition.inference_local.LocalBirdRecognizer", lambda **kw: pytest.fail("Must not load model"))
    with pytest.raises(TimeoutError):
        adapter._predict(RecognizeRequest(platform="local", image_path=str(image_path)), time.monotonic() - 1)
