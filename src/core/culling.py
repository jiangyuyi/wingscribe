"""Pure JPEG culling policies; no file mutation or quality verdicts."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Iterable, Sequence


RECOMMENDATION_COUNT = 3


@dataclass(frozen=True)
class Capture:
    version_id: str
    source_id: str
    directory_key: str
    camera_key: str | None
    captured_at: datetime | None


@dataclass(frozen=True)
class CaptureGroup:
    group_id: str
    version_ids: tuple[str, ...]
    reason: str


def _group(items: Sequence[Capture], reason: str) -> CaptureGroup:
    members = tuple(item.version_id for item in items)
    identity = json.dumps(sorted(members), ensure_ascii=False).encode("utf-8")
    return CaptureGroup(hashlib.sha256(identity).hexdigest(), members, reason)


def group_captures(
    captures: Iterable[Capture], *, max_gap_seconds: float, max_span_seconds: float
) -> list[CaptureGroup]:
    """Suggest time groups, never asserting that adjacent shots share a subject.

    Callers supply normalized directory/camera identities and EXIF capture times.
    Unknown time/camera inputs remain singletons. Naive camera-local times and
    offset-aware times never mix. The span limit prevents transitive long chains.
    """
    if not all(math.isfinite(v) and v > 0 for v in (max_gap_seconds, max_span_seconds)):
        raise ValueError("Grouping intervals must be finite and positive")
    buckets: dict[tuple, list[Capture]] = {}
    groups = []
    seen = set()
    for item in captures:
        if not item.version_id or not item.source_id or not item.directory_key:
            raise ValueError("Capture identity and directory are required")
        if item.version_id in seen:
            raise ValueError("Duplicate capture version")
        seen.add(item.version_id)
        if item.captured_at is None or not item.camera_key:
            groups.append(_group([item], "missing_capture_time_or_camera"))
            continue
        aware = item.captured_at.utcoffset() is not None
        key = (item.source_id, item.directory_key, item.camera_key, aware)
        buckets.setdefault(key, []).append(item)

    def instant(item: Capture) -> datetime:
        value = item.captured_at
        assert value is not None
        return value.astimezone(timezone.utc) if value.utcoffset() is not None else value

    for key in sorted(buckets):
        ordered = sorted(buckets[key], key=lambda item: (instant(item), item.version_id))
        current: list[Capture] = []
        for item in ordered:
            if current and (
                (instant(item) - instant(current[-1])).total_seconds() > max_gap_seconds
                or (instant(item) - instant(current[0])).total_seconds() > max_span_seconds
            ):
                groups.append(_group(current, "time_candidate"))
                current = []
            current.append(item)
        groups.append(_group(current, "time_candidate"))
    return sorted(groups, key=lambda group: group.group_id)


@dataclass(frozen=True)
class PrimarySubject:
    detection_index: int
    bbox: tuple[float, float, float, float]
    area_pixels: float


def largest_subject(
    boxes: Iterable[Sequence[float]], *, width: int, height: int
) -> PrimarySubject | None:
    """Choose largest valid XYXY box clipped to the supplied image frame.

    Coordinates must already match the oriented image; no padding, resizing,
    confidence weighting, or inference from missing detections is performed.
    Equal areas retain detector order. Invalid/empty boxes are ignored.
    """
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("Image dimensions must be finite and positive")
    best = None
    for index, box in enumerate(boxes):
        if len(box) != 4 or not all(math.isfinite(v) for v in box):
            continue
        x1, y1, x2, y2 = box
        x1, x2 = max(0.0, min(width, x1)), max(0.0, min(width, x2))
        y1, y2 = max(0.0, min(height, y1)), max(0.0, min(height, y2))
        if x2 <= x1 or y2 <= y1:
            continue
        area = (x2 - x1) * (y2 - y1)
        if best is None or area > best.area_pixels:
            best = PrimarySubject(index, (x1, y1, x2, y2), area)
    return best
