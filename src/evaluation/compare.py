from __future__ import annotations

from typing import Any, Iterable


class ReportFormatError(ValueError):
    """Raised when an evaluation report cannot be compared safely."""


def _prediction_index(report: dict[str, Any], report_name: str) -> dict[str, dict[str, Any]]:
    predictions = report.get("predictions")
    if not isinstance(predictions, list):
        raise ReportFormatError(f"{report_name} report does not contain a predictions list")

    indexed: dict[str, dict[str, Any]] = {}
    for prediction in predictions:
        if not isinstance(prediction, dict) or "sample_id" not in prediction:
            raise ReportFormatError(f"{report_name} report contains an invalid prediction")
        _labels(prediction)
        _confidence(prediction)
        sample_id = str(prediction["sample_id"])
        if sample_id in indexed:
            raise ReportFormatError(f"{report_name} report contains duplicate sample id {sample_id}")
        indexed[sample_id] = prediction
    return indexed


def _labels(prediction: dict[str, Any]) -> list[str]:
    labels = prediction.get("predicted_labels", [])
    if not isinstance(labels, list):
        raise ReportFormatError("predicted_labels must be a list")
    return [str(label) for label in labels if label]


def _confidence(prediction: dict[str, Any]) -> float | None:
    confidences = prediction.get("confidences", [])
    if not isinstance(confidences, list):
        raise ReportFormatError("confidences must be a list")
    if not confidences:
        return None
    try:
        return float(confidences[0])
    except (TypeError, ValueError) as exc:
        raise ReportFormatError("top-1 confidence must be numeric") from exc


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def compare_reports(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    *,
    disagreement_limit: int = 100,
) -> dict[str, Any]:
    if disagreement_limit < 0:
        raise ValueError("disagreement_limit must not be negative")

    baseline = _prediction_index(baseline_report, "baseline")
    candidate = _prediction_index(candidate_report, "candidate")
    common_ids = sorted(baseline.keys() & candidate.keys())
    comparable = 0
    top1_agreements = 0
    top5_jaccards: list[float] = []
    confidence_deltas: list[float] = []
    labeled_samples = 0
    improvements = 0
    regressions = 0
    disagreements: list[dict[str, Any]] = []

    for sample_id in common_ids:
        baseline_prediction = baseline[sample_id]
        candidate_prediction = candidate[sample_id]
        baseline_labels = _labels(baseline_prediction)
        candidate_labels = _labels(candidate_prediction)
        if (
            baseline_prediction.get("error")
            or candidate_prediction.get("error")
            or not baseline_labels
            or not candidate_labels
        ):
            continue

        comparable += 1
        baseline_top1 = baseline_labels[0]
        candidate_top1 = candidate_labels[0]
        if baseline_top1 == candidate_top1:
            top1_agreements += 1

        baseline_top5 = set(baseline_labels[:5])
        candidate_top5 = set(candidate_labels[:5])
        top5_jaccards.append(len(baseline_top5 & candidate_top5) / len(baseline_top5 | candidate_top5))

        baseline_confidence = _confidence(baseline_prediction)
        candidate_confidence = _confidence(candidate_prediction)
        confidence_delta = None
        if baseline_confidence is not None and candidate_confidence is not None:
            confidence_delta = candidate_confidence - baseline_confidence
            confidence_deltas.append(abs(confidence_delta))

        expected_label = str(baseline_prediction.get("expected_label") or "")
        candidate_expected = str(candidate_prediction.get("expected_label") or "")
        baseline_correct = None
        candidate_correct = None
        if expected_label and expected_label == candidate_expected:
            labeled_samples += 1
            baseline_correct = baseline_top1 == expected_label
            candidate_correct = candidate_top1 == expected_label
            improvements += int(not baseline_correct and candidate_correct)
            regressions += int(baseline_correct and not candidate_correct)

        if baseline_top1 != candidate_top1:
            disagreements.append(
                {
                    "sample_id": sample_id,
                    "image_path": baseline_prediction.get("image_path") or candidate_prediction.get("image_path"),
                    "expected_label": expected_label or None,
                    "baseline_top1": baseline_top1,
                    "candidate_top1": candidate_top1,
                    "baseline_confidence": baseline_confidence,
                    "candidate_confidence": candidate_confidence,
                    "confidence_delta": confidence_delta,
                    "baseline_correct": baseline_correct,
                    "candidate_correct": candidate_correct,
                }
            )

    disagreements.sort(
        key=lambda item: (
            item["baseline_correct"] is True and item["candidate_correct"] is False,
            abs(item["confidence_delta"] or 0.0),
        ),
        reverse=True,
    )

    return {
        "baseline_run": baseline_report.get("run", {}),
        "candidate_run": candidate_report.get("run", {}),
        "metrics": {
            "baseline_samples": len(baseline),
            "candidate_samples": len(candidate),
            "common_samples": len(common_ids),
            "baseline_only_samples": len(baseline.keys() - candidate.keys()),
            "candidate_only_samples": len(candidate.keys() - baseline.keys()),
            "comparable_samples": comparable,
            "top1_agreement": top1_agreements / comparable if comparable else None,
            "mean_top5_jaccard": _mean(top5_jaccards),
            "mean_abs_top1_confidence_delta": _mean(confidence_deltas),
            "top1_changed_samples": len(disagreements),
            "labeled_samples": labeled_samples,
            "top1_improvements": improvements,
            "top1_regressions": regressions,
        },
        "disagreements": disagreements[:disagreement_limit],
    }
