"""Reusable public-dataset evaluation utilities."""

from .benchmark import BenchmarkPrediction, BenchmarkResult, run_benchmark
from .compare import ReportFormatError, compare_reports
from .datasets import EvaluationDataset, EvaluationSample, load_cub_dataset
from .images import CUBCropPreparer, CUBMultiCropPreparer, build_crop_box
from .multicrop import MultiCropPredictor

__all__ = [
    "BenchmarkPrediction",
    "BenchmarkResult",
    "ReportFormatError",
    "EvaluationDataset",
    "EvaluationSample",
    "CUBCropPreparer",
    "CUBMultiCropPreparer",
    "MultiCropPredictor",
    "build_crop_box",
    "load_cub_dataset",
    "run_benchmark",
    "compare_reports",
]
