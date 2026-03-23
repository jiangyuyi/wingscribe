import base64
from pathlib import Path

from src.recognition.inference_api import APIBirdRecognizer


def test_predict_returns_empty_when_candidate_labels_missing(tmp_path: Path):
    image_path = tmp_path / "bird.jpg"
    image_path.write_bytes(b"image")
    recognizer = APIBirdRecognizer("https://example.com/api", "secret")

    assert recognizer.predict(str(image_path), []) == []


def test_predict_returns_empty_when_http_status_not_200(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "bird.jpg"
    image_path.write_bytes(b"image")
    recognizer = APIBirdRecognizer("https://example.com/api", "secret")

    class StubResponse:
        status_code = 500
        text = "server error"

        def json(self):
            raise AssertionError("json should not be read on HTTP failure")

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: StubResponse())

    assert recognizer.predict(str(image_path), ["sparrow"]) == []


def test_predict_returns_empty_for_non_list_payload(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "bird.jpg"
    image_path.write_bytes(b"image")
    recognizer = APIBirdRecognizer("https://example.com/api", "secret")

    class StubResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return {"unexpected": True}

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: StubResponse())

    assert recognizer.predict(str(image_path), ["sparrow"]) == []


def test_predict_posts_base64_payload_and_truncates_to_top_k(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "bird.jpg"
    image_data = b"bird-image"
    image_path.write_bytes(image_data)
    recognizer = APIBirdRecognizer("https://example.com/api", "secret")
    captured = {}

    class StubResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return [
                {"label": "Species A", "score": 0.91},
                {"label": "Species B", "score": 0.82},
                {"label": "Species C", "score": 0.73},
            ]

    def fake_post(url, headers, json):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return StubResponse()

    monkeypatch.setattr("requests.post", fake_post)

    results = recognizer.predict(str(image_path), ["Species A", "Species B"], top_k=2)

    assert captured == {
        "url": "https://example.com/api",
        "headers": {"Authorization": "Bearer secret"},
        "json": {
            "inputs": base64.b64encode(image_data).decode("utf-8"),
            "parameters": {"candidate_labels": ["Species A", "Species B"]},
        },
    }
    assert results == [
        {"scientific_name": "Species A", "confidence": 0.91},
        {"scientific_name": "Species B", "confidence": 0.82},
    ]


def test_predict_returns_empty_on_request_exception(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "bird.jpg"
    image_path.write_bytes(b"image")
    recognizer = APIBirdRecognizer("https://example.com/api", "secret")

    def fake_post(*args, **kwargs):
        raise RuntimeError("network failed")

    monkeypatch.setattr("requests.post", fake_post)

    assert recognizer.predict(str(image_path), ["sparrow"]) == []
