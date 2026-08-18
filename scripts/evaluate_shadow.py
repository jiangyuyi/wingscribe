import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import (
    begin_hardware_measurement,
    finish_hardware_measurement,
    load_candidate_labels,
    load_local_directory,
    run_benchmark,
)
from src.recognition.inference_local import LocalBirdRecognizer
from src.recognition.model_registry import MODEL_REGISTRY, get_model_spec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an unlabeled shadow benchmark on a local image directory."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--candidate-file",
        type=Path,
        default=Path("config/dictionaries/china_bird_list.txt"),
    )
    parser.add_argument("--model", choices=list(MODEL_REGISTRY), default="bioclip-2")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--seed", type=int, default=20260818)
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    model_spec = get_model_spec(args.model)
    batch_size = model_spec.recommended_eval_batch_size if args.batch_size is None else args.batch_size
    if batch_size < 1:
        raise ValueError("--batch-size must be at least 1")
    if args.top_k < 1:
        raise ValueError("--top-k must be at least 1")

    labels = load_candidate_labels(args.candidate_file)
    dataset = load_local_directory(
        args.root,
        labels,
        recursive=not args.no_recursive,
        limit=args.limit,
        seed=args.seed,
    )
    recognizer = LocalBirdRecognizer(model_name=args.model, device=args.device)
    hardware_measurement = begin_hardware_measurement(recognizer.device)
    result = run_benchmark(
        dataset,
        recognizer,
        batch_size=batch_size,
        top_k=args.top_k,
        run_metadata={
            "evaluation_type": "unlabeled_shadow",
            "model": args.model,
            "model_architecture": model_spec.architecture,
            "model_experimental": model_spec.experimental,
            "batch_size_was_defaulted": args.batch_size is None,
            "requested_device": args.device,
            "actual_device": recognizer.device,
            "seed": args.seed,
        },
    )
    result.run["hardware"] = finish_hardware_measurement(hardware_measurement)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.metrics, ensure_ascii=False, indent=2))
    print(f"Report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
