from __future__ import annotations

import json
import random
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from src.core.quality import QualityEvaluator


@dataclass(frozen=True)
class DegradationSpec:
    name: str
    kind: str
    severity: float

    def __post_init__(self):
        if self.kind not in {"original", "blur", "downsample", "exposure", "noise"}:
            raise ValueError(f"Unsupported degradation kind: {self.kind}")
        if self.severity < 0:
            raise ValueError("severity must not be negative")
        if self.kind == "downsample" and not 0 < self.severity <= 1:
            raise ValueError("downsample severity must be in the range (0, 1]")


DEFAULT_DEGRADATIONS = (
    DegradationSpec("original", "original", 0.0),
    DegradationSpec("blur_mild", "blur", 1.5),
    DegradationSpec("blur_strong", "blur", 4.0),
    DegradationSpec("downsample_half", "downsample", 0.5),
    DegradationSpec("downsample_quarter", "downsample", 0.25),
    DegradationSpec("exposure_dark", "exposure", 0.35),
    DegradationSpec("exposure_bright", "exposure", 2.0),
    DegradationSpec("noise_moderate", "noise", 18.0),
)


def apply_degradation(
    image: Image.Image,
    spec: DegradationSpec,
    *,
    seed: int = 0,
) -> Image.Image:
    source = image.convert("RGB")
    if spec.kind == "original":
        return source.copy()
    if spec.kind == "blur":
        return source.filter(ImageFilter.GaussianBlur(radius=spec.severity))
    if spec.kind == "downsample":
        width, height = source.size
        reduced = source.resize(
            (max(1, round(width * spec.severity)), max(1, round(height * spec.severity))),
            Image.Resampling.LANCZOS,
        )
        return reduced.resize(source.size, Image.Resampling.BICUBIC)
    if spec.kind == "exposure":
        return ImageEnhance.Brightness(source).enhance(spec.severity)

    pixels = np.asarray(source, dtype=np.float32)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, spec.severity, pixels.shape)
    return Image.fromarray(np.clip(pixels + noise, 0, 255).astype(np.uint8))


def run_quality_benchmark(
    image_paths: Sequence[str | Path],
    *,
    degradations: Sequence[DegradationSpec] = DEFAULT_DEGRADATIONS,
    seed: int = 20260817,
) -> dict:
    if not image_paths:
        raise ValueError("at least one image is required")
    if not degradations or degradations[0].kind != "original":
        raise ValueError("the first degradation must be the original baseline")

    samples = []
    with tempfile.TemporaryDirectory(prefix="wingscribe-quality-eval-") as temp_dir:
        temp_root = Path(temp_dir)
        for image_index, raw_path in enumerate(image_paths):
            image_path = Path(raw_path)
            with Image.open(image_path) as image:
                conditions = []
                for condition_index, spec in enumerate(degradations):
                    condition_seed = random.Random(f"{seed}:{image_path}:{spec.name}").randrange(2**32)
                    output_path = temp_root / f"{image_index:05d}-{condition_index:02d}.png"
                    apply_degradation(image, spec, seed=condition_seed).save(output_path, format="PNG")
                    result = QualityEvaluator.evaluate(str(output_path))
                    output_path.unlink(missing_ok=True)
                    conditions.append(
                        {
                            "name": spec.name,
                            "kind": spec.kind,
                            "severity": spec.severity,
                            **result.to_dict(),
                        }
                    )

            baseline_score = conditions[0]["quality_score"]
            for condition in conditions:
                condition["quality_delta_vs_original"] = condition["quality_score"] - baseline_score
            samples.append({"image_path": str(image_path), "conditions": conditions})

    summary = []
    for spec in degradations:
        values = [
            next(condition for condition in sample["conditions"] if condition["name"] == spec.name)
            for sample in samples
        ]
        deltas = [value["quality_delta_vs_original"] for value in values]
        summary.append(
            {
                **asdict(spec),
                "sample_count": len(values),
                "valid_count": sum(bool(value["valid"]) for value in values),
                "mean_quality_score": sum(value["quality_score"] for value in values) / len(values),
                "mean_laplacian_variance": sum(value["laplacian_variance"] for value in values) / len(values),
                "mean_quality_delta_vs_original": sum(deltas) / len(deltas),
                "quality_decrease_rate": sum(delta < 0 for delta in deltas) / len(deltas),
            }
        )

    return {
        "run": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "seed": seed,
            "image_count": len(samples),
        },
        "summary": summary,
        "samples": samples,
    }


def write_quality_report(report: dict, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
