"""Explicit culling advice modes; human choices are never inputs or outputs."""
from dataclasses import asdict

from src.core.culling import CaptureGroup
from src.core.focus import FocusEvidence, FocusPolicy, rank_group

MODES = ("safe", "assist", "relaxed")
MODE_VERSION = "focus-advice-v1"


def rank_with_mode(group, evidence, *, mode="safe", tie_fraction=0.05, max_side_ratio=2.0):
    if mode not in MODES:
        raise ValueError("Unknown focus mode")
    records = list(evidence)
    baseline = rank_group(group, records, tie_fraction=tie_fraction, max_side_ratio=max_side_ratio)
    ranking = baseline
    mismatch = "subject_scale_mismatch" in baseline.warnings
    if mode != "safe" and mismatch:
        eligible = [e for e in records if e.status == "rankable"]
        widths = [e.bounds[2] - e.bounds[0] for e in eligible]
        heights = [e.bounds[3] - e.bounds[1] for e in eligible]
        ranking = rank_group(group, records, tie_fraction=tie_fraction,
                             max_side_ratio=max(max_side_ratio, max(widths)/min(widths), max(heights)/min(heights)))
    result = asdict(ranking)
    # Keep the configured guard, not the internal diagnostic bypass tolerance.
    result["max_side_ratio"] = max_side_ratio
    result.update(mode=mode, mode_version=MODE_VERSION, scale_guard_triggered=mismatch)
    warnings = list(result["warnings"])
    if mismatch and "subject_scale_mismatch" not in warnings:
        warnings.append("subject_scale_mismatch")
    if mode == "assist":
        result["recommended"] = ()
        warnings.append("manual_selection_only")
    if mode == "relaxed":
        warnings.append("experimental_recommendation_review_required")
    result["warnings"] = tuple(warnings)
    return result


def report_modes(group, items):
    evidence = []
    for key in group["version_ids"]:
        value = dict(items[key]["evidence"])
        value["policy"] = FocusPolicy(**value["policy"])
        evidence.append(FocusEvidence(**value))
    capture_group = CaptureGroup(group["group_id"], tuple(group["version_ids"]), group["reason"])
    return {mode: rank_with_mode(capture_group, evidence, mode=mode,
            tie_fraction=group["ranking"]["tie_fraction"],
            max_side_ratio=group["ranking"]["max_side_ratio"]) for mode in MODES}
