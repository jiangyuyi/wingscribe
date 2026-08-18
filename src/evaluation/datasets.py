from __future__ import annotations

import hashlib
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class DatasetFormatError(ValueError):
    """Raised when a public dataset does not match its documented layout."""


@dataclass(frozen=True)
class EvaluationSample:
    sample_id: str
    image_path: Path
    expected_label: str
    split: str
    bbox: tuple[float, float, float, float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationDataset:
    name: str
    samples: tuple[EvaluationSample, ...]
    candidate_labels: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


def select_evaluation_subset(
    dataset: EvaluationDataset,
    limit: int,
    *,
    strategy: str = "stratified",
    seed: int = 20260817,
) -> EvaluationDataset:
    """Select a deterministic subset without concentrating on early classes."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if strategy not in {"stratified", "sequential"}:
        raise ValueError("strategy must be one of: stratified, sequential")

    if strategy == "sequential":
        selected = list(dataset.samples[:limit])
    else:
        rng = random.Random(seed)
        grouped: dict[str, list[EvaluationSample]] = defaultdict(list)
        for sample in dataset.samples:
            grouped[sample.expected_label].append(sample)

        labels = sorted(grouped)
        rng.shuffle(labels)
        queues: dict[str, deque[EvaluationSample]] = {}
        for label in labels:
            samples = grouped[label]
            rng.shuffle(samples)
            queues[label] = deque(samples)

        selected = []
        while len(selected) < limit:
            added = False
            for label in labels:
                if queues[label]:
                    selected.append(queues[label].popleft())
                    added = True
                    if len(selected) == limit:
                        break
            if not added:
                break

    return EvaluationDataset(
        name=dataset.name,
        samples=tuple(selected),
        candidate_labels=dataset.candidate_labels,
        metadata={
            **dataset.metadata,
            "sample_selection": {
                "strategy": strategy,
                "seed": seed if strategy == "stratified" else None,
                "requested_limit": limit,
                "selected_samples": len(selected),
                "selected_classes": len({sample.expected_label for sample in selected}),
            },
        },
    )


def _read_indexed_lines(path: Path) -> dict[int, str]:
    if not path.is_file():
        raise DatasetFormatError(f"Missing annotation file: {path}")

    values: dict[int, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            raw_id, value = line.split(maxsplit=1)
            item_id = int(raw_id)
        except ValueError as exc:
            raise DatasetFormatError(f"Invalid line {line_number} in {path.name}: {raw_line}") from exc
        if item_id in values:
            raise DatasetFormatError(f"Duplicate id {item_id} in {path.name}")
        values[item_id] = value
    return values


def _normalize_cub_label(raw_label: str) -> str:
    label = raw_label.split(".", 1)[-1]
    return label.replace("_", " ").strip()


def _annotation_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _resolve_cub_root(root: str | Path) -> Path:
    root_path = Path(root).expanduser().resolve()
    nested = root_path / "CUB_200_2011"
    if nested.is_dir():
        return nested
    return root_path


def load_cub_dataset(
    root: str | Path,
    split: str = "test",
    *,
    require_images: bool = True,
) -> EvaluationDataset:
    """Load CUB-200-2011 annotations without copying or redistributing images."""
    if split not in {"train", "test", "all"}:
        raise ValueError("split must be one of: train, test, all")

    dataset_root = _resolve_cub_root(root)
    annotation_paths = [
        dataset_root / "classes.txt",
        dataset_root / "images.txt",
        dataset_root / "image_class_labels.txt",
        dataset_root / "train_test_split.txt",
        dataset_root / "bounding_boxes.txt",
    ]
    classes = _read_indexed_lines(annotation_paths[0])
    images = _read_indexed_lines(annotation_paths[1])
    image_classes = _read_indexed_lines(annotation_paths[2])
    split_flags = _read_indexed_lines(annotation_paths[3])
    raw_boxes = _read_indexed_lines(annotation_paths[4])

    labels = {class_id: _normalize_cub_label(label) for class_id, label in classes.items()}
    image_root = (dataset_root / "images").resolve()
    samples: list[EvaluationSample] = []

    for image_id in sorted(images):
        try:
            class_id = int(image_classes[image_id])
            is_train = int(split_flags[image_id]) == 1
            x, y, width, height = (float(value) for value in raw_boxes[image_id].split())
            expected_label = labels[class_id]
        except KeyError as exc:
            raise DatasetFormatError(f"Incomplete annotations for image id {image_id}") from exc
        except ValueError as exc:
            raise DatasetFormatError(f"Invalid annotations for image id {image_id}") from exc

        sample_split = "train" if is_train else "test"
        if split != "all" and sample_split != split:
            continue

        image_path = (image_root / images[image_id]).resolve()
        try:
            image_path.relative_to(image_root)
        except ValueError as exc:
            raise DatasetFormatError(f"Image path escapes the dataset root: {images[image_id]}") from exc
        if require_images and not image_path.is_file():
            raise DatasetFormatError(f"Missing image for id {image_id}: {image_path}")

        samples.append(
            EvaluationSample(
                sample_id=str(image_id),
                image_path=image_path,
                expected_label=expected_label,
                split=sample_split,
                bbox=(x, y, x + width, y + height),
            )
        )

    if not samples:
        raise DatasetFormatError(f"No CUB samples found for split '{split}'")

    return EvaluationDataset(
        name="CUB-200-2011",
        samples=tuple(samples),
        candidate_labels=tuple(labels[class_id] for class_id in sorted(labels)),
        metadata={
            "root": str(dataset_root),
            "split": split,
            "annotation_sha256": _annotation_hash(annotation_paths),
            "license_notice": "Images are restricted to non-commercial research and educational use.",
            "source_url": "https://www.vision.caltech.edu/datasets/cub_200_2011/",
        },
    )
