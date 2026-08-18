"""Reusable public-dataset evaluation utilities."""

from .benchmark import BenchmarkPrediction, BenchmarkResult, run_benchmark
from .compare import ReportFormatError, compare_reports
from .datasets import (
    EvaluationDataset,
    EvaluationSample,
    load_cub_dataset,
    select_evaluation_subset,
)
from .images import CUBCropPreparer, CUBMultiCropPreparer, build_crop_box
from .hardware import HardwareMeasurement, begin_hardware_measurement, finish_hardware_measurement
from .inaturalist import load_inaturalist_manifest
from .local_directory import load_candidate_labels, load_local_directory
from .multicrop import MultiCropPredictor
from .prior import PriorBatchPredictor
from .quality import (
    DEFAULT_DEGRADATIONS,
    DegradationSpec,
    apply_degradation,
    run_quality_benchmark,
    write_quality_report,
)

__all__ = [
    "BenchmarkPrediction",
    "BenchmarkResult",
    "ReportFormatError",
    "EvaluationDataset",
    "EvaluationSample",
    "HardwareMeasurement",
    "CUBCropPreparer",
    "CUBMultiCropPreparer",
    "MultiCropPredictor",
    "PriorBatchPredictor",
    "DEFAULT_DEGRADATIONS",
    "DegradationSpec",
    "apply_degradation",
    "build_crop_box",
    "begin_hardware_measurement",
    "finish_hardware_measurement",
    "load_cub_dataset",
    "load_inaturalist_manifest",
    "load_candidate_labels",
    "load_local_directory",
    "select_evaluation_subset",
    "run_benchmark",
    "run_quality_benchmark",
    "write_quality_report",
    "compare_reports",
]
