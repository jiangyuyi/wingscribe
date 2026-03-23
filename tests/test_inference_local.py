import os
from pathlib import Path

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
