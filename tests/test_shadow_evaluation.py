import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from src.evaluation.datasets import DatasetFormatError
from src.evaluation.local_directory import load_candidate_labels, load_local_directory


def _write_image(path: Path, color: str = "white") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 6), color).save(path)


def test_load_candidate_labels_supports_bom_comments_and_whitespace(tmp_path: Path):
    path = tmp_path / "labels.txt"
    path.write_text("\ufeff# birds\n Alpha \n\nBeta\n", encoding="utf-8")

    assert load_candidate_labels(path) == ("Alpha", "Beta")


@pytest.mark.parametrize("content,match", [("\n# empty\n", "no labels"), ("Alpha\nAlpha\n", "duplicate")])
def test_load_candidate_labels_rejects_invalid_files(tmp_path: Path, content: str, match: str):
    path = tmp_path / "labels.txt"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(DatasetFormatError, match=match):
        load_candidate_labels(path)


def test_load_local_directory_reads_supported_images_recursively(tmp_path: Path):
    _write_image(tmp_path / "a.jpg")
    _write_image(tmp_path / "nested" / "b.PNG", "black")
    (tmp_path / "nested" / "notes.txt").write_text("not an image", encoding="utf-8")

    dataset = load_local_directory(tmp_path, ["Alpha", "Beta"])

    assert dataset.name == "Local-Directory-Shadow"
    assert [sample.image_path.name for sample in dataset.samples] == ["a.jpg", "b.PNG"]
    assert all(sample.expected_label == "" and sample.split == "shadow" for sample in dataset.samples)
    assert dataset.metadata["discovered_images"] == 2
    assert dataset.metadata["candidate_labels_count"] == 2
    assert len(dataset.metadata["candidate_labels_sha256"]) == 64
    assert len(dataset.metadata["image_snapshot_sha256"]) == 64


def test_load_local_directory_can_disable_recursion(tmp_path: Path):
    _write_image(tmp_path / "a.jpg")
    _write_image(tmp_path / "nested" / "b.jpg")

    dataset = load_local_directory(tmp_path, ["Alpha"], recursive=False)

    assert [sample.image_path.name for sample in dataset.samples] == ["a.jpg"]


def test_load_local_directory_limit_is_deterministic(tmp_path: Path):
    for index in range(10):
        _write_image(tmp_path / f"{index}.jpg")

    first = load_local_directory(tmp_path, ["Alpha"], limit=4, seed=7)
    second = load_local_directory(tmp_path, ["Alpha"], limit=4, seed=7)
    different = load_local_directory(tmp_path, ["Alpha"], limit=4, seed=8)

    assert first.samples == second.samples
    assert first.samples != different.samples
    assert first.metadata["discovered_images"] == 10
    assert first.metadata["selected_images"] == 4
    assert first.metadata["selection_seed"] == 7


def test_load_local_directory_sample_ids_are_independent_of_root(tmp_path: Path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _write_image(first_root / "nested" / "bird.jpg")
    _write_image(second_root / "nested" / "bird.jpg")

    first = load_local_directory(first_root, ["Alpha"])
    second = load_local_directory(second_root, ["Alpha"])

    assert first.samples[0].sample_id == second.samples[0].sample_id


@pytest.mark.parametrize(
    ("labels", "limit", "match"),
    [
        ([], None, "non-empty"),
        (["Alpha", "Alpha"], None, "duplicates"),
        (["Alpha"], 0, "limit"),
    ],
)
def test_load_local_directory_validates_inputs(tmp_path: Path, labels, limit, match: str):
    _write_image(tmp_path / "a.jpg")

    with pytest.raises((DatasetFormatError, ValueError), match=match):
        load_local_directory(tmp_path, labels, limit=limit)


def test_load_local_directory_rejects_empty_or_missing_roots(tmp_path: Path):
    with pytest.raises(DatasetFormatError, match="No supported images"):
        load_local_directory(tmp_path, ["Alpha"])
    with pytest.raises(DatasetFormatError, match="not a directory"):
        load_local_directory(tmp_path / "missing", ["Alpha"])


def test_shadow_evaluation_script_can_show_help():
    completed = subprocess.run(
        [sys.executable, "scripts/evaluate_shadow.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--candidate-file" in completed.stdout
    assert "--no-recursive" in completed.stdout
    assert "bioclip-2.5-vith14" in completed.stdout
