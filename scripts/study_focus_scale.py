"""Replay frozen focus reports; alternative gates are diagnostics, not recommendations."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.culling import CaptureGroup
from src.core.focus import FocusEvidence, FocusPolicy, rank_group


def geometry_comparison(bounds):
    """Compare fixed 2x linear-scale gates without claiming pose invariance."""
    sizes = []
    for x1, y1, x2, y2 in bounds:
        if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
            raise ValueError("Nonfinite bounds")
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            raise ValueError("Empty bounds")
        sizes.append((w, h))
    if not sizes:
        return {"eligible_count": 0, "ratios": {}, "passes": {}}

    def ratio(values):
        return max(values) / min(values)

    ratios = dict(
        width=ratio([w for w, h in sizes]),
        height=ratio([h for w, h in sizes]),
        area_linear=ratio([math.sqrt(w * h) for w, h in sizes]),
        diagonal=ratio([math.hypot(w, h) for w, h in sizes]),
    )
    return {"eligible_count": len(sizes), "ratios": ratios, "passes": {
        "separate_sides": max(ratios["width"], ratios["height"]) <= 2,
        "area_linear": ratios["area_linear"] <= 2,
        "diagonal": ratios["diagonal"] <= 2,
    }}


def replay(report):
    rows = []
    for group in report["groups"]:
        records = []
        for key in group["version_ids"]:
            value = dict(report["items"][key]["evidence"])
            value["policy"] = FocusPolicy(**value["policy"])
            value["reasons"] = tuple(value["reasons"])
            if value["bounds"] is not None:
                value["bounds"] = tuple(value["bounds"])
            records.append(FocusEvidence(**value))
        capture_group = CaptureGroup(group["group_id"], tuple(group["version_ids"]), group["reason"])
        tie = group["ranking"]["tie_fraction"]
        limit = group["ranking"]["max_side_ratio"]
        if limit != 2:
            raise ValueError("Study requires frozen 2x baseline")
        baseline = rank_group(capture_group, records, tie_fraction=tie, max_side_ratio=limit)
        if json.loads(json.dumps(asdict(baseline))) != group["ranking"]:
            raise ValueError("Frozen ranking no longer matches baseline")
        geo = geometry_comparison([e.bounds for e in records if e.status == "rankable"])
        # A labelled diagnostic bypass, never a replacement result or changed evidence.
        relaxed_limit = max(2, geo["ratios"].get("width", 1), geo["ratios"].get("height", 1))
        diagnostic = rank_group(capture_group, records, tie_fraction=tie, max_side_ratio=relaxed_limit)
        rows.append({"group_id": group["group_id"], "geometry": geo,
                     "baseline_recommended": list(baseline.recommended),
                     "diagnostic_only_top3": list(diagnostic.recommended),
                     "diagnostic_only_ties": diagnostic.tie_sets,
                     "unranked": list(diagnostic.unranked),
                     "filenames": {k: report["items"][k]["filename"] for k in group["version_ids"]}})
    return {"source_report_id": report["report_id"], "groups": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output file; frozen evidence must not be overwritten")
    results = [replay(json.loads(p.read_text(encoding="utf-8"))) for p in args.reports]
    if len({r["source_report_id"] for r in results}) != len(results):
        parser.error("Duplicate reports")
    output = {"scope": "diagnostic only; no calibrated scale or accuracy claim", "reports": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
    for result in results:
        rows = result["groups"]
        print(result["source_report_id"][:12], "groups", len(rows), "passes", {
            policy: sum(r["geometry"]["passes"].get(policy, False) for r in rows)
            for policy in ("separate_sides", "area_linear", "diagonal")})


if __name__ == "__main__":
    main()
