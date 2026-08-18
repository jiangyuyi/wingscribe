from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, Sequence

from src.recognition.prior import SpeciesPriorProvider, rerank_visual_logits

from .datasets import EvaluationSample


class PriorRecognizer(Protocol):
    def encode_images(self, image_paths: list[str]): ...

    def score_embeddings(self, image_features, candidate_labels: list[str]): ...


class PriorBatchPredictor:
    def __init__(
        self,
        recognizer: PriorRecognizer,
        provider: SpeciesPriorProvider,
        *,
        weight: float = 0.25,
        location_confidence: float = 1.0,
        max_adjustment: float = 1.0,
    ):
        self.recognizer = recognizer
        self.provider = provider
        self.weight = weight
        self.location_confidence = location_confidence
        self.max_adjustment = max_adjustment

    def predict(
        self,
        samples: Sequence[EvaluationSample],
        candidate_labels: list[str],
        top_k: int,
    ) -> list[list[dict[str, Any]]]:
        features = self.recognizer.encode_images([str(Path(sample.image_path)) for sample in samples])
        logits = self.recognizer.score_embeddings(features, candidate_labels).detach().cpu().tolist()
        if len(logits) != len(samples):
            raise ValueError("Prior recognizer returned a different number of score rows")
        results: list[list[dict[str, Any]]] = []
        for sample, visual_logits in zip(samples, logits):
            application = self.provider.build_application(
                candidate_labels,
                region_context={"national": str(sample.metadata.get("national") or "")},
                month=sample.metadata.get("month"),
                weight=self.weight,
                location_confidence=self.location_confidence,
                max_adjustment=self.max_adjustment,
            )
            results.append(
                rerank_visual_logits(
                    visual_logits,
                    candidate_labels,
                    application,
                    top_k=top_k,
                )
            )
        return results
