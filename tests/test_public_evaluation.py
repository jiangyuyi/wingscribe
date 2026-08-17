import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from src.evaluation import EvaluationDataset, EvaluationSample, load_cub_dataset, run_benchmark
from src.evaluation.datasets import DatasetFormatError
from src.evaluation.images import CUBCropPreparer, build_crop_box


def _write_cub_fixture(root: Path) -> Path:
    dataset_root = root / "CUB_200_2011"
    (dataset_root / "images" / "001.Alpha_Bird").mkdir(parents=True)
    (dataset_root / "images" / "002.Beta_Bird").mkdir(parents=True)
    Image.new("RGB", (20, 10), "white").save(dataset_root / "images" / "001.Alpha_Bird" / "one.jpg")
    Image.new("RGB", (30, 20), "black").save(dataset_root / "images" / "002.Beta_Bird" / "two.jpg")
    (dataset_root / "classes.txt").write_text("1 001.Alpha_Bird\n2 002.Beta_Bird\n", encoding="utf-8")
    (dataset_root / "images.txt").write_text(
        "1 001.Alpha_Bird/one.jpg\n2 002.Beta_Bird/two.jpg\n",
        encoding="utf-8",
    )
    (dataset_root / "image_class_labels.txt").write_text("1 1\n2 2\n", encoding="utf-8")
    (dataset_root / "train_test_split.txt").write_text("1 1\n2 0\n", encoding="utf-8")
    (dataset_root / "bounding_boxes.txt").write_text("1 1 2 10 6\n2 2 3 20 10\n", encoding="utf-8")
    return dataset_root


def test_load_cub_dataset_reads_test_split_and_bbox(tmp_path: Path):
    dataset_root = _write_cub_fixture(tmp_path)

    dataset = load_cub_dataset(tmp_path, split="test")

    assert dataset.name == "CUB-200-2011"
    assert dataset.candidate_labels == ("Alpha Bird", "Beta Bird")
    assert len(dataset.samples) == 1
    assert dataset.samples[0].image_path == (dataset_root / "images" / "002.Beta_Bird" / "two.jpg").resolve()
    assert dataset.samples[0].expected_label == "Beta Bird"
    assert dataset.samples[0].bbox == (2.0, 3.0, 22.0, 13.0)
    assert len(dataset.metadata["annotation_sha256"]) == 64


def test_load_cub_dataset_supports_all_splits(tmp_path: Path):
    _write_cub_fixture(tmp_path)

    dataset = load_cub_dataset(tmp_path, split="all")

    assert [sample.split for sample in dataset.samples] == ["train", "test"]


def test_load_cub_dataset_rejects_missing_image(tmp_path: Path):
    dataset_root = _write_cub_fixture(tmp_path)
    (dataset_root / "images" / "002.Beta_Bird" / "two.jpg").unlink()

    with pytest.raises(DatasetFormatError, match="Missing image"):
        load_cub_dataset(tmp_path, split="test")


def test_load_cub_dataset_rejects_path_escape(tmp_path: Path):
    dataset_root = _write_cub_fixture(tmp_path)
    (dataset_root / "images.txt").write_text("1 ../one.jpg\n2 ../two.jpg\n", encoding="utf-8")

    with pytest.raises(DatasetFormatError, match="escapes the dataset root"):
        load_cub_dataset(tmp_path, split="test", require_images=False)


class _FakeRecognizer:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def predict_batch(self, image_paths, candidate_labels, top_k):
        self.calls.append((image_paths, candidate_labels, top_k))
        count = len(image_paths)
        result, self.results = self.results[:count], self.results[count:]
        return result


def _dataset(tmp_path: Path) -> EvaluationDataset:
    samples = tuple(
        EvaluationSample(str(index), tmp_path / f"{index}.jpg", label, "test")
        for index, label in enumerate(["Alpha", "Beta", "Gamma"], 1)
    )
    return EvaluationDataset("fixture", samples, ("Alpha", "Beta", "Gamma"), {"version": "1"})


def test_run_benchmark_calculates_topk_and_batches(tmp_path: Path):
    recognizer = _FakeRecognizer(
        [
            [{"scientific_name": "Alpha", "confidence": 0.9}],
            [
                {"scientific_name": "Gamma", "confidence": 0.6},
                {"scientific_name": "Beta", "confidence": 0.4},
            ],
            [{"scientific_name": "Alpha", "confidence": 0.8}],
        ]
    )

    result = run_benchmark(_dataset(tmp_path), recognizer, batch_size=2, top_k=5)

    assert len(recognizer.calls) == 2
    assert result.metrics["total_samples"] == 3
    assert result.metrics["top1_accuracy"] == pytest.approx(1 / 3)
    assert result.metrics["top5_accuracy"] == pytest.approx(2 / 3)
    assert result.metrics["failed_samples"] == 0


