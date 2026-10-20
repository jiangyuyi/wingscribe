"""Experimental native-pixel focus evidence, not calibrated focus probabilities."""
from dataclasses import asdict, dataclass
import math
from typing import Iterable

import cv2
import numpy as np

from src.core.culling import CaptureGroup, RECOMMENDATION_COUNT, largest_subject
from src.core.culling_input import JpegInput


ALGORITHM_VERSION = "native-gradient-v1-experimental"


@dataclass(frozen=True)
class FocusPolicy:
    min_side: int = 32
    min_contrast: float = 3.0
    max_noise: float = 8.0
    max_clipped_fraction: float = 0.5

    def __post_init__(self):
        if (not isinstance(self.min_side, int) or self.min_side < 16
                or not all(math.isfinite(v) and v > 0 for v in
                           (self.min_contrast, self.max_noise, self.max_clipped_fraction))
                or self.max_clipped_fraction > 1):
            raise ValueError("Invalid focus policy")


@dataclass(frozen=True)
class FocusEvidence:
    version_id: str
    input_sha256: str
    algorithm: str
    policy: FocusPolicy
    status: str
    reasons: tuple[str, ...]
    detection_index: int | None
    bounds: tuple[int, int, int, int] | None
    metrics: dict[str, float]
    score: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_focus(
    frame: JpegInput, boxes: Iterable, *, version_id: str,
    policy: FocusPolicy = FocusPolicy(),
) -> FocusEvidence:
    """Boxes must be in frame's oriented coordinates. Never analyze padding.

    Noise estimate is median absolute diagonal differences / Gaussian MAD
    factor. Texture can also raise it, so high values mean review, not noise
    certainty. Fixed Gaussian filters measure gradient persistence across two
    scales without resizing the subject or modifying the source.
    """
    if not version_id:
        raise ValueError("File version identity is required")
    subject = largest_subject(boxes, width=frame.size[0], height=frame.size[1])

    def result(reasons, bounds=None, metrics=None, score=None):
        return FocusEvidence(version_id, frame.sha256, ALGORITHM_VERSION, policy,
                             "review" if reasons else "rankable", tuple(reasons),
                             subject.detection_index if subject else None,
                             bounds, metrics or {}, score)

    if subject is None:
        return result(["no_valid_subject"])
    pixels, bounds = frame.crop(subject.bbox)
    h, w = pixels.shape[:2]
    metrics = {"width": float(w), "height": float(h), "pixel_count": float(w * h)}
    if min(w, h) < policy.min_side:
        return result(["subject_too_small"], bounds, metrics)
    gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY).astype(np.float32)
    contrast = float(gray.std())
    clipped = float(np.mean((gray <= 5) | (gray >= 250)))
    diagonal = gray[:-1, :-1] - gray[1:, :-1] - gray[:-1, 1:] + gray[1:, 1:]
    noise = float(np.median(np.abs(diagonal)) / (2 * 0.67448975))

    def energy(sigma):
        smooth = cv2.GaussianBlur(gray, (0, 0), sigma, borderType=cv2.BORDER_REFLECT_101)
        dx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3, scale=1 / 8)
        dy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3, scale=1 / 8)
        # Exclude filter boundary artifacts, while preserving native scale.
        return float(np.mean((dx * dx + dy * dy)[6:-6, 6:-6]))

    fine, coarse = energy(1.0), energy(2.0)
    metrics.update(contrast=contrast, clipped_fraction=clipped, noise_estimate=noise,
                   gradient_energy_sigma1=fine, gradient_energy_sigma2=coarse)
    reasons = []
    if contrast < policy.min_contrast or coarse < 0.01:
        reasons.append("insufficient_structure")
    if noise > policy.max_noise:
        reasons.append("noise_or_fine_texture")
    if clipped > policy.max_clipped_fraction:
        reasons.append("severe_clipping")
    # A relative spectral-detail ratio; neither probability nor absolute quality.
    score = max(0.0, fine / max(coarse, 0.01) - 1.0)
    return result(reasons, bounds, metrics, None if reasons else score)


@dataclass(frozen=True)
class FocusRanking:
    group_id: str
    ranked: tuple[str, ...]
    recommended: tuple[str, ...]
    unranked: tuple[str, ...]
    tie_sets: tuple[tuple[str, ...], ...]
    warnings: tuple[str, ...]
    tie_fraction: float
    max_side_ratio: float


def rank_group(
    group: CaptureGroup, evidence: Iterable[FocusEvidence], *,
    tie_fraction: float = 0.05, max_side_ratio: float = 2.0,
) -> FocusRanking:
    """Recommend up to three within one group; never classify rejected photos.

    Missing/review evidence remains unranked. Native-scale size mismatch blocks
    recommendations until reviewed. Ties preserve capture order, including at
    the Top-3 boundary; tie_sets keeps alternative tied candidates visible.
    """
    if not math.isfinite(tie_fraction) or not 0 <= tie_fraction <= 1:
        raise ValueError("Invalid tie tolerance")
    if not math.isfinite(max_side_ratio) or max_side_ratio < 1:
        raise ValueError("Invalid size tolerance")
    members = group.version_ids
    if len(set(members)) != len(members):
        raise ValueError("Duplicate group members")
    records = {}
    for item in evidence:
        if item.version_id not in members or item.version_id in records:
            raise ValueError("Evidence must belong uniquely to this group")
        records[item.version_id] = item
    if len({(e.algorithm, e.policy) for e in records.values()}) > 1:
        raise ValueError("Do not mix algorithms or scoring policies")
    eligible = []
    for key in members:
        item = records.get(key)
        if item and item.status == "rankable":
            if item.score is None or not math.isfinite(item.score) or item.score < 0 or not item.bounds:
                raise ValueError("Invalid rankable evidence")
            x1, y1, x2, y2 = item.bounds
            if x2 <= x1 or y2 <= y1:
                raise ValueError("Invalid evidence bounds")
            eligible.append(item)
    warnings = ["relative_ranking_not_focus_verdict"]
    if eligible:
        widths = [e.bounds[2] - e.bounds[0] for e in eligible]
        heights = [e.bounds[3] - e.bounds[1] for e in eligible]
        if max(widths) / min(widths) > max_side_ratio or max(heights) / min(heights) > max_side_ratio:
            return FocusRanking(group.group_id, (), (), members, (),
                                tuple(warnings + ["subject_scale_mismatch"]),
                                tie_fraction, max_side_ratio)
    eligible.sort(key=lambda e: -e.score)  # Stable capture order for exact ties.
    buckets = []
    for item in eligible:
        if not buckets or buckets[-1][0].score - item.score > tie_fraction * max(buckets[-1][0].score, 1e-9):
            buckets.append([item])
        else:
            buckets[-1].append(item)
    order = {key: i for i, key in enumerate(members)}
    for bucket in buckets:
        bucket.sort(key=lambda e: order[e.version_id])
    ranked = tuple(e.version_id for bucket in buckets for e in bucket)
    ties = tuple(tuple(e.version_id for e in bucket) for bucket in buckets if len(bucket) > 1)
    if ties:
        warnings.append("near_ties_compare_manually")
    if not ranked:
        warnings.append("no_rankable_subjects")
    return FocusRanking(group.group_id, ranked, ranked[:RECOMMENDATION_COUNT],
                        tuple(key for key in members if key not in ranked), ties,
                        tuple(warnings), tie_fraction, max_side_ratio)
