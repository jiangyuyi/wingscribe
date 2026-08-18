import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.inaturalist_prior import (
    build_province_annual_prior,
    build_national_month_prior,
    fetch_observation_province_assignments,
    fetch_species_province_counts,
    fetch_species_month_counts,
    load_manifest_candidate_labels,
    load_province_catalog,
    resolve_province_places,
    write_province_assignments,
    write_prior_file,
)
from src.evaluation.local_directory import load_candidate_labels


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a time-isolated iNaturalist China species prior."
    )
    candidates = parser.add_mutually_exclusive_group(required=True)
    candidates.add_argument("--candidate-manifest", type=Path)
    candidates.add_argument("--candidate-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--region-mode",
        choices=["province-annual", "national-month"],
        default="province-annual",
        help="Province annual is the recommended path; national month is retained for reproducibility",
    )
    parser.add_argument(
        "--province-catalog",
        type=Path,
        default=PROJECT_ROOT / "data/references/inaturalist_china_provinces.json",
    )
    parser.add_argument(
        "--province-assignment-output",
        type=Path,
        help="Optional sample-to-province sidecar; requires --candidate-manifest",
    )
    parser.add_argument("--cutoff-date", default="2021-12-31")
    parser.add_argument("--smoothing-alpha", type=float, default=1.0)
    parser.add_argument("--max-api-records", type=int, default=20000)
    parser.add_argument("--request-delay", type=float, default=0.1)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.province_assignment_output and not args.candidate_manifest:
        raise ValueError("--province-assignment-output requires --candidate-manifest")
    if args.province_assignment_output and args.region_mode != "province-annual":
        raise ValueError("Province assignments require --region-mode province-annual")
    labels = (
        load_manifest_candidate_labels(args.candidate_manifest)
        if args.candidate_manifest
        else load_candidate_labels(args.candidate_file)
    )
    headers = {"User-Agent": "WingScribe-public-evaluation/1.0"}
    timeout = httpx.Timeout(60.0, connect=30.0)
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        if args.region_mode == "province-annual":
            catalog_source, catalog_regions = load_province_catalog(args.province_catalog)
            regions = resolve_province_places(
                client,
                catalog_source,
                catalog_regions,
                request_delay_seconds=args.request_delay,
            )
            counts, source = fetch_species_province_counts(
                client,
                regions,
                cutoff_date=args.cutoff_date,
                max_api_records=args.max_api_records,
                request_delay_seconds=args.request_delay,
            )
        else:
            regions = ()
            counts, source = fetch_species_month_counts(
                client,
                cutoff_date=args.cutoff_date,
                max_api_records=args.max_api_records,
                request_delay_seconds=args.request_delay,
            )
    if source["truncated"]:
        raise RuntimeError(
            "iNaturalist species-count aggregation was truncated; increase --max-api-records"
        )
    prior = (
        build_province_annual_prior(
            counts,
            labels,
            regions,
            source,
            smoothing_alpha=args.smoothing_alpha,
        )
        if args.region_mode == "province-annual"
        else build_national_month_prior(
            counts,
            labels,
            source,
            smoothing_alpha=args.smoothing_alpha,
        )
    )
    write_prior_file(prior, args.output)
    assignment_summary = None
    if args.province_assignment_output:
        manifest_path = args.candidate_manifest.resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
            assignments, assignment_summary = fetch_observation_province_assignments(
                client,
                manifest.get("samples") or [],
                regions,
                request_delay_seconds=args.request_delay,
            )
        assignment_source = {
            "name": "iNaturalist observation place_ids",
            "api_url": "https://api.inaturalist.org/v1/observations",
            "regions": source["regions"],
            **assignment_summary,
        }
        write_province_assignments(
            assignments,
            assignment_source,
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            args.province_assignment_output,
        )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "source": prior["source"],
                "records": len(prior["records"]),
                "province_assignment_output": (
                    str(args.province_assignment_output.resolve())
                    if args.province_assignment_output
                    else None
                ),
                "province_assignment_summary": assignment_summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
