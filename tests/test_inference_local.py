import os
from pathlib import Path
import logging

import pytest
import torch
from PIL import Image

from src.recognition.inference_local import LocalBirdRecognizer


class _FakeModel:
    def __init__(self):
        self.to_calls = []
        self.encode_text_calls = 0

    def to(self, device):
        self.to_calls.append(device)
        return self

    def encode_text(self, batch_tokens):
        self.encode_text_calls += 1
        return batch_tokens.float() + 1

    def encode_image(self, image_input):
        rows = image_input.shape[0]
        return torch.tensor([[3.0, 1.0]] * rows, dtype=torch.float32)


def test_init_sets_hf_mirror_and_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)
    monkeypatch.setattr("src.recognition.inference_local._check_cuda_stable", lambda: False)
    monkeypatch.setattr(LocalBirdRecognizer, "_load_model", lambda self: None)

    recognizer = LocalBirdRecognizer(model_name="bioclip-2", device="auto", hf_mirror="https://mirror.example")

    assert recognizer.device == "cpu"
    assert recognizer.model_id == "hf-hub:imageomics/bioclip-2"
    assert os.environ["HF_ENDPOINT"] == "https://mirror.example"
    assert os.environ["HF_HUB_URL"] == "https://mirror.example"
    assert os.environ["HF_HUB_ENABLE_HF_TRANSFER"] == "1"


def test_get_text_features_uses_cache(monkeypatch):
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer.model = _FakeModel()
    recognizer.cached_labels = None
    recognizer.cached_text_features = None
    recognizer.tokenizer = lambda labels: torch.tensor([[1.0, 0.0], [0.0, 1.0]], dtype=torch.float32)

    first = recognizer._get_text_features(["sparrow", "robin"])
    second = recognizer._get_text_features(["sparrow", "robin"])

    assert recognizer.model.encode_text_calls == 1
    assert first is second


def test_predict_batch_returns_empty_lists_when_no_candidate_labels():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)

    assert recognizer.predict_batch(["a.jpg", "b.jpg"], []) == [[], []]


def test_predict_batch_falls_back_to_cpu_on_cuda_error():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cuda"
    recognizer.model = _FakeModel()
    recognizer.cached_text_features = object()
    calls = {"count": 0}

    def fake_do_predict_batch(image_paths, candidate_labels, top_k):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("CUDA failed")
        return [[{"scientific_name": "sparrow", "confidence": 0.9}]]

    recognizer._do_predict_batch = fake_do_predict_batch

    result = recognizer.predict_batch(["a.jpg"], ["sparrow"])

    assert result == [[{"scientific_name": "sparrow", "confidence": 0.9}]]
    assert recognizer.device == "cpu"
    assert recognizer.model.to_calls == ["cpu"]
    assert recognizer.cached_text_features is None


def test_do_predict_batch_preserves_positions_for_invalid_images(tmp_path: Path):
    valid_path = tmp_path / "valid.jpg"
    Image.new("RGB", (4, 4), color="white").save(valid_path)
    invalid_path = tmp_path / "missing.jpg"

    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer.preprocess = lambda image: torch.tensor([1.0, 0.0], dtype=torch.float32)
    recognizer.model = _FakeModel()
    recognizer._get_text_features = lambda labels: torch.tensor(
        [[1.0, 0.0], [0.0, 1.0]],
        dtype=torch.float32,
    )

    results = recognizer._do_predict_batch(
        [str(valid_path), str(invalid_path)],
        ["sparrow", "robin"],
        top_k=2,
    )

    assert len(results) == 2
    assert results[0][0]["scientific_name"] == "sparrow"
    assert results[1] == []


def test_predict_falls_back_to_cpu_on_cuda_error():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cuda"
    recognizer.model = _FakeModel()
    recognizer.cached_text_features = object()
    calls = {"count": 0}

    def fake_do_predict(image_path, candidate_labels, top_k):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("CUDA bad")
        return [{"scientific_name": "sparrow", "confidence": 0.8}]

    recognizer._do_predict = fake_do_predict

    result = recognizer.predict("bird.jpg", ["sparrow"])

    assert result == [{"scientific_name": "sparrow", "confidence": 0.8}]
    assert recognizer.device == "cpu"
    assert recognizer.model.to_calls == ["cpu"]
    assert recognizer.cached_text_features is None


def test_load_model_restores_logging_levels_after_failure(monkeypatch, tmp_path: Path):
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer.model_type_slug = "bioclip"
    recognizer.model_id = "hf-hub:imageomics/bioclip"

    root_logger = logging.getLogger()
    factory_logger = logging.getLogger("open_clip.factory")
    httpx_logger = logging.getLogger("httpx")
    original_levels = (root_logger.level, factory_logger.level, httpx_logger.level)

    class FakeOpenClip:
        def create_model_and_transforms(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr("src.recognition.inference_local._get_open_clip", lambda: FakeOpenClip())
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="boom"):
        recognizer._load_model()

    assert (root_logger.level, factory_logger.level, httpx_logger.level) == original_levels


def test_do_predict_batch_closes_image_handles(monkeypatch):
    class FakeImage:
        def __init__(self, name):
            self.name = name
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

        def close(self):
            self.closed = True

    opened = []

    def fake_open(path):
        image = FakeImage(path)
        opened.append(image)
        return image

    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer.preprocess = lambda image: torch.tensor([1.0, 0.0], dtype=torch.float32)
    recognizer.model = _FakeModel()
    recognizer._get_text_features = lambda labels: torch.tensor(
        [[1.0, 0.0], [0.0, 1.0]],
        dtype=torch.float32,
    )

    monkeypatch.setattr("src.recognition.inference_local.Image.open", fake_open)

    results = recognizer._do_predict_batch(["a.jpg", "b.jpg"], ["sparrow", "robin"], top_k=1)

    assert len(results) == 2
    assert all(image.closed for image in opened)


def test_do_predict_closes_image_handle(monkeypatch):
    class FakeImage:
        def __init__(self, name):
            self.name = name
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

        def close(self):
            self.closed = True

    opened = []

    def fake_open(path):
        image = FakeImage(path)
        opened.append(image)
        return image

    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer.preprocess = lambda image: torch.tensor([1.0, 0.0], dtype=torch.float32)
    recognizer.model = _FakeModel()
    recognizer._get_text_features = lambda labels: torch.tensor(
        [[1.0, 0.0], [0.0, 1.0]],
        dtype=torch.float32,
    )

    monkeypatch.setattr("src.recognition.inference_local.Image.open", fake_open)

    result = recognizer._do_predict("a.jpg", ["sparrow", "robin"], top_k=1)

    assert result[0]["scientific_name"] == "sparrow"
    assert opened[0].closed is True
