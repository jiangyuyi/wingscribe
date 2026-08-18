import argparse
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.inaturalist import (
    build_manifest,
    download_manifest_images,
    fetch_observation_pool,
    write_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a frozen, license-aware iNaturalist China bird evaluation manifest."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-count", type=int, default=600)
    parser.add_argument("--max-per-species", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--cutoff-date", default="2025-12-31")
    parser.add_argument("--max-api-records", type=int, default=20000)
    parser.add_argument("--request-delay", type=float, default=0.1)
    parser.add_argument("--skip-download", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    headers = {"User-Agent": "WingScribe-public-evaluation/1.0"}
    timeout = httpx.Timeout(60.0, connect=30.0)
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        records, source = fetch_observation_pool(
            client,
            cutoff_date=args.cutoff_date,
            max_api_records=args.max_api_records,
            request_delay_seconds=args.request_delay,
        )
        manifest = build_manifest(
            records,
            source,
            sample_count=args.sample_count,
            max_per_species=args.max_per_species,
            seed=args.seed,
        )
        write_manifest(manifest, args.output)
        download = None
        if not args.skip_download:
            download = download_manifest_images(manifest, args.output, client)
            write_manifest(manifest, args.output)

    summary = {
        "output": str(args.output.resolve()),
        "source": source,
        "selection": manifest["selection"],
        "download": download,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if download and download["failed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
