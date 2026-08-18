import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import (
    CUBCropPreparer,
    MultiCropPredictor,
    PriorBatchPredictor,
    begin_hardware_measurement,
    finish_hardware_measurement,
    load_cub_dataset,
    load_inaturalist_manifest,
    run_benchmark,
    select_evaluation_subset,
)
from src.recognition.inference_local import LocalBirdRecognizer
from src.recognition.model_registry import get_model_spec
from src.recognition.prior import load_prior_provider


def _batch_predictor_metadata(batch_predictor) -> dict:
    return {
        "multicrop_margins": (
            list(batch_predictor.margins)
            if getattr(batch_predictor, "margins", None) is not None
            else None
        ),
        "multicrop_weights": (
            list(batch_predictor.weights)
            if getattr(batch_predictor, "weights", None) is not None
            else None
        ),
        "view_encode_batch_size": getattr(batch_predictor, "encode_batch_size", None),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a repeatable WingScribe public-dataset benchmark.")
    parser.add_argument("--dataset", choices=["cub", "inaturalist-manifest"], default="cub")
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Extracted CUB directory or frozen iNaturalist manifest path",
    )
    parser.add_argument("--split", choices=["train", "test", "all"], default="test")
    parser.add_argument(
        "--model",
        choices=["bioclip", "bioclip-2", "bioclip-2.5-vith14"],
        default="bioclip-2",
    )
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Image batch size; defaults to a conservative value for the selected model",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--image-mode",
        choices=["full", "bbox", "bbox-jitter", "multicrop-2", "multicrop-3"],
        default="bbox",
    )
    parser.add_argument("--bbox-margin", type=float, default=0.15, help="Fraction added around each bbox edge")
    parser.add_argument("--bbox-jitter", type=float, default=0.10, help="Maximum deterministic bbox perturbation")
    parser.add_argument("--seed", type=int, default=20260817)
    parser.add_argument("--limit", type=int, help="Evaluate a deterministic subset of N samples")
    parser.add_argument("--observed-on-from", help="Inclusive ISO date filter for iNaturalist manifests")
    parser.add_argument(
        "--province-assignments",
        type=Path,
        help="Versioned sample-to-province sidecar bound to the iNaturalist manifest",
    )
    parser.add_argument("--prior-file", type=Path, help="Experimental versioned species-prior JSON")
    parser.add_argument("--prior-weight", type=float, default=0.25)
    parser.add_argument("--prior-location-confidence", type=float, default=1.0)
    parser.add_argument("--prior-max-adjustment", type=float, default=1.0)
    parser.add_argument(
        "--sample-strategy",
        choices=["stratified", "sequential"],
        default="stratified",
        help="Subset selection used with --limit; stratified avoids early-class bias",
    )
    parser.add_argument("--output", type=Path, required=True, help="JSON report path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    model_spec = get_model_spec(args.model)
    batch_size = (
        model_spec.recommended_eval_batch_size
        if args.batch_size is None
        else args.batch_size
    )
    if batch_size < 1:
        raise ValueError("--batch-size must be at least 1")
    if args.dataset == "cub":
        dataset = load_cub_dataset(args.root, split=args.split)
    else:
        if args.image_mode != "full":
            raise ValueError("iNaturalist manifests currently require --image-mode full")
        dataset = load_inaturalist_manifest(
            args.root,
            observed_on_from=args.observed_on_from,
            province_assignments_path=args.province_assignments,
        )
    if args.limit is not None:
        dataset = select_evaluation_subset(
            dataset,
            args.limit,
            strategy=args.sample_strategy,
            seed=args.seed,
        )

    image_preparer = None
    if args.image_mode in {"bbox", "bbox-jitter"}:
        jitter = args.bbox_jitter if args.image_mode == "bbox-jitter" else 0.0
        image_preparer = CUBCropPreparer(
            margin=args.bbox_margin,
            jitter=jitter,
            seed=args.seed,
            work_root=args.output.parent / ".tmp",
        )
    recognizer = LocalBirdRecognizer(model_name=args.model, device=args.device)
    hardware_measurement = begin_hardware_measurement(recognizer.device)
    batch_predictor = None
    multicrop_presets = {
        "multicrop-2": ((0.0, 0.15), (0.35, 0.65)),
        "multicrop-3": ((0.0, 0.15, 0.35), (0.25, 0.55, 0.20)),
    }
    if args.image_mode in multicrop_presets:
        margins, weights = multicrop_presets[args.image_mode]
        batch_predictor = MultiCropPredictor(
            recognizer,
            margins,
            weights,
            work_root=args.output.parent / ".tmp",
            encode_batch_size=batch_size,
        )
    prior_metadata = None
    if args.prior_file:
        if args.dataset != "inaturalist-manifest" or args.image_mode != "full":
            raise ValueError("Species priors currently require an iNaturalist manifest in full mode")
        provider = load_prior_provider(args.prior_file)
        batch_predictor = PriorBatchPredictor(
            recognizer,
            provider,
            weight=args.prior_weight,
            location_confidence=args.prior_location_confidence,
            max_adjustment=args.prior_max_adjustment,
        )
        prior_metadata = {
            "file_sha256": hashlib.sha256(args.prior_file.read_bytes()).hexdigest(),
            "source": provider.source,
            "weight": args.prior_weight,
            "location_confidence": args.prior_location_confidence,
            "max_adjustment": args.prior_max_adjustment,
        }
    predictor_metadata = _batch_predictor_metadata(batch_predictor)
    result = run_benchmark(
        dataset,
        recognizer,
        batch_size=batch_size,
        top_k=args.top_k,
        run_metadata={
            "model": args.model,
            "model_architecture": model_spec.architecture,
            "model_experimental": model_spec.experimental,
            "batch_size_was_defaulted": args.batch_size is None,
            "requested_device": args.device,
            "actual_device": recognizer.device,
            "image_mode": args.image_mode,
            "bbox_margin": args.bbox_margin if image_preparer else None,
            "bbox_jitter": args.bbox_jitter if args.image_mode == "bbox-jitter" else 0.0,
            "seed": args.seed,
            **predictor_metadata,
            "prior": prior_metadata,
        },
        image_preparer=image_preparer,
        batch_predictor=batch_predictor,
    )
    result.run["hardware"] = finish_hardware_measurement(hardware_measurement)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.metrics, ensure_ascii=False, indent=2))
    print(f"Report: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
