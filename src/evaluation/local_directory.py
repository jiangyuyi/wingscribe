from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Iterable

from .datasets import DatasetFormatError, EvaluationDataset, EvaluationSample


SUPPORTED_IMAGE_EXTENSIONS = frozenset(
    {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
)


def load_candidate_labels(path: str | Path) -> tuple[str, ...]:
    candidate_path = Path(path).expanduser().resolve()
    try:
        lines = candidate_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise DatasetFormatError(f"Unable to read candidate label file: {candidate_path}") from exc

    labels = tuple(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))
    if not labels:
        raise DatasetFormatError("Candidate label file contains no labels")
    if len(labels) != len(set(labels)):
        raise DatasetFormatError("Candidate label file contains duplicate labels")
    return labels


def _hash_values(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _relative_image_paths(root: Path, recursive: bool) -> list[tuple[str, Path]]:
    paths = root.rglob("*") if recursive else root.glob("*")
    images: list[tuple[str, Path]] = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise DatasetFormatError(f"Image path escapes the shadow root: {path}") from exc
        relative_key = relative.as_posix()
        images.append((relative_key, resolved))
    images.sort(key=lambda item: (item[0].casefold(), item[0]))
    return images


def load_local_directory(
    root: str | Path,
    candidate_labels: Iterable[str],
    *,
    recursive: bool = True,
    limit: int | None = None,
    seed: int = 20260818,
) -> EvaluationDataset:
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise DatasetFormatError(f"Shadow evaluation root is not a directory: {root_path}")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")

    labels = tuple(str(label).strip() for label in candidate_labels)
    if not labels or any(not label for label in labels):
        raise DatasetFormatError("Shadow evaluation requires non-empty candidate labels")
    if len(labels) != len(set(labels)):
        raise DatasetFormatError("Shadow evaluation candidate labels contain duplicates")

    image_paths = _relative_image_paths(root_path, recursive)
    discovered_count = len(image_paths)
    if not image_paths:
        raise DatasetFormatError(f"No supported images found under: {root_path}")

    if limit is not None and limit < len(image_paths):
        rng = random.Random(seed)
        rng.shuffle(image_paths)
        image_paths = sorted(image_paths[:limit], key=lambda item: (item[0].casefold(), item[0]))

    samples: list[EvaluationSample] = []
    snapshot_values: list[str] = []
    sample_ids: set[str] = set()
    for relative_path, image_path in image_paths:
        normalized_path = relative_path.casefold()
        sample_id = f"local-{hashlib.sha256(normalized_path.encode('utf-8')).hexdigest()[:20]}"
        if sample_id in sample_ids:
            raise DatasetFormatError(f"Shadow sample id collision for path: {relative_path}")
        sample_ids.add(sample_id)
        stat = image_path.stat()
        snapshot_values.append(f"{normalized_path}\0{stat.st_size}\0{stat.st_mtime_ns}")
        samples.append(
            EvaluationSample(
                sample_id=sample_id,
                image_path=image_path,
                expected_label="",
                split="shadow",
            )
        )

    return EvaluationDataset(
        name="Local-Directory-Shadow",
        samples=tuple(samples),
        candidate_labels=labels,
        metadata={
            "evaluation_type": "unlabeled_shadow",
            "root": str(root_path),
            "recursive": recursive,
            "supported_extensions": sorted(SUPPORTED_IMAGE_EXTENSIONS),
            "discovered_images": discovered_count,
            "selected_images": len(samples),
            "selection_seed": seed if limit is not None else None,
            "requested_limit": limit,
            "candidate_labels_count": len(labels),
            "candidate_labels_sha256": _hash_values(labels),
            "image_snapshot_sha256": _hash_values(snapshot_values),
        },
    )
