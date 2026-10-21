"""Create an isolated offline focus review, or evaluate exported human labels."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.focus import evaluate_labels, render_review


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--gap", type=float, default=2)
    parser.add_argument("--span", type=float, default=30)
    parser.add_argument("--labels", type=Path)
    args = parser.parse_args()
    if args.labels:
        report = json.loads((args.output / "report.json").read_text(encoding="utf-8"))
        labels = json.loads(args.labels.read_text(encoding="utf-8"))
        print(json.dumps(evaluate_labels(report, labels), ensure_ascii=False, indent=2))
        return
    if not args.input or not args.input.is_dir() or not args.model or not args.model.is_file():
        parser.error("Existing input directory and local model are required")
    if args.output.exists():
        parser.error("Output must be a new isolated directory")
    # Lazy imports: label evaluation does not load model dependencies.
    import numpy as np
    from PIL import Image
    from ultralytics import YOLO
    from src.core.culling import group_captures
    from src.core.culling_input import read_jpeg
    from src.core.focus import analyze_focus, rank_group
    from src.core.focus_modes import report_modes
    args.output.mkdir(parents=True)
    media = args.output / "media"
    media.mkdir()
    model = YOLO(str(args.model))
    captures, evidence, items = [], {}, {}
    inputs = sorted(p for p in args.input.iterdir() if p.suffix.lower() in (".jpg", ".jpeg"))
    for path in inputs:
        frame = read_jpeg(path)
        key = hashlib.sha256((path.name + frame.sha256).encode()).hexdigest()
        captures.append(frame.capture(version_id=key, source_id="isolated-study", directory_key="."))
        predictions = model.predict(source=np.ascontiguousarray(frame.pixels[:, :, ::-1]),
                                    conf=0.5, classes=[14], device=args.device, verbose=False)
        boxes = [box.xyxy[0].tolist() for result in predictions for box in result.boxes]
        result = analyze_focus(frame, boxes, version_id=key)
        evidence[key] = result
        preview = Image.fromarray(frame.pixels)
        preview.thumbnail((720, 480))
        preview.save(media / f"{key}.jpg", quality=90)
        crop_path = None
        if result.bounds:
            crop, _ = frame.crop(result.bounds)
            Image.fromarray(crop).save(media / f"{key}.png")
            crop_path = f"media/{key}.png"
        # Verify input after inference/export too; never save to the input path.
        with path.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == frame.sha256
        items[key] = dict(filename=path.name, sha256=frame.sha256,
                          captured_at=frame.metadata.captured_at.isoformat() if frame.metadata.captured_at else None,
                          original=path.resolve().as_uri(), preview=f"media/{key}.jpg", crop=crop_path,
                          boxes=boxes, evidence=result.to_dict())
        print(path.name, result.status, flush=True)
    groups = []
    for group in group_captures(captures, max_gap_seconds=args.gap, max_span_seconds=args.span):
        groups.append({**asdict(group), "ranking": asdict(rank_group(group, [evidence[k] for k in group.version_ids]))})
    groups.sort(key=lambda g: items[g["version_ids"][0]]["captured_at"] or "")
    for group in groups:
        group["ranking_modes"] = report_modes(group, items)
    with args.model.open("rb") as stream:
        model_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    report = dict(items=items, groups=groups, experiment=dict(gap=args.gap, span=args.span,
                  device=args.device, model_sha256=model_hash, confidence=0.5),
                  input_hashes_unchanged=True, human_evaluation="pending")
    report["report_id"] = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "review.html").write_text(render_review(report), encoding="utf-8")
    print(f"Review ready: {args.output / 'review.html'}", flush=True)


if __name__ == "__main__":
    main()
