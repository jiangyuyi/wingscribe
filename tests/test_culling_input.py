import hashlib
from datetime import timedelta

import numpy as np
from PIL import Image
import pytest

from src.core.culling import group_captures, largest_subject
from src.core.culling_input import (
    orient_box, parse_metadata, preview_box_to_original, read_jpeg,
)


def exif_data(orientation=1, **changes):
    exif = Image.Exif()
    exif[274], exif[271], exif[272] = orientation, "Test", "Camera"
    nested = {36867: "2026:10:01 08:15:30", 37521: "123", 36881: "+08:00", 42033: "body-1"}
    nested.update({int(k): v for k, v in changes.items()})
    exif[34665] = nested
    loaded = Image.Exif()
    loaded.load(exif.tobytes())
    return loaded


def write_jpeg(path, exif=None):
    pixels = np.random.default_rng(42).integers(0, 256, (40, 60, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(path, format="JPEG", quality=95, exif=exif or Image.Exif())
    return path


def test_nested_metadata_and_capture_adapter(tmp_path):
    path = write_jpeg(tmp_path / "相机.JPG", exif_data())
    frame = read_jpeg(path)
    meta = frame.metadata
    assert meta.captured_at.isoformat() == "2026-10-01T08:15:30.123000+08:00"
    assert meta.subsecond_digits == "123"
    assert meta.camera_identity_kind == "body_serial"
    assert meta.warnings == ()
    capture = frame.capture(version_id="v1", source_id="s1", directory_key="trip")
    assert capture.captured_at == meta.captured_at
    assert len(group_captures([capture], max_gap_seconds=2, max_span_seconds=30)) == 1


@pytest.mark.parametrize("orientation", range(1, 9))
def test_all_orientations_pixel_and_box_agreement(tmp_path, orientation):
    path = write_jpeg(tmp_path / "bird.jpg", exif_data(orientation))
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    before = path.stat()
    with Image.open(path) as image:
        raw = np.array(image.convert("RGB"))
    expected = {
        1: raw, 2: raw[:, ::-1], 3: raw[::-1, ::-1], 4: raw[::-1],
        5: raw.transpose(1, 0, 2), 6: np.rot90(raw, -1),
        7: raw.transpose(1, 0, 2)[::-1, ::-1], 8: np.rot90(raw),
    }[orientation]
    frame = read_jpeg(path)
    np.testing.assert_array_equal(frame.pixels, expected)
    assert frame.raw_size == (60, 40)
    # A raw rectangle mask is transformed independently using NumPy.
    mask = np.zeros_like(raw)
    mask[4:17, 3:21] = 1
    transforms = {
        1: lambda a: a, 2: lambda a: a[:, ::-1], 3: lambda a: a[::-1, ::-1],
        4: lambda a: a[::-1], 5: lambda a: a.transpose(1, 0, 2),
        6: lambda a: np.rot90(a, -1),
        7: lambda a: a.transpose(1, 0, 2)[::-1, ::-1], 8: lambda a: np.rot90(a),
    }
    yy, xx = np.nonzero(transforms[orientation](mask)[:, :, 0])
    expected_box = (xx.min(), yy.min(), xx.max() + 1, yy.max() + 1)
    box = orient_box((3, 4, 21, 17), raw_size=frame.raw_size, orientation=orientation)
    assert box == expected_box
    primary = largest_subject([box], width=frame.size[0], height=frame.size[1])
    crop, bounds = frame.crop(primary.bbox)
    x1, y1, x2, y2 = bounds
    np.testing.assert_array_equal(crop, expected[y1:y2, x1:x2])
    assert not crop.flags.writeable and not frame.pixels.flags.writeable
    assert frame.sha256 == original_hash == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (path.stat().st_size, path.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def test_missing_metadata_does_not_use_file_time_or_modify_date(tmp_path):
    exif = Image.Exif()
    exif[306] = "2026:10:01 12:00:00"
    frame = read_jpeg(write_jpeg(tmp_path / "missing.jpg", exif))
    assert frame.metadata.captured_at is None
    assert frame.metadata.camera_key is None
    assert "orientation_missing_assumed_1" in frame.metadata.warnings


def test_camera_mpo_jpeg_uses_primary_only(tmp_path):
    path = tmp_path / "camera.JPG"
    primary = Image.new("RGB", (60, 40), (200, 20, 30))
    auxiliary = Image.new("RGB", (12, 8), (0, 0, 255))
    primary.save(path, format="MPO", save_all=True, append_images=[auxiliary], exif=exif_data(6))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as image:
        assert image.n_frames == 2
        expected = np.rot90(np.array(image.convert("RGB")), -1)
    frame = read_jpeg(path)
    assert frame.container_format == "MPO"
    assert frame.raw_size == (60, 40) and frame.size == (40, 60)
    np.testing.assert_array_equal(frame.pixels, expected)
    assert before == frame.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("changes", [
    {"36867": "2026:02:30 08:15:30"}, {"36867": "2026-10-01"},
    {"37521": "abc"}, {"36881": "+24:00"}, {"36881": "+08:99"}, {"36881": "UTC"},
])
def test_malformed_capture_time_stays_unknown(changes):
    metadata = parse_metadata(exif_data(**changes))
    assert metadata.captured_at is None
    assert "invalid_capture_time" in metadata.warnings


def test_precision_offset_and_camera_identity():
    metadata = parse_metadata(exif_data(**{"37521": "123456789", "36881": "-03:30"}))
    assert metadata.captured_at.microsecond == 123456
    assert metadata.captured_at.utcoffset() == -timedelta(hours=3, minutes=30)
    assert metadata.subsecond_digits == "123456789"
    assert "subsecond_truncated_to_microseconds" in metadata.warnings
    first = parse_metadata(exif_data())
    second = parse_metadata(exif_data(**{"42033": "body-2"}))
    assert first.camera_key != second.camera_key
    no_serial = parse_metadata(exif_data(**{"42033": "", "36881": ""}))
    assert no_serial.camera_identity_kind == "make_model"
    assert no_serial.captured_at.tzinfo is None
    assert "camera_serial_missing_same_model_may_merge" in no_serial.warnings


def test_fractional_preview_mapping_clipping_and_no_resize(tmp_path):
    frame = read_jpeg(write_jpeg(tmp_path / "frame.jpg"))
    box = preview_box_to_original((-0.2, 1.1, 7.1, 8.2),
                                  preview_size=(15, 10), original_size=frame.size)
    crop, bounds = frame.crop(box)
    assert bounds == (0, 4, 29, 33)
    np.testing.assert_array_equal(crop, frame.pixels[4:33, :29])
    with pytest.raises(ValueError):
        frame.crop((100, 100, 200, 200))


@pytest.mark.parametrize("box", [(1, 1, 0, 0), (0, 0, float("nan"), 1), (1, 2)])
def test_bad_boxes_fail_explicitly(box, tmp_path):
    with pytest.raises(ValueError):
        orient_box(box, raw_size=(60, 40), orientation=1)
    with pytest.raises(ValueError):
        preview_box_to_original(box, preview_size=(30, 20), original_size=(60, 40))


def test_bad_frames_rejected(tmp_path):
    with pytest.raises(ValueError):
        orient_box((0, 0, 1, 1), raw_size=(0, 40), orientation=1)
    with pytest.raises(ValueError):
        preview_box_to_original((0, 0, 1, 1), preview_size=(0, 20), original_size=(60, 40))
    with pytest.raises(ValueError, match="orientation"):
        read_jpeg(write_jpeg(tmp_path / "bad.jpg", exif_data(9)))
    path = tmp_path / "fake.jpg"
    Image.new("RGB", (10, 10)).save(path, format="PNG")
    with pytest.raises(ValueError, match="JPEG only"):
        read_jpeg(path)
    path.write_bytes(b"not a photo")
    with pytest.raises(OSError):
        read_jpeg(path)


def test_modified_during_read_is_rejected(tmp_path, monkeypatch):
    path = write_jpeg(tmp_path / "changing.jpg")
    real_stat = type(path).stat
    def altered_stat(self, **kwargs):
        stat = real_stat(self, **kwargs)
        if self == path:
            from types import SimpleNamespace
            return SimpleNamespace(st_dev=stat.st_dev, st_ino=stat.st_ino, st_size=stat.st_size + 1,
                                   st_mtime_ns=stat.st_mtime_ns, st_ctime_ns=stat.st_ctime_ns)
        return stat
    monkeypatch.setattr(type(path), "stat", altered_stat)
    with pytest.raises(RuntimeError, match="changed"):
        read_jpeg(path)
