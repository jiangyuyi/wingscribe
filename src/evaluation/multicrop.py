from __future__ import annotations

from typing import Any, Protocol, Sequence

import torch

from .datasets import EvaluationSample
from .images import CUBMultiCropPreparer


class EmbeddingRecognizer(Protocol):
    def encode_images(self, image_paths: list[str]) -> torch.Tensor: ...

    def classify_embeddings(
        self,
        image_features: torch.Tensor,
        candidate_labels: list[str],
        top_k: int = 5,
    ) -> list[list[dict[str, Any]]]: ...


class MultiCropPredictor:
    def __init__(
        self,
        recognizer: EmbeddingRecognizer,
        margins: Sequence[float],
        weights: Sequence[float],
        *,
        work_root=None,
        encode_batch_size: int | None = None,
    ):
        if len(margins) != len(weights) or not margins:
            raise ValueError("margins and weights must have the same non-zero length")
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("weights must be non-negative and have a positive sum")
        if encode_batch_size is not None and encode_batch_size < 1:
            raise ValueError("encode_batch_size must be at least 1")

        weight_sum = float(sum(weights))
        self.recognizer = recognizer
        self.margins = tuple(float(margin) for margin in margins)
        self.weights = tuple(float(weight) / weight_sum for weight in weights)
        self.encode_batch_size = encode_batch_size
        self.preparer = CUBMultiCropPreparer(self.margins, work_root=work_root)

    def predict(
        self,
        samples: Sequence[EvaluationSample],
        candidate_labels: list[str],
        top_k: int,
    ) -> list[list[dict[str, Any]]]:
        if not samples:
            return []

        with self.preparer.prepare_views(samples) as paths:
            chunk_size = self.encode_batch_size or len(paths)
            feature_chunks = [
                self.recognizer.encode_images(paths[start : start + chunk_size])
                for start in range(0, len(paths), chunk_size)
            ]
            features = torch.cat(feature_chunks, dim=0)

        view_count = len(self.margins)
        expected_rows = len(samples) * view_count
        if features.ndim != 2 or features.shape[0] != expected_rows:
            raise ValueError(
                f"Recognizer returned embedding shape {tuple(features.shape)} for {expected_rows} views"
            )

        grouped = features.reshape(len(samples), view_count, features.shape[-1])
        weights = torch.tensor(self.weights, dtype=grouped.dtype, device=grouped.device).view(1, view_count, 1)
        fused = (grouped * weights).sum(dim=1)
        fused = fused / fused.norm(dim=-1, keepdim=True)
        return self.recognizer.classify_embeddings(fused, candidate_labels, top_k)
