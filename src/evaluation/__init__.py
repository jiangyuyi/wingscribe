"""Reusable public-dataset evaluation utilities."""

from .benchmark import BenchmarkPrediction, BenchmarkResult, run_benchmark
from .datasets import EvaluationDataset, EvaluationSample, load_cub_dataset
from .images import CUBCropPreparer, build_crop_box

__all__ = [
    "BenchmarkPrediction",
    "BenchmarkResult",
    "EvaluationDataset",
    "EvaluationSample",
    "CUBCropPreparer",
    "build_crop_box",
    "load_cub_dataset",
    "run_benchmark",
]
