import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import load_cub_dataset, run_benchmark
from src.recognition.inference_local import LocalBirdRecognizer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a repeatable WingScribe public-dataset benchmark.")
    parser.add_argument("--dataset", choices=["cub"], default="cub")
    parser.add_argument("--root", type=Path, required=True, help="Extracted public dataset directory")
    parser.add_argument("--split", choices=["train", "test", "all"], default="test")
    parser.add_argument("--model", choices=["bioclip", "bioclip-2"], default="bioclip-2")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, help="Evaluate only the first N samples for a smoke test")
    parser.add_argument("--output", type=Path, required=True, help="JSON report path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dataset = load_cub_dataset(args.root, split=args.split)
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1")
        dataset = type(dataset)(
            name=dataset.name,
            samples=dataset.samples[: args.limit],
            candidate_labels=dataset.candidate_labels,
            metadata={**dataset.metadata, "limit": args.limit},
        )

    recognizer = LocalBirdRecognizer(model_name=args.model, device=args.device)
    result = run_benchmark(
        dataset,
        recognizer,
        batch_size=args.batch_size,
        top_k=args.top_k,
        run_metadata={"model": args.model, "requested_device": args.device, "actual_device": recognizer.device},
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.metrics, ensure_ascii=False, indent=2))
    print(f"Report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
