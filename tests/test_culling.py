from datetime import datetime, timedelta, timezone

import pytest

from src.core.culling import Capture, group_captures, largest_subject, RECOMMENDATION_COUNT


def capture(name, seconds=0, **changes):
    values = dict(version_id=name, source_id="source", directory_key="trip",
                  camera_key="camera", captured_at=datetime(2026, 10, 1) + timedelta(seconds=seconds))
    values.update(changes)
    return Capture(**values)


def grouped(items, gap=2, span=4):
    return group_captures(items, max_gap_seconds=gap, max_span_seconds=span)


def members(groups):
    return {group.version_ids for group in groups}


def test_subsecond_order_boundary_and_long_chain():
    items = [capture("a"), capture("b", 0.5), capture("c", 2.5),
             capture("d", 4.5), capture("e", 7)]
    assert members(grouped(items)) == {("a", "b", "c"), ("d",), ("e",)}
    assert grouped(items) == grouped(reversed(items))


@pytest.mark.parametrize("change", [
    {"source_id": "other"}, {"directory_key": "other"}, {"camera_key": "other"},
    {"captured_at": datetime(2026, 10, 1, tzinfo=timezone.utc)},
])
def test_distinct_contexts_never_merge(change):
    assert len(grouped([capture("a"), capture("b", **change)])) == 2


@pytest.mark.parametrize("change", [{"captured_at": None}, {"camera_key": None}])
def test_missing_evidence_stays_singleton(change):
    groups = grouped([capture("a", **change), capture("b", **change)])
    assert len(groups) == 2
    assert all(g.reason == "missing_capture_time_or_camera" for g in groups)


def test_offsets_compare_instants():
    a = capture("a", captured_at=datetime(2026, 10, 1, 8, tzinfo=timezone(timedelta(hours=8))))
    b = capture("b", captured_at=datetime(2026, 10, 1, 0, 0, 1, tzinfo=timezone.utc))
    assert members(grouped([b, a])) == {("a", "b")}


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_interval_rejected(value):
    with pytest.raises(ValueError):
        grouped([], gap=value)
    with pytest.raises(ValueError):
        grouped([], span=value)


def test_duplicates_rejected_and_empty_input_supported():
    with pytest.raises(ValueError, match="Duplicate"):
        grouped([capture("a"), capture("a")])
    assert grouped([]) == []
    assert RECOMMENDATION_COUNT == 3


def test_largest_visible_subject_without_padding_or_confidence():
    result = largest_subject([(-100, -100, 2, 2), (10, 10, 30, 40), (0, 0, 10, 10)],
                             width=100, height=100)
    assert result.detection_index == 1
    assert result.bbox == (10, 10, 30, 40)
    assert result.area_pixels == 600


def test_invalid_boxes_and_absent_bird_are_not_focus_failures():
    boxes = [(1, 1, 0, 0), (0, 0, float("nan"), 1), (200, 200, 300, 300), (1, 2)]
    assert largest_subject(boxes, width=100, height=100) is None
    assert largest_subject([], width=100, height=100) is None
    with pytest.raises(ValueError):
        largest_subject([], width=0, height=100)


def test_equal_subject_area_preserves_detection_order():
    result = largest_subject([(0, 0, 10, 10), (20, 20, 30, 30)], width=100, height=100)
    assert result.detection_index == 0