def test_run_benchmark_counts_empty_results_as_failures(tmp_path: Path):
    recognizer = _FakeRecognizer([[], [{"label": "Beta", "confidence": 0.5}], []])

    result = run_benchmark(_dataset(tmp_path), recognizer, batch_size=3)

    assert result.metrics["failed_samples"] == 2
    assert result.metrics["top1_accuracy"] == pytest.approx(1 / 3)
    assert result.predictions[0].error == "No predictions returned"


def test_run_benchmark_records_recognizer_errors(tmp_path: Path):
    class FailingRecognizer:
        def predict_batch(self, image_paths, candidate_labels, top_k):
            raise RuntimeError("model unavailable")

    result = run_benchmark(_dataset(tmp_path), FailingRecognizer(), batch_size=2)

    assert result.metrics["failed_samples"] == 3
    assert all("model unavailable" in prediction.error for prediction in result.predictions)


def test_benchmark_result_is_json_serializable(tmp_path: Path):
    recognizer = _FakeRecognizer(
        [[{"scientific_name": label, "confidence": 1.0}] for label in ["Alpha", "Beta", "Gamma"]]
    )

    result = run_benchmark(_dataset(tmp_path), recognizer, run_metadata={"model": "fake"})
    serialized = json.dumps(result.to_dict())

    assert '"top1_accuracy": 1.0' in serialized
    assert result.run["model"] == "fake"


@pytest.mark.parametrize("batch_size,top_k", [(0, 5), (1, 0)])
def test_run_benchmark_validates_limits(tmp_path: Path, batch_size: int, top_k: int):
    with pytest.raises(ValueError):
        run_benchmark(_dataset(tmp_path), _FakeRecognizer([]), batch_size=batch_size, top_k=top_k)


def test_public_evaluation_script_can_show_help():
    completed = subprocess.run(
        [sys.executable, "scripts/evaluate_public.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--dataset" in completed.stdout
    assert "--image-mode" in completed.stdout


def test_build_crop_box_applies_margin_and_clips_to_image(tmp_path: Path):
    sample = EvaluationSample("one", tmp_path / "one.jpg", "Alpha", "test", (2, 3, 12, 9))

    crop = build_crop_box(sample, (20, 10), margin=0.5)

    assert crop == (0.0, 0.0, 17.0, 10.0)


def test_build_crop_box_jitter_is_deterministic_per_sample(tmp_path: Path):
    sample = EvaluationSample("one", tmp_path / "one.jpg", "Alpha", "test", (20, 20, 80, 80))

    first = build_crop_box(sample, (100, 100), jitter=0.2, seed=7)
    second = build_crop_box(sample, (100, 100), jitter=0.2, seed=7)
    different = build_crop_box(sample, (100, 100), jitter=0.2, seed=8)

    assert first == second
    assert first != different


@pytest.mark.parametrize("margin,jitter", [(-0.1, 0.0), (0.0, -0.1), (0.0, 1.0)])
def test_build_crop_box_validates_parameters(tmp_path: Path, margin: float, jitter: float):
    sample = EvaluationSample("one", tmp_path / "one.jpg", "Alpha", "test", (1, 1, 5, 5))

    with pytest.raises(ValueError):
        build_crop_box(sample, (10, 10), margin=margin, jitter=jitter)


@pytest.mark.parametrize("margin,jitter", [(-0.1, 0.0), (0.0, -0.1), (0.0, 1.0)])
def test_cub_crop_preparer_validates_parameters(tmp_path: Path, margin: float, jitter: float):
    with pytest.raises(ValueError):
        CUBCropPreparer(margin=margin, jitter=jitter, work_root=tmp_path)


def test_cub_crop_preparer_creates_and_cleans_batch_crops(tmp_path: Path):
    image_path = tmp_path / "source.png"
    Image.new("RGBA", (20, 10), "white").save(image_path)
    sample = EvaluationSample("one", image_path, "Alpha", "test", (2, 2, 12, 8))
    preparer = CUBCropPreparer(work_root=tmp_path / "work")

    with preparer.prepare([sample]) as paths:
        crop_path = Path(paths[0])
        assert crop_path.is_file()
        with Image.open(crop_path) as crop:
            assert crop.size == (10, 6)
            assert crop.mode == "RGB"

    assert not crop_path.exists()


def test_run_benchmark_uses_image_preparer(tmp_path: Path):
    class TrackingPreparer:
        def __init__(self):
            self.calls = 0

        def prepare(self, samples):
            from contextlib import nullcontext

            self.calls += 1
            return nullcontext([f"prepared-{sample.sample_id}.jpg" for sample in samples])

    dataset = _dataset(tmp_path)
    recognizer = _FakeRecognizer(
        [[{"scientific_name": label, "confidence": 1.0}] for label in ["Alpha", "Beta", "Gamma"]]
    )
    preparer = TrackingPreparer()

    result = run_benchmark(dataset, recognizer, batch_size=2, image_preparer=preparer)

    assert result.metrics["top1_accuracy"] == 1.0
    assert preparer.calls == 2
    assert recognizer.calls[0][0] == ["prepared-1.jpg", "prepared-2.jpg"]
