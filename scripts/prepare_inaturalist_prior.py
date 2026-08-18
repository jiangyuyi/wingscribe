import argparse
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.inaturalist_prior import (
    build_national_month_prior,
    fetch_species_month_counts,
    load_manifest_candidate_labels,
    write_prior_file,
)
from src.evaluation.local_directory import load_candidate_labels


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a time-isolated iNaturalist China national/month species prior."
    )
    candidates = parser.add_mutually_exclusive_group(required=True)
    candidates.add_argument("--candidate-manifest", type=Path)
    candidates.add_argument("--candidate-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cutoff-date", default="2021-12-31")
    parser.add_argument("--smoothing-alpha", type=float, default=1.0)
    parser.add_argument("--max-api-records", type=int, default=20000)
    parser.add_argument("--request-delay", type=float, default=0.1)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    labels = (
        load_manifest_candidate_labels(args.candidate_manifest)
        if args.candidate_manifest
        else load_candidate_labels(args.candidate_file)
    )
    headers = {"User-Agent": "WingScribe-public-evaluation/1.0"}
    timeout = httpx.Timeout(60.0, connect=30.0)
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
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
    prior = build_national_month_prior(
        counts,
        labels,
        source,
        smoothing_alpha=args.smoothing_alpha,
    )
    write_prior_file(prior, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "source": prior["source"],
                "records": len(prior["records"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
