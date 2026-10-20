from dataclasses import replace
from pathlib import Path
import json

import cv2
import numpy as np
import pytest

from src.core.culling import CaptureGroup
from src.core.culling_input import CaptureMetadata, JpegInput
from src.core.focus import FocusPolicy, analyze_focus, rank_group


def texture():
    y, x = np.indices((192, 192))
    return np.uint8(128 + 45 * np.sin(x / 3) + 30 * np.sin(y / 7))


def frame(gray):
    pixels = np.repeat(gray[:, :, None], 3, axis=2)
    return JpegInput(Path("test.jpg"), "source-hash", 123, 456,
                     (gray.shape[1], gray.shape[0]), "JPEG",
                     CaptureMetadata(None, None, None, "missing", None, None, 1, ()), pixels)


def analyze(gray, key="a"):
    return analyze_focus(frame(gray), [(0, 0, gray.shape[1], gray.shape[0])], version_id=key)


def test_blur_and_motion_reduce_relative_detail():
    sharp = texture()
    blur = cv2.GaussianBlur(sharp, (0, 0), 5)
    motion = cv2.filter2D(sharp, -1, np.ones((1, 19), np.float32) / 19)
    a, b, c = analyze(sharp), analyze(blur), analyze(motion)
    assert all(e.status == "rankable" for e in (a, b, c))
    assert a.score > b.score and a.score > c.score
    assert a.input_sha256 == "source-hash"
    json.dumps(a.to_dict(), allow_nan=False)


def test_noise_cannot_promote_blurry_candidate():
    blur = cv2.GaussianBlur(texture(), (0, 0), 5).astype(float)
    noisy = np.uint8(np.clip(blur + np.random.default_rng(42).normal(0, 22, blur.shape), 0, 255))
    result = analyze(noisy)
    assert result.status == "review" and result.score is None
    assert "noise_or_fine_texture" in result.reasons


@pytest.mark.parametrize("value", [0, 128, 255])
def test_uniform_and_extreme_exposure_are_not_sharp(value):
    result = analyze(np.full((64, 64), value, np.uint8))
    assert result.status == "review" and result.score is None
    assert "insufficient_structure" in result.reasons
    if value != 128:
        assert "severe_clipping" in result.reasons


def test_small_or_missing_bird_is_not_blur():
    result = analyze(np.full((15, 20), 100, np.uint8))
    assert result.reasons == ("subject_too_small",)
    missing = analyze_focus(frame(texture()), [], version_id="a")
    assert missing.reasons == ("no_valid_subject",)
    assert missing.bounds is None and missing.score is None


def test_only_largest_subject_region_matters_and_input_unchanged():
    image = frame(texture())
    before = image.pixels.copy()
    boxes = [(0, 0, 10, 10), (30, 40, 150, 160)]
    first = analyze_focus(image, boxes, version_id="a")
    altered = image.pixels.copy()
    altered[:30] = 255
    second = analyze_focus(replace(image, pixels=altered), boxes, version_id="a")
    assert first == second
    assert first.detection_index == 1 and first.bounds == (30, 40, 150, 160)
    np.testing.assert_array_equal(image.pixels, before)


def records(scores):
    base = analyze(texture())
    return [replace(base, version_id=str(i), score=score) for i, score in enumerate(scores)]


def group(count):
    return CaptureGroup("group", tuple(str(i) for i in range(count)), "time_candidate")


def test_top_three_missing_and_review_keep_all_members():
    rows = records([1, 4, 2, 3, 5])
    rows[4] = replace(rows[4], status="review", score=None, reasons=("noise_or_fine_texture",))
    result = rank_group(group(6), rows)
    assert result.recommended == ("1", "3", "2")
    assert result.ranked == ("1", "3", "2", "0")
    assert result.unranked == ("4", "5")
    assert "relative_ranking_not_focus_verdict" in result.warnings


def test_ties_preserve_capture_order_and_expose_boundary_alternatives():
    result = rank_group(group(5), reversed(records([1, 1.02, 1.01, 1.03, 0.5])))
    assert result.recommended == ("0", "1", "2")
    assert result.tie_sets == (("0", "1", "2", "3"),)
    assert "near_ties_compare_manually" in result.warnings


def test_under_three_and_all_unknown_do_not_fill_slots():
    assert rank_group(group(2), records([1, 2])).recommended == ("1", "0")
    result = rank_group(group(2), [])
    assert result.recommended == ()
    assert result.unranked == ("0", "1")
    assert "no_rankable_subjects" in result.warnings


def test_large_size_difference_blocks_native_scale_comparison():
    rows = records([1, 2])
    rows[1] = replace(rows[1], bounds=(0, 0, 32, 32))
    result = rank_group(group(2), rows)
    assert result.recommended == () and result.unranked == ("0", "1")
    assert "subject_scale_mismatch" in result.warnings


@pytest.mark.parametrize("change", [
    {"score": float("nan")}, {"score": float("inf")}, {"score": -1}, {"bounds": None},
])
def test_invalid_rankable_evidence_rejected(change):
    with pytest.raises(ValueError):
        rank_group(group(1), [replace(records([1])[0], **change)])


def test_identity_and_algorithm_mismatch_rejected():
    with pytest.raises(ValueError):
        rank_group(group(1), records([1, 2]))
    with pytest.raises(ValueError):
        rank_group(group(1), records([1]) * 2)
    rows = records([1, 2])
    rows[1] = replace(rows[1], algorithm="different")
    with pytest.raises(ValueError):
        rank_group(group(2), rows)
    with pytest.raises(ValueError):
        analyze_focus(frame(texture()), [], version_id="")


@pytest.mark.parametrize("kwargs", [
    {"min_side": 8}, {"max_noise": float("nan")}, {"max_clipped_fraction": 2},
])
def test_invalid_policy_rejected(kwargs):
    with pytest.raises(ValueError):
        FocusPolicy(**kwargs)


def test_invalid_ranking_parameters_rejected():
    with pytest.raises(ValueError):
        rank_group(group(0), [], tie_fraction=float("nan"))
    with pytest.raises(ValueError):
        rank_group(group(0), [], max_side_ratio=0)
