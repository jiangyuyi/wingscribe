import json
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

from src.evaluation.quality import (
    DegradationSpec,
    apply_degradation,
    run_quality_benchmark,
    write_quality_report,
)


def _checkerboard(size=128):
    grid = np.indices((size, size)).sum(axis=0) % 2
    pixels = (grid * 255).astype(np.uint8)
    return Image.fromarray(np.repeat(pixels[:, :, None], 3, axis=2))


@pytest.mark.parametrize(
    "spec",
    [
        DegradationSpec("original", "original", 0),
        DegradationSpec("blur", "blur", 2),
        DegradationSpec("downsample", "downsample", 0.5),
        DegradationSpec("dark", "exposure", 0.5),
        DegradationSpec("noise", "noise", 10),
    ],
)
def test_apply_degradation_preserves_image_shape(spec):
    result = apply_degradation(_checkerboard(32), spec, seed=7)

    assert result.size == (32, 32)
    assert result.mode == "RGB"


def test_noise_degradation_is_deterministic():
    spec = DegradationSpec("noise", "noise", 20)

    first = np.asarray(apply_degradation(_checkerboard(16), spec, seed=7))
    second = np.asarray(apply_degradation(_checkerboard(16), spec, seed=7))
    different = np.asarray(apply_degradation(_checkerboard(16), spec, seed=8))

    assert np.array_equal(first, second)
    assert not np.array_equal(first, different)


@pytest.mark.parametrize(
    "kind,severity",
    [
        ("unknown", 1),
        ("blur", -1),
        ("downsample", 0),
        ("downsample", 1.1),
    ],
)
def test_degradation_spec_rejects_invalid_values(kind, severity):
    with pytest.raises(ValueError):
        DegradationSpec("bad", kind, severity)


def test_quality_benchmark_reports_relative_changes(tmp_path):
    image_path = tmp_path / "checkerboard.png"
    _checkerboard().save(image_path)
    specs = (
        DegradationSpec("original", "original", 0),
        DegradationSpec("blur", "blur", 4),
    )

    report = run_quality_benchmark([image_path], degradations=specs, seed=7)

    assert report["run"]["image_count"] == 1
    assert report["summary"][0]["mean_quality_delta_vs_original"] == 0
    assert report["summary"][1]["mean_quality_delta_vs_original"] < 0
    assert report["summary"][1]["quality_decrease_rate"] == 1.0
    conditions = report["samples"][0]["conditions"]
    assert conditions[1]["laplacian_variance"] < conditions[0]["laplacian_variance"]


def test_quality_benchmark_validates_inputs(tmp_path):
    with pytest.raises(ValueError, match="at least one image"):
        run_quality_benchmark([])
    with pytest.raises(ValueError, match="original baseline"):
        run_quality_benchmark(
            [tmp_path / "unused.jpg"],
            degradations=[DegradationSpec("blur", "blur", 1)],
        )


def test_write_quality_report_creates_json(tmp_path):
    output_path = tmp_path / "reports" / "quality.json"
    report = {"summary": [{"name": "original"}]}

    write_quality_report(report, output_path)

    assert json.loads(output_path.read_text(encoding="utf-8")) == report


def test_quality_evaluation_script_can_show_help():
    completed = subprocess.run(
        [sys.executable, "scripts/evaluate_quality.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--root" in completed.stdout
    assert "--output" in completed.stdout
