from pathlib import Path

import pytest
import torch

from src.evaluation import EvaluationDataset, EvaluationSample, PriorBatchPredictor, run_benchmark
from src.recognition.prior import PriorRecord, SpeciesPriorProvider


class _Recognizer:
    def encode_images(self, image_paths):
        return torch.ones((len(image_paths), 2))

    def score_embeddings(self, features, candidate_labels):
        return torch.tensor([[1.0, 1.4]] * len(features))


def _provider() -> SpeciesPriorProvider:
    return SpeciesPriorProvider(
        [
            PriorRecord("Alpha", "national", "CN", 5, 0.8),
            PriorRecord("Beta", "national", "CN", 5, 0.2),
        ]
    )


def test_prior_batch_predictor_reranks_complete_candidate_scores(tmp_path: Path):
    predictor = PriorBatchPredictor(
        _Recognizer(),
        _provider(),
        weight=1.0,
        max_adjustment=2.0,
    )
    sample = EvaluationSample(
        "1",
        tmp_path / "bird.jpg",
        "Alpha",
        "test",
        metadata={"national": "CN", "month": 5},
    )

    results = predictor.predict([sample], ["Alpha", "Beta"], top_k=2)

    assert [item["scientific_name"] for item in results[0]] == ["Alpha", "Beta"]
    assert results[0][0]["visual_logit"] == 1.0
    assert results[0][0]["prior_source"]["month"] == 5


def test_run_benchmark_keeps_prior_candidate_audit_details(tmp_path: Path):
    sample = EvaluationSample(
        "1",
        tmp_path / "bird.jpg",
        "Alpha",
        "test",
        metadata={"national": "CN", "month": 5},
    )
    dataset = EvaluationDataset("fixture", (sample,), ("Alpha", "Beta"))
    predictor = PriorBatchPredictor(_Recognizer(), _provider(), weight=1.0, max_adjustment=2.0)

    result = run_benchmark(dataset, _Recognizer(), batch_predictor=predictor)
    serialized = result.to_dict()

    details = serialized["predictions"][0]["candidate_details"]
    assert details[0]["scientific_name"] == "Alpha"
    assert "visual_logit" in details[0]
    assert "prior_adjustment" in details[0]
    assert result.metrics["top1_accuracy"] == 1.0


def test_prior_batch_predictor_rejects_score_row_mismatch(tmp_path: Path):
    recognizer = _Recognizer()
    recognizer.score_embeddings = lambda features, labels: torch.empty((0, len(labels)))
    predictor = PriorBatchPredictor(recognizer, _provider())
    sample = EvaluationSample("1", tmp_path / "bird.jpg", "", "shadow")

    with pytest.raises(ValueError, match="score rows"):
        predictor.predict([sample], ["Alpha", "Beta"], top_k=1)
