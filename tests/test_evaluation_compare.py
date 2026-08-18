import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.evaluation.compare import ReportFormatError, compare_reports


def _prediction(sample_id, expected, labels, confidences=None, error=None):
    return {
        "sample_id": sample_id,
        "image_path": f"{sample_id}.jpg",
        "expected_label": expected,
        "predicted_labels": labels,
        "confidences": confidences or [],
        "error": error,
    }


def test_compare_reports_distinguishes_improvements_and_regressions():
    baseline = {
        "run": {"image_mode": "bbox"},
        "predictions": [
            _prediction("1", "Alpha", ["Beta", "Alpha"], [0.7, 0.3]),
            _prediction("2", "Beta", ["Beta", "Alpha"], [0.8, 0.2]),
            _prediction("3", "Gamma", ["Alpha", "Gamma"], [0.6, 0.4]),
        ],
    }
    candidate = {
        "run": {"image_mode": "multicrop-2"},
        "predictions": [
            _prediction("1", "Alpha", ["Alpha", "Beta"], [0.9, 0.1]),
            _prediction("2", "Beta", ["Alpha", "Beta"], [0.55, 0.45]),
            _prediction("3", "Gamma", ["Alpha", "Gamma"], [0.65, 0.35]),
        ],
    }

    comparison = compare_reports(baseline, candidate)

    assert comparison["metrics"]["top1_agreement"] == pytest.approx(1 / 3)
    assert comparison["metrics"]["mean_top5_jaccard"] == 1.0
    assert comparison["metrics"]["top1_improvements"] == 1
    assert comparison["metrics"]["top1_regressions"] == 1
    assert comparison["metrics"]["baseline_top1_accuracy"] == pytest.approx(1 / 3)
    assert comparison["metrics"]["candidate_top1_accuracy"] == pytest.approx(1 / 3)
    assert comparison["metrics"]["top1_accuracy_delta"] == 0.0
    assert comparison["metrics"]["paired_top1_exact_p_value"] == 1.0
    assert comparison["disagreements"][0]["sample_id"] == "2"


def test_compare_reports_calculates_paired_exact_significance():
    baseline = {
        "predictions": [
            _prediction(str(index), "Alpha", ["Beta"])
            for index in range(4)
        ]
    }
    candidate = {
        "predictions": [
            _prediction(str(index), "Alpha", ["Alpha"])
            for index in range(4)
        ]
    }

    metrics = compare_reports(baseline, candidate)["metrics"]

    assert metrics["baseline_top1_accuracy"] == 0.0
    assert metrics["candidate_top1_accuracy"] == 1.0
    assert metrics["top1_accuracy_delta"] == 1.0
    assert metrics["paired_top1_exact_p_value"] == pytest.approx(0.125)


def test_compare_reports_supports_unlabeled_shadow_results():
    baseline = {"predictions": [_prediction("1", "", ["Alpha"], [0.8])]}
    candidate = {"predictions": [_prediction("1", "", ["Beta"], [0.7])]}

    comparison = compare_reports(baseline, candidate)

    assert comparison["metrics"]["labeled_samples"] == 0
    assert comparison["metrics"]["top1_improvements"] == 0
    assert comparison["metrics"]["top1_regressions"] == 0
    assert comparison["metrics"]["top1_agreement"] == 0.0
    assert comparison["metrics"]["baseline_top1_accuracy"] is None
    assert comparison["metrics"]["candidate_top1_accuracy"] is None
    assert comparison["metrics"]["top1_accuracy_delta"] is None
    assert comparison["metrics"]["paired_top1_exact_p_value"] is None


def test_compare_reports_excludes_failed_samples_and_counts_missing_ids():
    baseline = {
        "predictions": [
            _prediction("1", "Alpha", [], error="failed"),
            _prediction("2", "Beta", ["Beta"]),
        ]
    }
    candidate = {
        "predictions": [
            _prediction("1", "Alpha", ["Alpha"]),
            _prediction("3", "Gamma", ["Gamma"]),
        ]
    }

    comparison = compare_reports(baseline, candidate)

    assert comparison["metrics"]["common_samples"] == 1
    assert comparison["metrics"]["comparable_samples"] == 0
    assert comparison["metrics"]["baseline_only_samples"] == 1
    assert comparison["metrics"]["candidate_only_samples"] == 1
    assert comparison["metrics"]["top1_agreement"] is None


@pytest.mark.parametrize(
    "report,match",
    [
        ({}, "predictions list"),
        ({"predictions": ["bad"]}, "invalid prediction"),
        ({"predictions": [{"sample_id": "1"}, {"sample_id": "1"}]}, "duplicate"),
        ({"predictions": [{"sample_id": "1", "predicted_labels": "Alpha"}]}, "must be a list"),
    ],
)
def test_compare_reports_validates_report_format(report, match):
    valid = {"predictions": []}

    with pytest.raises(ReportFormatError, match=match):
        compare_reports(report, valid)


def test_compare_reports_validates_disagreement_limit():
    with pytest.raises(ValueError):
        compare_reports({"predictions": []}, {"predictions": []}, disagreement_limit=-1)


@pytest.mark.parametrize("field", ["candidate_labels_sha256", "image_snapshot_sha256"])
def test_compare_reports_rejects_different_shadow_fingerprints(field: str):
    baseline = {"dataset": {field: "a"}, "predictions": []}
    candidate = {"dataset": {field: "b"}, "predictions": []}

    with pytest.raises(ReportFormatError, match=field):
        compare_reports(baseline, candidate)


def test_compare_reports_rejects_invalid_dataset_metadata():
    with pytest.raises(ReportFormatError, match="dataset metadata"):
        compare_reports({"dataset": "invalid"}, {"predictions": []})


def test_compare_reports_respects_disagreement_limit():
    baseline = {
        "predictions": [
            _prediction("1", "", ["Alpha"]),
            _prediction("2", "", ["Alpha"]),
        ]
    }
    candidate = {
        "predictions": [
            _prediction("1", "", ["Beta"]),
            _prediction("2", "", ["Beta"]),
        ]
    }

    comparison = compare_reports(baseline, candidate, disagreement_limit=1)

    assert comparison["metrics"]["top1_changed_samples"] == 2
    assert len(comparison["disagreements"]) == 1


def test_compare_evaluation_reports_script(tmp_path: Path):
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    output_path = tmp_path / "comparison.json"
    baseline_path.write_text(json.dumps({"predictions": [_prediction("1", "", ["Alpha"])]}), encoding="utf-8")
    candidate_path.write_text(json.dumps({"predictions": [_prediction("1", "", ["Alpha"])]}), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/compare_evaluation_reports.py",
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert output_path.is_file()
    assert json.loads(output_path.read_text(encoding="utf-8"))["metrics"]["top1_agreement"] == 1.0
