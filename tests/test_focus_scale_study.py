"""Geometric counterexamples, not synthetic claims about focus accuracy."""
from dataclasses import asdict
import json

import pytest

from scripts.study_focus_scale import geometry_comparison, replay
from src.core.culling import CaptureGroup
from src.core.focus import FocusEvidence, FocusPolicy, rank_group


@pytest.mark.parametrize("sizes, expected", [
    ([(100, 100), (201, 201)], (False, False, False)),  # Actual uniform zoom.
    ([(100, 100), (200, 200)], (True, True, True)),
    ([(100, 300), (300, 100)], (False, True, True)),  # Rotation/shape ambiguity.
    ([(100, 100), (300, 100)], (False, True, False)),  # Area gate misses one-side growth.
    ([(100, 800), (300, 800)], (False, True, True)),  # Both alternatives hide width error.
    ([(100, 100), (1000, 10)], (False, True, False)),  # Equal area is not equal scale.
])
def test_geometry_counterexamples(sizes, expected):
    result = geometry_comparison([(0, 0, w, h) for w, h in sizes])
    assert tuple(result["passes"].values()) == expected


def test_unknown_is_not_a_pass_and_singleton_has_no_scale_information():
    assert geometry_comparison([])["passes"] == {}
    single = geometry_comparison([(0, 0, 50, 80)])
    assert single["eligible_count"] == 1
    assert all(single["passes"].values())


@pytest.mark.parametrize("box", [(0, 0, 0, 20), (0, 0, float("nan"), 20)])
def test_malformed_geometry_rejected(box):
    with pytest.raises(ValueError):
        geometry_comparison([box])


def test_replay_preserves_abstention_missing_member_and_near_ties():
    group = CaptureGroup("g", ("a", "b", "c"), "time_candidate")
    records = [FocusEvidence(k, "sha", "v", FocusPolicy(), status, (), None, bounds, {}, score)
               for k, status, bounds, score in [
                   ("a", "rankable", (0, 0, 100, 300), 1),
                   ("b", "rankable", (0, 0, 300, 100), 1.02),
                   ("c", "review", None, None)]]
    report = json.loads(json.dumps({"report_id": "r", "groups": [{**asdict(group),
        "ranking": asdict(rank_group(group, records))}],
        "items": {e.version_id: {"filename": e.version_id, "evidence": asdict(e)} for e in records}}))
    before = json.dumps(report, sort_keys=True)
    row = replay(report)["groups"][0]
    assert row["baseline_recommended"] == []
    assert row["diagnostic_only_top3"] == ["a", "b"]
    assert row["diagnostic_only_ties"] == (("a", "b"),)
    assert row["unranked"] == ["c"]
    assert json.dumps(report, sort_keys=True) == before
    report["groups"][0]["ranking"]["recommended"] = ["a"]
    with pytest.raises(ValueError, match="no longer matches"):
        replay(report)
