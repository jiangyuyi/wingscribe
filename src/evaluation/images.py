from __future__ import annotations

import random
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from PIL import Image

from .datasets import EvaluationSample


def build_crop_box(
    sample: EvaluationSample,
    image_size: tuple[int, int],
    *,
    margin: float = 0.0,
    jitter: float = 0.0,
    seed: int = 0,
) -> tuple[float, float, float, float]:
    if sample.bbox is None:
        raise ValueError(f"Sample {sample.sample_id} does not have a bounding box")
    if margin < 0:
        raise ValueError("margin must not be negative")
    if not 0 <= jitter < 1:
        raise ValueError("jitter must be in the range [0, 1)")

    x1, y1, x2, y2 = sample.bbox
    box_width = x2 - x1
    box_height = y2 - y1
    if box_width <= 0 or box_height <= 0:
        raise ValueError(f"Sample {sample.sample_id} has an invalid bounding box")

    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    scale = 1 + 2 * margin

    if jitter:
        rng = random.Random(f"{seed}:{sample.sample_id}")
        center_x += rng.uniform(-jitter, jitter) * box_width
        center_y += rng.uniform(-jitter, jitter) * box_height
        scale *= rng.uniform(1 - jitter, 1 + jitter)

    half_width = box_width * scale / 2
    half_height = box_height * scale / 2
    image_width, image_height = image_size
    crop = (
        max(0.0, center_x - half_width),
        max(0.0, center_y - half_height),
        min(float(image_width), center_x + half_width),
        min(float(image_height), center_y + half_height),
    )
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        raise ValueError(f"Sample {sample.sample_id} bbox is outside the image")
    return crop


class CUBCropPreparer:
    def __init__(
        self,
        *,
        margin: float = 0.0,
        jitter: float = 0.0,
        seed: int = 0,
        work_root: str | Path | None = None,
    ):
        if margin < 0:
            raise ValueError("margin must not be negative")
        if not 0 <= jitter < 1:
            raise ValueError("jitter must be in the range [0, 1)")
        self.margin = margin
        self.jitter = jitter
        self.seed = seed
        self.work_root = Path(work_root) if work_root is not None else None

    @contextmanager
    def prepare(self, samples: Sequence[EvaluationSample]) -> Iterator[list[str]]:
        if self.work_root is not None:
            self.work_root.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="wingscribe-eval-", dir=self.work_root) as temp_dir:
            paths: list[str] = []
            for index, sample in enumerate(samples):
                output_path = Path(temp_dir) / f"{index:04d}.jpg"
                with Image.open(sample.image_path) as image:
                    crop_box = build_crop_box(
                        sample,
                        image.size,
                        margin=self.margin,
                        jitter=self.jitter,
                        seed=self.seed,
                    )
                    cropped = image.crop(crop_box)
                    if cropped.mode != "RGB":
                        cropped = cropped.convert("RGB")
                    cropped.save(output_path, format="JPEG", quality=95)
                paths.append(str(output_path))
            yield paths
