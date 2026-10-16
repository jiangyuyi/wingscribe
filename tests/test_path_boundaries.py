from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from PIL import Image

from src.core.io.local import LocalProvider, SecurityViolationError
from src.core.io.path_utils import is_within_directory
from src.pipeline_runner import SmartScanner, WingScribePipeline


def test_provider_rejects_sibling_prefix_and_parent_escape(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    sibling = tmp_path / "photos_backup"
    sibling.mkdir()
    provider = LocalProvider(str(root))
    for path in (sibling / "bird.jpg", root / ".." / "outside.jpg"):
        with pytest.raises(SecurityViolationError):
            provider.write_bytes(str(path), b"must not be written")
        assert not path.exists()
    provider.write_bytes(str(root / "new" / "bird.jpg"), b"allowed")
    assert provider.read_bytes(str(root / "new" / "bird.jpg")) == b"allowed"


def test_provider_rejects_link_outside_root(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "bird.jpg").write_bytes(b"outside")
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires Windows Developer Mode or privilege")
    provider = LocalProvider(str(root))
    with pytest.raises(SecurityViolationError):
        provider.read_bytes(str(link / "bird.jpg"))
    assert list(provider.list_dir(str(root), recursive=True)) == []


def test_scanners_exclude_only_output_tree(tmp_path):
    output = tmp_path / "output"
    sibling = tmp_path / "output_backup"
    for directory in (output, sibling):
        directory.mkdir()
        (directory / "bird.jpg").write_bytes(b"bird")
    expected = [str(sibling / "bird.jpg")]
    scanner = SmartScanner(tmp_path, exclude_dirs=[output])
    assert [entry.path for entry in scanner.scan(tmp_path)] == expected
    pipeline = WingScribePipeline.__new__(WingScribePipeline)
    pipeline.output_root = str(output)
    assert [entry.path for entry in pipeline._scan_folder_recursive(LocalProvider(str(tmp_path)), str(tmp_path))] == expected
    assert is_within_directory(output, output)
    assert not is_within_directory(sibling, output)


def test_same_name_crops_are_isolated_and_cleaned_after_recognition(tmp_path):
    pipeline = WingScribePipeline.__new__(WingScribePipeline)
    pipeline.existing_hashes = set()
    pipeline._detector = SimpleNamespace(detect=lambda path: [([0, 0, 10, 10], 0.9)])
    pipeline._detector_loaded = True
    pipeline._detector_lock = Lock()
    pipeline.recognizer = object()
    pipeline.output_root = str(tmp_path / "output")
    pipeline.config = {"processing": {"target_size": 10, "crop_padding": 0, "quality_mode": "disabled"}}
    pipeline._select_candidate_labels = lambda _: ["test bird"]
    barrier = Barrier(2)
    captured = []

    def recognize(items, candidates):
        barrier.wait(timeout=10)
        crop = Path(items[0]["crop_path"])
        with Image.open(crop) as image:
            captured.append((crop, image.getpixel((5, 5))))

    pipeline._recognize_batch = recognize
    provider = LocalProvider(str(tmp_path))
    entries = []
    for folder, color in (("day1", "red"), ("day2", "blue")):
        directory = tmp_path / folder
        directory.mkdir()
        path = directory / "DSC0001.jpg"
        Image.new("RGB", (10, 10), color=color).save(path)
        entries.append(SimpleNamespace(path=str(path), name=path.name, size=path.stat().st_size))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(pipeline.process_image, provider, entry, {}) for entry in entries]
        for future in futures:
            future.result()
    assert len({path for path, _ in captured}) == 2
    assert sorted(pixel[0] > pixel[2] for _, pixel in captured) == [False, True]
    assert list((tmp_path / "output" / "temp").iterdir()) == []


def test_failed_crop_is_cleaned(tmp_path, monkeypatch):
    pipeline = WingScribePipeline.__new__(WingScribePipeline)
    pipeline.existing_hashes = set()
    pipeline._detector = SimpleNamespace(detect=lambda path: [([0, 0, 10, 10], 0.9)])
    pipeline._detector_loaded = True
    pipeline._detector_lock = Lock()
    pipeline.recognizer = object()
    pipeline.output_root = str(tmp_path / "output")
    pipeline.config = {"processing": {"target_size": 10, "crop_padding": 0}}
    pipeline._select_candidate_labels = lambda _: []

    def fail_crop(source, box, destination, **kwargs):
        Path(destination).write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr("src.pipeline_runner.ImageProcessor.crop_and_resize", fail_crop)
    path = tmp_path / "bird.jpg"
    Image.new("RGB", (10, 10)).save(path)
    entry = SimpleNamespace(path=str(path), name=path.name, size=path.stat().st_size)
    with pytest.raises(OSError, match="disk full"):
        pipeline.process_image(LocalProvider(str(tmp_path)), entry, {})
    assert list((tmp_path / "output" / "temp").iterdir()) == []


def test_folder_run_uses_matching_source_and_longest_root(tmp_path):
    first = tmp_path / "source"
    second = tmp_path / "source_backup"
    nested = second / "trip"
    first.mkdir()
    nested.mkdir(parents=True)
    photo = nested / "bird.jpg"
    photo.write_bytes(b"fixture")
    pipeline = WingScribePipeline.__new__(WingScribePipeline)
    pipeline.config = {"paths": {"sources": [{"path": str(p)} for p in (first, second, nested)]}}
    pipeline.source_dir = str(first)
    pipeline.output_root = str(tmp_path / "output")
    pipeline.existing_hashes = set()
    pipeline.total_files = 0
    pipeline.processed_count = 0
    pipeline._progress_callback = None
    pipeline.db = SimpleNamespace(add_scan_history=lambda record: None)
    captured = []
    pipeline.process_image = lambda provider, entry, meta: captured.append((provider.base_dir, entry.path))
    pipeline.run_by_folders([str(nested)], recursive=False)
    assert captured == [(nested, str(photo))]
