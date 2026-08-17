from __future__ import annotations

import math
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

from .datasets import EvaluationDataset, EvaluationSample


class BatchRecognizer(Protocol):
    def predict_batch(
        self,
        image_paths: list[str],
        candidate_labels: list[str],
        top_k: int = 5,
    ) -> list[list[dict[str, Any]]]: ...


class BatchImagePreparer(Protocol):
    def prepare(self, samples: Sequence[EvaluationSample]): ...


class BatchPredictor(Protocol):
    def predict(
        self,
        samples: Sequence[EvaluationSample],
        candidate_labels: list[str],
        top_k: int,
    ) -> list[list[dict[str, Any]]]: ...


class OriginalImagePreparer:
    @contextmanager
    def prepare(self, samples: Sequence[EvaluationSample]):
        yield [str(sample.image_path) for sample in samples]


@dataclass(frozen=True)
class BenchmarkPrediction:
    sample_id: str
    image_path: str
    expected_label: str
    predicted_labels: tuple[str, ...]
    confidences: tuple[float, ...]
    duration_ms: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["predicted_labels"] = list(self.predicted_labels)
        value["confidences"] = list(self.confidences)
        return value


@dataclass(frozen=True)
class BenchmarkResult:
    dataset: dict[str, Any]
    run: dict[str, Any]
    metrics: dict[str, Any]
    predictions: tuple[BenchmarkPrediction, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "run": self.run,
            "metrics": self.metrics,
            "predictions": [prediction.to_dict() for prediction in self.predictions],
        }


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summarize(predictions: Sequence[BenchmarkPrediction]) -> dict[str, Any]:
    total = len(predictions)
    succeeded = [prediction for prediction in predictions if prediction.error is None]
    top1 = sum(
        bool(prediction.predicted_labels)
        and prediction.predicted_labels[0] == prediction.expected_label
        for prediction in succeeded
    )
    top5 = sum(
        prediction.expected_label in prediction.predicted_labels[:5]
        for prediction in succeeded
    )
    durations = [prediction.duration_ms for prediction in succeeded]

    return {
        "total_samples": total,
        "succeeded_samples": len(succeeded),
        "failed_samples": total - len(succeeded),
        "top1_correct": top1,
        "top5_correct": top5,
        "top1_accuracy": top1 / total if total else 0.0,
        "top5_accuracy": top5 / total if total else 0.0,
        "mean_duration_ms": sum(durations) / len(durations) if durations else None,
        "p50_duration_ms": _percentile(durations, 0.50),
        "p95_duration_ms": _percentile(durations, 0.95),
    }


def _failed_prediction(sample: EvaluationSample, duration_ms: float, error: str) -> BenchmarkPrediction:
    return BenchmarkPrediction(
        sample_id=sample.sample_id,
        image_path=str(sample.image_path),
        expected_label=sample.expected_label,
        predicted_labels=(),
        confidences=(),
        duration_ms=duration_ms,
        error=error,
    )


def run_benchmark(
    dataset: EvaluationDataset,
    recognizer: BatchRecognizer,
    *,
    batch_size: int = 16,
    top_k: int = 5,
    run_metadata: dict[str, Any] | None = None,
    image_preparer: BatchImagePreparer | None = None,
    batch_predictor: BatchPredictor | None = None,
) -> BenchmarkResult:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    started_at = datetime.now(timezone.utc).isoformat()
    predictions: list[BenchmarkPrediction] = []
    candidates = list(dataset.candidate_labels)
    preparer = image_preparer or OriginalImagePreparer()

    for start in range(0, len(dataset.samples), batch_size):
        batch = dataset.samples[start : start + batch_size]
        started = time.perf_counter()
        try:
            if batch_predictor is not None:
                raw_results = batch_predictor.predict(batch, candidates, top_k)
            else:
                with preparer.prepare(batch) as prepared_paths:
                    if len(prepared_paths) != len(batch):
                        raise ValueError(
                            f"Image preparer returned {len(prepared_paths)} paths for a batch of {len(batch)}"
                        )
                    raw_results = recognizer.predict_batch(prepared_paths, candidates, top_k)
            elapsed_per_sample = (time.perf_counter() - started) * 1000 / len(batch)
        except Exception as exc:
            elapsed_per_sample = (time.perf_counter() - started) * 1000 / len(batch)
            predictions.extend(
                _failed_prediction(sample, elapsed_per_sample, f"{type(exc).__name__}: {exc}")
                for sample in batch
            )
            continue

        if len(raw_results) != len(batch):
            error = f"Recognizer returned {len(raw_results)} results for a batch of {len(batch)}"
            predictions.extend(_failed_prediction(sample, elapsed_per_sample, error) for sample in batch)
            continue

        for sample, raw_prediction in zip(batch, raw_results):
            if not raw_prediction:
                predictions.append(_failed_prediction(sample, elapsed_per_sample, "No predictions returned"))
                continue

            labels = tuple(str(item.get("scientific_name") or item.get("label") or "") for item in raw_prediction)
            confidences = tuple(float(item.get("confidence", 0.0)) for item in raw_prediction)
            predictions.append(
                BenchmarkPrediction(
                    sample_id=sample.sample_id,
                    image_path=str(sample.image_path),
                    expected_label=sample.expected_label,
                    predicted_labels=labels,
                    confidences=confidences,
                    duration_ms=elapsed_per_sample,
                )
            )

    run = {
        "started_at": started_at,
        "batch_size": batch_size,
        "top_k": top_k,
    }
    if run_metadata:
        run.update(run_metadata)

    return BenchmarkResult(
        dataset={"name": dataset.name, "sample_count": len(dataset.samples), **dataset.metadata},
        run=run,
        metrics=_summarize(predictions),
        predictions=tuple(predictions),
    )
