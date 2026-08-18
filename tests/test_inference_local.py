import os
import threading
import time
from pathlib import Path
import logging

import pytest
import torch
from PIL import Image

from src.recognition.inference_local import LocalBirdRecognizer
from src.recognition.model_registry import get_model_spec


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


def test_init_rejects_unknown_model_before_loading(monkeypatch):
    monkeypatch.setattr(LocalBirdRecognizer, "_load_model", pytest.fail)

    with pytest.raises(ValueError, match="Unsupported local recognition model"):
        LocalBirdRecognizer(model_name="bioclip-typo", device="cpu")


def test_init_marks_bioclip_25_as_experimental(monkeypatch, caplog):
    monkeypatch.setattr(LocalBirdRecognizer, "_load_model", lambda self: None)

    recognizer = LocalBirdRecognizer(model_name="bioclip-2.5-vith14", device="cpu")

    assert recognizer.model_id == "hf-hub:imageomics/bioclip-2.5-vith14"
    assert recognizer.model_spec.architecture == "ViT-H-14"
    assert "experimental" in caplog.text


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


def test_get_text_features_serializes_concurrent_cache_misses():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer.model = _FakeModel()
    recognizer.cached_labels = None
    recognizer.cached_text_features = None
    recognizer.tokenizer = lambda labels: torch.tensor([[1.0, 0.0], [0.0, 1.0]], dtype=torch.float32)

    original_encode_text = recognizer.model.encode_text

    def slow_encode_text(batch_tokens):
        time.sleep(0.05)
        return original_encode_text(batch_tokens)

    recognizer.model.encode_text = slow_encode_text
    results = []

    def worker():
        results.append(recognizer._get_text_features(["sparrow", "robin"]))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert recognizer.model.encode_text_calls == 1
    assert len(results) == 2
    assert results[0] is results[1]


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


def test_load_model_uses_registered_architecture_for_local_checkpoint(monkeypatch, tmp_path: Path):
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer.model_type_slug = "bioclip-2"
    recognizer.model_id = "hf-hub:imageomics/bioclip-2"
    recognizer.model_spec = get_model_spec("bioclip-2")
    model_dir = tmp_path / "data" / "models" / "bioclip-2"
    model_dir.mkdir(parents=True)
    checkpoint = model_dir / "open_clip_model.safetensors"
    checkpoint.write_bytes(b"fixture")
    calls = {}

    class FakeLoadedModel(_FakeModel):
        def parameters(self):
            yield torch.nn.Parameter(torch.ones(1))

    class FakeOpenClip:
        def create_model_and_transforms(self, architecture, pretrained, **kwargs):
            calls["model"] = (architecture, pretrained, kwargs)
            return FakeLoadedModel(), None, object()

        def get_tokenizer(self, model_id):
            calls["tokenizer"] = model_id
            return object()

    monkeypatch.setattr("src.recognition.inference_local._get_open_clip", lambda: FakeOpenClip())
    monkeypatch.setattr("torch.cuda.is_available", lambda: False)
    monkeypatch.chdir(tmp_path)

    recognizer._load_model()

    assert calls["model"][0] == "ViT-L-14"
    assert calls["model"][1] == str(Path("data/models/bioclip-2/open_clip_model.safetensors"))
    assert calls["tokenizer"] == "ViT-L-14"


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


def test_encode_images_returns_normalized_embeddings(tmp_path: Path):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    Image.new("RGB", (4, 4), color="white").save(first)
    Image.new("RGB", (4, 4), color="black").save(second)
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer.preprocess = lambda image: torch.tensor([1.0, 0.0], dtype=torch.float32)
    recognizer.model = _FakeModel()
    recognizer._memory_profile_enabled = False

    features = recognizer.encode_images([str(first), str(second)])

    assert features.shape == (2, 2)
    assert torch.allclose(features.norm(dim=-1), torch.ones(2))


