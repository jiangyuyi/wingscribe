import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import run_quality_benchmark, write_quality_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate image-quality metrics under repeatable degradations.")
    parser.add_argument("--root", type=Path, required=True, help="Directory containing evaluation images")
    parser.add_argument("--glob", default="**/*", help="Image glob relative to --root")
    parser.add_argument("--limit", type=int, help="Evaluate only the first N sorted images")
    parser.add_argument("--seed", type=int, default=20260817)
    parser.add_argument("--output", type=Path, required=True, help="JSON report path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
    image_paths = sorted(
        path for path in args.root.glob(args.glob) if path.is_file() and path.suffix.lower() in extensions
    )
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1")
        image_paths = image_paths[: args.limit]
    if not image_paths:
        raise ValueError("No supported images found")

    report = run_quality_benchmark(image_paths, seed=args.seed)
    write_quality_report(report, args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
