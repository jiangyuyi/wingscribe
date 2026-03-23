from pathlib import Path

from src.recognition.inference_dongniao import DongniaoRecognizer


def test_predict_returns_empty_without_api_key(tmp_path: Path):
    image_path = tmp_path / "bird.jpg"
    image_path.write_bytes(b"image")
    recognizer = DongniaoRecognizer.__new__(DongniaoRecognizer)
    recognizer.api_key = ""
    recognizer.api_url = "https://example.com/api"
    recognizer.did = "device-id"

    assert recognizer.predict(str(image_path)) == []


def test_upload_image_accepts_flat_list_response(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "bird.jpg"
    image_path.write_bytes(b"image")
    recognizer = DongniaoRecognizer("secret", "https://example.com/api")

    class StubResponse:
        text = "ok"

        def json(self):
            return [1000, "rec-123"]

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: StubResponse())

    assert recognizer._upload_image(str(image_path)) == "rec-123"


def test_upload_image_accepts_dict_response(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "bird.jpg"
    image_path.write_bytes(b"image")
    recognizer = DongniaoRecognizer("secret", "https://example.com/api")

    class StubResponse:
        text = "ok"

        def json(self):
            return {"status": "1000", "data": {"recognitionId": "rec-456"}}

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: StubResponse())

    assert recognizer._upload_image(str(image_path)) == "rec-456"


def test_poll_result_retries_until_success(monkeypatch):
    recognizer = DongniaoRecognizer("secret", "https://example.com/api")
    responses = iter(
        [
            {"status": "1001", "data": None},
            {"status": "1000", "data": [{"list": [[98.5, "中文|English|Sci name", 1, "B"]]}]},
        ]
    )

    class StubResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: StubResponse(next(responses)))

    result = recognizer._poll_result("rec-123", max_retries=2, interval=0)

    assert result == [{"list": [[98.5, "中文|English|Sci name", 1, "B"]]}]


def test_poll_result_returns_none_for_no_animal(monkeypatch):
    recognizer = DongniaoRecognizer("secret", "https://example.com/api")

    class StubResponse:
        status_code = 200

        def json(self):
            return {"status": "1008", "data": None}

    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: StubResponse())

    assert recognizer._poll_result("rec-123", max_retries=1, interval=0) is None


def test_parse_result_extracts_scientific_name_and_confidence():
    recognizer = DongniaoRecognizer.__new__(DongniaoRecognizer)

    results = recognizer._parse_result(
        [{"list": [[98.5, "中文名|English name|Sci name", 1, "B"]]}],
        top_k=1,
    )

    assert results == [{"scientific_name": "Sci name", "confidence": 0.985}]


def test_predict_batch_processes_each_image(tmp_path: Path, monkeypatch):
    recognizer = DongniaoRecognizer("secret", "https://example.com/api")
    image_a = tmp_path / "a.jpg"
    image_b = tmp_path / "b.jpg"
    image_a.write_bytes(b"a")
    image_b.write_bytes(b"b")

    monkeypatch.setattr(
        recognizer,
        "predict",
        lambda image_path, candidate_labels=None, top_k=5: [{"scientific_name": Path(image_path).stem, "confidence": 0.9}],
    )

    assert recognizer.predict_batch(
        [str(image_a), str(image_b)],
        candidate_labels=["ignored"],
        top_k=3,
    ) == [
        [{"scientific_name": "a", "confidence": 0.9}],
        [{"scientific_name": "b", "confidence": 0.9}],
    ]


def test_predict_runs_upload_poll_and_parse(tmp_path: Path, monkeypatch):
    image_path = tmp_path / "bird.jpg"
    image_path.write_bytes(b"image")
    recognizer = DongniaoRecognizer("secret", "https://example.com/api")

    monkeypatch.setattr(recognizer, "_upload_image", lambda path: "rec-123")
    monkeypatch.setattr(recognizer, "_poll_result", lambda rec_id: [{"list": [[88.0, "中文|English|Sci", 1, "B"]]}])
    monkeypatch.setattr(recognizer, "_parse_result", lambda data, top_k: [{"scientific_name": "Sci", "confidence": 0.88}])

    assert recognizer.predict(str(image_path), candidate_labels=["ignored"], top_k=2) == [
        {"scientific_name": "Sci", "confidence": 0.88}
    ]