def test_encode_images_rejects_invalid_image(tmp_path: Path):
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer.preprocess = lambda image: torch.tensor([1.0, 0.0], dtype=torch.float32)
    recognizer.model = _FakeModel()
    recognizer._memory_profile_enabled = False

    with pytest.raises(ValueError, match="Failed to load image"):
        recognizer.encode_images([str(tmp_path / "missing.jpg")])


def test_encode_images_falls_back_to_cpu_on_cuda_error():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cuda"
    recognizer.model = _FakeModel()
    recognizer.cached_text_features = object()
    calls = {"count": 0}

    def fake_encode(image_paths, skip_invalid):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("CUDA encoding failed")
        return torch.tensor([[1.0, 0.0]]), [0]

    recognizer._encode_image_paths = fake_encode

    features = recognizer.encode_images(["bird.jpg"])

    assert features.tolist() == [[1.0, 0.0]]
    assert recognizer.device == "cpu"
    assert recognizer.model.to_calls == ["cpu"]
    assert recognizer.cached_text_features is None


def test_classify_embeddings_supports_single_and_batch_inputs():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer._get_text_features = lambda labels: torch.tensor(
        [[1.0, 0.0], [0.0, 1.0]],
        dtype=torch.float32,
    )

    single = recognizer.classify_embeddings(torch.tensor([3.0, 1.0]), ["sparrow", "robin"], top_k=2)
    batch = recognizer.classify_embeddings(
        torch.tensor([[3.0, 1.0], [1.0, 3.0]]),
        ["sparrow", "robin"],
        top_k=1,
    )

    assert single[0][0]["scientific_name"] == "sparrow"
    assert [result[0]["scientific_name"] for result in batch] == ["sparrow", "robin"]


def test_classify_embeddings_handles_empty_candidates():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"

    assert recognizer.classify_embeddings(torch.tensor([[1.0, 0.0]]), []) == [[]]


def test_score_embeddings_returns_pre_softmax_logits_for_all_candidates():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer._get_text_features = lambda labels: torch.tensor(
        [[1.0, 0.0], [0.0, 1.0]],
        dtype=torch.float32,
    )

    logits = recognizer.score_embeddings(
        torch.tensor([[3.0, 4.0], [0.0, 2.0]]),
        ["sparrow", "robin"],
    )

    assert logits.shape == (2, 2)
    assert torch.allclose(logits, torch.tensor([[60.0, 80.0], [0.0, 100.0]]))


def test_score_embeddings_handles_single_empty_and_zero_batch_inputs():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer._get_text_features = lambda labels: torch.eye(2)

    single = recognizer.score_embeddings(torch.tensor([1.0, 0.0]), ["sparrow", "robin"])
    no_candidates = recognizer.score_embeddings(torch.ones((2, 2)), [])
    no_images = recognizer.score_embeddings(torch.empty((0, 2)), ["sparrow", "robin"])

    assert single.shape == (1, 2)
    assert no_candidates.shape == (2, 0)
    assert no_images.shape == (0, 2)


def test_classify_embeddings_uses_visual_logits_before_softmax():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"
    recognizer.score_embeddings = lambda features, labels: torch.tensor([[1.0, 3.0]])

    result = recognizer.classify_embeddings(torch.tensor([1.0, 0.0]), ["sparrow", "robin"], top_k=2)

    assert [item["scientific_name"] for item in result[0]] == ["robin", "sparrow"]
    assert result[0][0]["confidence"] == pytest.approx(torch.softmax(torch.tensor([1.0, 3.0]), 0)[1].item())


@pytest.mark.parametrize(
    "features,top_k",
    [
        (torch.ones((1, 1, 2)), 1),
        (torch.ones((1, 2)), 0),
    ],
)
def test_classify_embeddings_validates_inputs(features, top_k):
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"

    with pytest.raises(ValueError):
        recognizer.classify_embeddings(features, ["sparrow"], top_k=top_k)


def test_score_embeddings_validates_feature_dimensions():
    recognizer = LocalBirdRecognizer.__new__(LocalBirdRecognizer)
    recognizer.device = "cpu"

    with pytest.raises(ValueError, match="1D or 2D"):
        recognizer.score_embeddings(torch.ones((1, 1, 2)), ["sparrow"])
