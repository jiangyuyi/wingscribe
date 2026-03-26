import base64
from pathlib import Path

import pytest

from src.recognition.cloud.aliyun import AliyunRecognizer
from src.recognition.cloud.baidu import BaiduRecognizer
from src.recognition.cloud.huggingface import HuggingFaceRecognizer
from src.recognition.cloud.modelscope import ModelScopeRecognizer
from src.recognition.protocol import RecognitionPlatform, RecognizeRequest


def _recognizer_builders():
    return [
        (
            "huggingface",
            lambda: HuggingFaceRecognizer(
                api_token="token",
                model_id="imageomics/bioclip",
            ),
        ),
        (
            "modelscope",
            lambda: ModelScopeRecognizer(
                api_token="modelscope-token",
                model_id="damo/birds",
            ),
        ),
        (
            "aliyun",
            lambda: AliyunRecognizer(
                access_key_id="ak",
                access_key_secret="secret",
            ),
        ),
        (
            "baidu",
            lambda: BaiduRecognizer(
                api_key="api-key",
                secret_key="secret-key",
            ),
        ),
    ]


@pytest.mark.parametrize(("platform_name", "builder"), _recognizer_builders())
def test_cloud_recognizer_load_image_from_base64(platform_name, builder):
    recognizer = builder()
    payload = b"bird-image"
    request = RecognizeRequest(
        image_base64=base64.b64encode(payload).decode("ascii"),
        platform=RecognitionPlatform(platform_name),
    )

    assert recognizer._load_image(request) == payload


@pytest.mark.parametrize(("platform_name", "builder"), _recognizer_builders())
def test_cloud_recognizer_load_image_from_local_path(platform_name, builder, tmp_path: Path):
    recognizer = builder()
    image_path = tmp_path / f"{platform_name}.jpg"
    image_path.write_bytes(b"local-image")
    request = RecognizeRequest(
        image_path=str(image_path),
        platform=RecognitionPlatform(platform_name),
    )

    assert recognizer._load_image(request) == b"local-image"


@pytest.mark.parametrize(("platform_name", "builder"), _recognizer_builders())
def test_cloud_recognizer_load_image_from_url(platform_name, builder, monkeypatch):
    recognizer = builder()
    captured = {}

    class DummyResponse:
        content = b"remote-image"

        def raise_for_status(self):
            captured["raised"] = True

    def fake_get(url, timeout):
        captured["url"] = url
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("httpx.get", fake_get)

    request = RecognizeRequest(
        image_url="https://example.com/bird.jpg",
        timeout=17,
        platform=RecognitionPlatform(platform_name),
    )

    assert recognizer._load_image(request) == b"remote-image"
    assert captured == {
        "url": "https://example.com/bird.jpg",
        "timeout": 17,
        "raised": True,
    }
