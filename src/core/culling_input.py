"""Read-only JPEG input in an EXIF-oriented, full-resolution RGB frame."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Sequence

import numpy as np
from PIL import Image, ImageOps

from src.core.culling import Capture


@dataclass(frozen=True)
class CaptureMetadata:
    captured_at: datetime | None
    subsecond_digits: str | None
    camera_key: str | None
    camera_identity_kind: str
    make: str | None
    model: str | None
    orientation: int
    warnings: tuple[str, ...]


def _text(value) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="replace")
    if isinstance(value, str):
        return value.strip(" \x00") or None
    return None


def parse_metadata(exif: Image.Exif) -> CaptureMetadata:
    """Only original capture tags count; file mtime and EXIF ModifyDate do not."""
    tags = dict(exif)
    tags.update(exif.get_ifd(34665))  # ExifIFD; real cameras nest capture tags here.
    warnings = []
    orientation = tags.get(274, 1)
    if orientation not in range(1, 9):
        raise ValueError("Invalid EXIF orientation")
    if 274 not in tags:
        warnings.append("orientation_missing_assumed_1")
    original = _text(tags.get(36867))
    subsecond = _text(tags.get(37521))
    offset = _text(tags.get(36881))
    captured = None
    if original:
        try:
            if not re.fullmatch(r"\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}", original):
                raise ValueError("Invalid capture time")
            captured = datetime.strptime(original, "%Y:%m:%d %H:%M:%S")
            if subsecond:
                if not re.fullmatch(r"[0-9]+", subsecond):
                    raise ValueError("Invalid capture subsecond")
                captured = captured.replace(microsecond=int((subsecond + "000000")[:6]))
                if len(subsecond) > 6:
                    warnings.append("subsecond_truncated_to_microseconds")
            if offset:
                if not re.fullmatch(r"[+-]\d{2}:\d{2}", offset):
                    raise ValueError("Invalid capture offset")
                hours, minutes = int(offset[1:3]), int(offset[4:6])
                if hours > 23 or minutes > 59:
                    raise ValueError("Invalid capture offset")
                delta = timedelta(hours=hours, minutes=minutes)
                captured = captured.replace(tzinfo=timezone(delta if offset[0] == "+" else -delta))
        except ValueError:
            captured = None
            warnings.append("invalid_capture_time")
    else:
        warnings.append("capture_time_missing")
    make, model = _text(tags.get(271)), _text(tags.get(272))
    serial = _text(tags.get(42033))
    camera_key = None
    identity_kind = "missing"
    if make and model:
        identity_kind = "body_serial" if serial else "make_model"
        identity = [make.casefold(), model.casefold(), serial]
        camera_key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        if not serial:
            warnings.append("camera_serial_missing_same_model_may_merge")
    else:
        warnings.append("camera_identity_missing")
    return CaptureMetadata(captured, subsecond, camera_key, identity_kind, make, model,
                           orientation, tuple(warnings))


@dataclass(frozen=True)
class JpegInput:
    path: Path
    sha256: str
    size_bytes: int
    mtime_ns: int
    raw_size: tuple[int, int]
    container_format: str
    metadata: CaptureMetadata
    pixels: np.ndarray  # H x W x 3, uint8 RGB; EXIF-oriented, no resize.

    @property
    def size(self) -> tuple[int, int]:
        return self.pixels.shape[1], self.pixels.shape[0]

    def capture(self, *, version_id: str, source_id: str, directory_key: str) -> Capture:
        return Capture(version_id, source_id, directory_key,
                       self.metadata.camera_key, self.metadata.captured_at)

    def crop(self, bbox: Sequence[float]) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        """Oriented XYXY edges; floor starts/ceil ends, clipped, no padding."""
        x1, y1, x2, y2 = _box(bbox)
        width, height = self.size
        bounds = (max(0, min(width, math.floor(x1))), max(0, min(height, math.floor(y1))),
                  max(0, min(width, math.ceil(x2))), max(0, min(height, math.ceil(y2))))
        left, top, right, bottom = bounds
        if right <= left or bottom <= top:
            raise ValueError("Empty subject region")
        region = self.pixels[top:bottom, left:right].copy()
        region.setflags(write=False)
        return region, bounds


def _signature(stat) -> tuple:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def read_jpeg(path: str | Path) -> JpegInput:
    """Decode one JPEG and hash the same open file; reject observed replacement.

    Exceptions remain input errors, never a blur score. No ICC rendering,
    denoising, sharpening, EXIF write, or JPEG re-encoding is performed.
    """
    path = Path(path).absolute()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        stream.seek(0)
        with Image.open(stream) as image:
            if image.format not in ("JPEG", "MPO"):
                raise ValueError("Culling currently accepts JPEG only")
            container_format = image.format
            # Camera JPEGs may include MPF auxiliary images. Score the primary
            # image only, never an auxiliary preview or a combined rendition.
            image.seek(0)
            metadata = parse_metadata(image.getexif())
            raw_size = image.size
            oriented = ImageOps.exif_transpose(image)
            try:
                pixels = np.array(oriented.convert("RGB"), dtype=np.uint8)
            finally:
                oriented.close()
        after = os.fstat(stream.fileno())
        if _signature(before) != _signature(after) or _signature(after) != _signature(path.stat()):
            raise RuntimeError("JPEG changed during read; rescan before analysis")
    pixels.setflags(write=False)
    return JpegInput(path, digest, before.st_size, before.st_mtime_ns, raw_size,
                     container_format, metadata, pixels)


def _box(bbox: Sequence[float]) -> tuple[float, float, float, float]:
    if len(bbox) != 4 or not all(math.isfinite(v) for v in bbox):
        raise ValueError("Expected finite XYXY coordinates")
    x1, y1, x2, y2 = map(float, bbox)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Empty or reversed box")
    return x1, y1, x2, y2


def orient_box(
    bbox: Sequence[float], *, raw_size: tuple[int, int], orientation: int
) -> tuple[float, float, float, float]:
    """Map raw pixel-edge coordinates to EXIF-oriented pixel-edge coordinates.

    Only call for boxes in the un-oriented frame, never already-oriented boxes.
    """
    x1, y1, x2, y2 = _box(bbox)
    width, height = raw_size
    if orientation not in range(1, 9) or not all(math.isfinite(v) and v > 0 for v in raw_size):
        raise ValueError("Invalid frame")
    def point(x, y):
        return {
            1: (x, y), 2: (width - x, y), 3: (width - x, height - y),
            4: (x, height - y), 5: (y, x), 6: (height - y, x),
            7: (height - y, width - x), 8: (y, width - x),
        }[orientation]
    corners = [point(x, y) for x in (x1, x2) for y in (y1, y2)]
    return (min(p[0] for p in corners), min(p[1] for p in corners),
            max(p[0] for p in corners), max(p[1] for p in corners))


def preview_box_to_original(
    bbox: Sequence[float], *, preview_size: tuple[int, int], original_size: tuple[int, int]
) -> tuple[float, float, float, float]:
    """Map a plain resized, oriented preview; padded/letterboxed inputs forbidden."""
    x1, y1, x2, y2 = _box(bbox)
    if not all(math.isfinite(v) and v > 0 for v in (*preview_size, *original_size)):
        raise ValueError("Invalid frame dimensions")
    sx, sy = original_size[0] / preview_size[0], original_size[1] / preview_size[1]
    return x1 * sx, y1 * sy, x2 * sx, y2 * sy
