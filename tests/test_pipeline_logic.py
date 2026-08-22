import pytest
import json
import os
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.pipeline_runner import WingScribePipeline
from src.core.io.local import LocalProvider
from src.core.quality import QualityResult

# Mocking the pipeline to avoid loading heavy models during init
class MockPipeline(WingScribePipeline):
    def __init__(self):
        # Skip super init
        pass


def _make_entry(path: Path):
    return SimpleNamespace(path=str(path), name=path.name, size=path.stat().st_size, is_dir=False)


def _quality_result(laplacian_variance=50.0, quality_score=0.6):
    return QualityResult(
        valid=True,
        quality_score=quality_score,
        laplacian_variance=laplacian_variance,
        tenengrad=100.0,
        contrast=0.2,
        brightness=0.5,
        underexposed_ratio=0.0,
        overexposed_ratio=0.0,
        detector_confidence=0.9,
        bird_pixel_ratio=0.25,
    )

def test_file_hash(tmp_path):
    # Create a dummy file
    p = tmp_path / "test_file.jpg"
    p.write_bytes(b"A" * 5000 + b"B" * 5000 + b"C" * 5000)

    pipeline = MockPipeline()
    provider = LocalProvider(str(tmp_path))
    h1 = pipeline._calculate_file_hash(provider, str(p), 15000)

    # Create duplicate file
    p2 = tmp_path / "test_file_2.jpg"
    p2.write_bytes(b"A" * 5000 + b"B" * 5000 + b"C" * 5000)
    h2 = pipeline._calculate_file_hash(provider, str(p2), 15000)

    assert h1 == h2

    # Create diff file (diff at end)
    p3 = tmp_path / "test_file_3.jpg"
    p3.write_bytes(b"A" * 5000 + b"B" * 5000 + b"D" * 5000)
    h3 = pipeline._calculate_file_hash(provider, str(p3), 15000)

    assert h1 != h3


def test_recognize_batch_uses_supplied_candidate_labels(tmp_path):
    class FakeRecognizer:
        def __init__(self):
            self.calls = []

        def predict_batch(self, image_paths, candidate_labels, top_k=5):
            self.calls.append((list(image_paths), list(candidate_labels), top_k))
            return [[{"scientific_name": "Passer montanus", "confidence": 0.95}] for _ in image_paths]

    pipeline = MockPipeline()
    pipeline.recognizer = FakeRecognizer()
    pipeline._recognizer_inference_lock = threading.Lock()
    pipeline.config = {"recognition": {"top_k": 3, "alternatives_threshold": 70, "low_confidence_threshold": 60}}

    archived = []
    pipeline._archive_item = lambda item, results, alt_threshold, low_conf_threshold: archived.append(
        (item["crop_path"], results, alt_threshold, low_conf_threshold)
    )

    crop_a = tmp_path / "a.jpg"
    crop_b = tmp_path / "b.jpg"
    crop_a.write_bytes(b"a")
    crop_b.write_bytes(b"b")

    items = [
        {"crop_path": str(crop_a)},
        {"crop_path": str(crop_b)},
    ]

    pipeline._recognize_batch(items, ["label-a", "label-b"])

    assert pipeline.recognizer.calls == [([str(crop_a), str(crop_b)], ["label-a", "label-b"], 3)]
    assert len(archived) == 2
    assert all(entry[2:] == (70, 60) for entry in archived)


def test_drain_futures_counts_worker_failures(caplog):
    class SuccessfulFuture:
        def result(self):
            return None

    class FailedFuture:
        def result(self):
            raise RuntimeError("worker failed")

    failures = MockPipeline._drain_futures([SuccessfulFuture(), FailedFuture()])

    assert failures == 1
    assert "Image processing worker failed" in caplog.text


def test_process_image_keeps_candidate_labels_per_image(tmp_path, monkeypatch):
    class FakeDetector:
        def detect(self, image_path):
            return [([0, 0, 5, 5], 0.9)]

    pipeline = MockPipeline()
    pipeline.existing_hashes = set()
    pipeline.db = SimpleNamespace(check_hash_exists=lambda _: False)
    pipeline._detector = FakeDetector()
    pipeline._detector_loaded = True
    pipeline._detector_lock = threading.Lock()
    pipeline.recognizer = object()
    pipeline.batch_lock = threading.Lock()
    pipeline.output_root = str(tmp_path / "out")
    pipeline.output_root and Path(pipeline.output_root).mkdir(parents=True, exist_ok=True)
    pipeline.config = {
        "processing": {"target_size": 224, "crop_padding": 0, "blur_threshold": 0},
        "recognition": {"top_k": 5, "local": {"inference_batch_size": 16}},
    }

    captured_labels = []
    pipeline._select_candidate_labels = lambda location_tag: [f"candidate:{location_tag}"]
    pipeline._recognize_batch = lambda items, candidate_labels: captured_labels.append(list(candidate_labels))

    def fake_crop(src, box, dest, target_size, padding):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        return True

    monkeypatch.setattr("src.pipeline_runner.ImageProcessor.crop_and_resize", fake_crop)

    image_path_a = tmp_path / "img_a.jpg"
    image_path_b = tmp_path / "img_b.jpg"
    Image.new("RGB", (10, 10), color="white").save(image_path_a)
    Image.new("RGB", (10, 10), color="white").save(image_path_b)

    provider = LocalProvider(str(tmp_path))
    entry_a = SimpleNamespace(path=str(image_path_a), name=image_path_a.name, size=image_path_a.stat().st_size)
    entry_b = SimpleNamespace(path=str(image_path_b), name=image_path_b.name, size=image_path_b.stat().st_size)

    pipeline.process_image(provider, entry_a, {"location_tag": "Beijing", "captured_date": "20260320"})
    pipeline.process_image(provider, entry_b, {"location_tag": "Yunnan", "captured_date": "20260320"})

    assert captured_labels == [["candidate:Beijing"], ["candidate:Yunnan"]]


def test_quality_legacy_mode_rejects_below_blur_threshold(monkeypatch):
    pipeline = MockPipeline()
    pipeline.config = {"processing": {"quality_mode": "legacy_reject", "blur_threshold": 40.0}}
    calls = []

    def fake_evaluate(path, **kwargs):
        calls.append((path, kwargs))
        return _quality_result(laplacian_variance=39.0)

    monkeypatch.setattr("src.pipeline_runner.QualityEvaluator.evaluate", fake_evaluate)

    should_process, result = pipeline._evaluate_crop_quality(
        "crop.jpg",
        detection_score=0.9,
        box=[10, 20, 60, 70],
        image_width=100,
        image_height=100,
    )

    assert should_process is False
    assert result.laplacian_variance == 39.0
    assert calls == [("crop.jpg", {"detector_confidence": 0.9, "bird_pixel_ratio": 0.25})]


def test_quality_legacy_mode_with_disabled_threshold_skips_evaluation(monkeypatch):
    pipeline = MockPipeline()
    pipeline.config = {"processing": {"blur_threshold": 0}}
    evaluate = pytest.fail
    monkeypatch.setattr("src.pipeline_runner.QualityEvaluator.evaluate", evaluate)

    assert pipeline._evaluate_crop_quality(
        "crop.jpg",
        detection_score=0.9,
        box=[0, 0, 10, 10],
        image_width=10,
        image_height=10,
    ) == (True, None)


def test_quality_score_only_keeps_low_quality_result(monkeypatch):
    pipeline = MockPipeline()
    pipeline.config = {"processing": {"quality_mode": "score_only", "blur_threshold": 100.0}}
    expected = _quality_result(laplacian_variance=1.0, quality_score=0.1)
    monkeypatch.setattr("src.pipeline_runner.QualityEvaluator.evaluate", lambda *args, **kwargs: expected)

    should_process, result = pipeline._evaluate_crop_quality(
        "crop.jpg",
        detection_score=0.2,
        box=[0, 0, 5, 5],
        image_width=10,
        image_height=10,
    )

    assert should_process is True
    assert result is expected


def test_quality_disabled_mode_skips_evaluation(monkeypatch):
    pipeline = MockPipeline()
    pipeline.config = {"processing": {"quality_mode": "disabled"}}
    monkeypatch.setattr("src.pipeline_runner.QualityEvaluator.evaluate", pytest.fail)

    assert pipeline._evaluate_crop_quality(
        "crop.jpg",
        detection_score=0.9,
        box=[0, 0, 10, 10],
        image_width=10,
        image_height=10,
    ) == (True, None)


def test_quality_unknown_mode_falls_back_to_legacy(monkeypatch, caplog):
    pipeline = MockPipeline()
    pipeline.config = {"processing": {"quality_mode": "unexpected", "blur_threshold": 40.0}}
    monkeypatch.setattr(
        "src.pipeline_runner.QualityEvaluator.evaluate",
        lambda *args, **kwargs: _quality_result(laplacian_variance=20.0),
    )

    should_process, _ = pipeline._evaluate_crop_quality(
        "crop.jpg",
        detection_score=0.9,
        box=[0, 0, 10, 10],
        image_width=10,
        image_height=10,
    )

    assert should_process is False
    assert "falling back to legacy_reject" in caplog.text


@pytest.mark.parametrize(
    ("box", "width", "height", "expected"),
    [
        ([-10, -10, 50, 50], 100, 100, 0.25),
        ([80, 80, 120, 120], 100, 100, 0.04),
        ([0, 0, 10, 10], 0, 100, None),
    ],
)
def test_calculate_bird_pixel_ratio_clips_to_image(box, width, height, expected):
    result = MockPipeline._calculate_bird_pixel_ratio(box, width, height)

    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_process_image_passes_quality_metrics_to_recognition(tmp_path, monkeypatch):
    pipeline = MockPipeline()
    pipeline.existing_hashes = set()
    pipeline.db = SimpleNamespace(check_hash_exists=lambda _: False)
    pipeline._detector = SimpleNamespace(detect=lambda _: [([0, 0, 5, 5], 0.9)])
    pipeline._detector_loaded = True
    pipeline._detector_lock = threading.Lock()
    pipeline.recognizer = object()
    pipeline.batch_lock = threading.Lock()
    pipeline.output_root = str(tmp_path / "out")
    pipeline.config = {
        "processing": {
            "target_size": 224,
            "crop_padding": 0,
            "blur_threshold": 40.0,
            "quality_mode": "score_only",
        }
    }
    pipeline._select_candidate_labels = lambda _: ["Passer montanus"]
    captured_items = []
    pipeline._recognize_batch = lambda items, _: captured_items.extend(items)
    expected = _quality_result()
    monkeypatch.setattr("src.pipeline_runner.QualityEvaluator.evaluate", lambda *args, **kwargs: expected)

    def fake_crop(src, box, dest, target_size, padding):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        return True

    monkeypatch.setattr("src.pipeline_runner.ImageProcessor.crop_and_resize", fake_crop)
    image_path = tmp_path / "bird.jpg"
    Image.new("RGB", (10, 10), color="white").save(image_path)
    provider = LocalProvider(str(tmp_path))

    pipeline.process_image(provider, _make_entry(image_path), {"location_tag": "Beijing"})

    assert len(captured_items) == 1
    assert captured_items[0]["quality"] == expected.to_dict()


def test_quality_storage_fields_preserve_score_and_audit_details():
    quality = _quality_result(quality_score=0.625).to_dict()

    fields = MockPipeline._quality_storage_fields(quality)

    assert fields["quality_score"] == pytest.approx(0.625)
    assert json.loads(fields["quality_details_json"]) == quality


@pytest.mark.parametrize("quality", [None, {}, "invalid"])
def test_quality_storage_fields_keep_disabled_or_invalid_results_empty(quality):
    fields = MockPipeline._quality_storage_fields(quality)

    if quality == {}:
        assert fields["quality_score"] is None
        assert json.loads(fields["quality_details_json"]) == {}
    else:
        assert fields == {"quality_score": None, "quality_details_json": None}


def test_select_candidate_labels_respects_region_filter_modes():
    pipeline = MockPipeline()
    pipeline.all_labels = ["Passer montanus", "Parus minor", "Corvus macrorhynchos"]
    pipeline.china_allowlist = {"Passer montanus", "Parus minor"}
    pipeline.foreign_countries = {"Japan", "USA"}

    pipeline.config = {"recognition": {"region_filter": "china"}}
    assert pipeline._select_candidate_labels("Beijing") == ["Passer montanus", "Parus minor"]

    pipeline.config = {"recognition": {"region_filter": "auto"}}
    assert pipeline._select_candidate_labels("Beijing") == ["Passer montanus", "Parus minor"]
    assert pipeline._select_candidate_labels("Japan_Tokyo") == pipeline.all_labels

    pipeline.config = {"recognition": {"region_filter": "global"}}
    assert pipeline._select_candidate_labels("Anywhere") == pipeline.all_labels


def test_init_recognizer_selects_backend(monkeypatch):
    pipeline = MockPipeline()
    pipeline.device = "auto"
    pipeline.config = {
        "recognition": {
            "mode": "local",
            "hf_mirror": "https://mirror.example",
            "local": {"model_type": "bioclip-2"},
            "dongniao": {"key": "k1", "url": "https://dongniao.example"},
            "api": {"key": "k2", "url": "https://api.example"},
        }
    }

    created = {}

    class FakeLocal:
        def __init__(self, model_name, device, hf_mirror):
            created["local"] = (model_name, device, hf_mirror)

    class FakeDongniao:
        def __init__(self, api_key, api_url):
            created["dongniao"] = (api_key, api_url)

    class FakeApi:
        def __init__(self, api_url, api_key):
            created["api"] = (api_key, api_url)

    monkeypatch.setattr("src.pipeline_runner.LocalBirdRecognizer", FakeLocal)
    monkeypatch.setattr("src.pipeline_runner.DongniaoRecognizer", FakeDongniao)
    monkeypatch.setattr("src.pipeline_runner.APIBirdRecognizer", FakeApi)

    pipeline._init_recognizer()
    assert created["local"] == ("bioclip-2", "auto", "https://mirror.example")

    pipeline.config["recognition"]["mode"] = "dongniao"
    pipeline._init_recognizer()
    assert created["dongniao"] == ("k1", "https://dongniao.example")

    pipeline.config["recognition"]["mode"] = "api"
    pipeline._init_recognizer()
    assert created["api"] == ("k2", "https://api.example")

    pipeline.config["recognition"]["mode"] = "unknown"
    with pytest.raises(ValueError):
        pipeline._init_recognizer()


def test_run_processes_valid_entries_and_records_scan_history(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    valid_a = source_root / "20260320_Beijing" / "a.jpg"
    valid_b = source_root / "20260321_Beijing" / "b.jpeg"
    skipped_txt = source_root / "20260320_Beijing" / "note.txt"
    output_file = tmp_path / "output" / "ignored.jpg"
    valid_a.parent.mkdir(parents=True, exist_ok=True)
    valid_b.parent.mkdir(parents=True, exist_ok=True)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    valid_a.write_bytes(b"a")
    valid_b.write_bytes(b"b")
    skipped_txt.write_text("x", encoding="utf-8")
    output_file.write_bytes(b"y")

    pipeline = MockPipeline()
    pipeline.config = {
        "paths": {
            "sources": [{"path": str(source_root), "recursive": False, "enabled": True}],
        }
    }
    pipeline.source_dir = str(source_root)
    pipeline.output_root = str(output_file.parent)
    pipeline.total_files = 0
    pipeline.processed_count = 0
    emitted = []
    pipeline._progress_callback = lambda processed, total: emitted.append((processed, total))
    pipeline.existing_hashes = set()
    recorded = []
    pipeline.process_image = lambda provider, entry, meta: recorded.append((entry.name, meta["captured_date"], meta["location_tag"]))

    history = []
    pipeline.db = SimpleNamespace(
        get_all_hashes=lambda: set(),
        add_scan_history=lambda record: history.append(record),
    )

    class FakeProvider:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def exists(self, path):
            return True

        def get_local_path(self, path):
            return path

        def list_dir(self, path, recursive=False):
            return [
                _make_entry(valid_a),
                _make_entry(valid_b),
                _make_entry(skipped_txt),
                _make_entry(output_file),
            ]

    class FakeParser:
        def __init__(self, source_root_abs, structure_pattern):
            self.source_root_abs = source_root_abs
            self.structure_pattern = structure_pattern

        def parse(self, entry_path):
            name = Path(entry_path).name
            if name == "a.jpg":
                return {"captured_date": "20260320", "location_tag": "Beijing"}
            return {"captured_date": "20260321", "location_tag": "Beijing"}

    class ImmediateExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return SimpleNamespace(done=lambda: True, result=lambda: None)

    monkeypatch.setattr("src.pipeline_runner.LocalProvider", FakeProvider)
    monkeypatch.setattr("src.pipeline_runner.PathParser", FakeParser)
    monkeypatch.setattr("src.pipeline_runner.ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.pipeline_runner.wait", lambda futures, timeout=None: (list(futures), []))

    pipeline.run(start_date="20260320", end_date="20260320", existing_hashes={"already"})

    assert recorded == [("a.jpg", "20260320", "Beijing")]
    assert pipeline.total_files == 2
    assert emitted[0] == (0, 2)
    assert history[0]["range_start"] == "20260320"
    assert history[0]["range_end"] == "20260320"
    assert history[0]["processed_count"] == 1


def test_run_by_folders_uses_recursive_scanner_and_records_history(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    target_folder = source_root / "trip"
    target_folder.mkdir(parents=True)
    valid_a = target_folder / "a.jpg"
    valid_b = target_folder / "b.jpeg"
    valid_a.write_bytes(b"a")
    valid_b.write_bytes(b"b")

    pipeline = MockPipeline()
    pipeline.config = {
        "paths": {
            "sources": [{"path": str(source_root), "enabled": True}],
        }
    }
    pipeline.source_dir = str(source_root)
    pipeline.output_root = ""
    pipeline.total_files = 0
    pipeline.processed_count = 0
    pipeline._progress_callback = None
    pipeline.existing_hashes = None
    processed = []
    pipeline.process_image = lambda provider, entry, meta: processed.append((entry.name, meta["captured_date"]))
    history = []
    pipeline.db = SimpleNamespace(
        get_all_hashes=lambda: {"old"},
        add_scan_history=lambda record: history.append(record),
    )
    pipeline._scan_folder_recursive = lambda provider, folder_path: [_make_entry(valid_a), _make_entry(valid_b)]

    class FakeProvider:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def exists(self, path):
            return True

        def list_dir(self, path, recursive=False):
            return []

    class FakeParser:
        def __init__(self, source_root_abs, structure_pattern):
            self.source_root_abs = source_root_abs

        def parse(self, entry_path):
            return {"captured_date": "20260322", "location_tag": "Trip"}

    class ImmediateExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return SimpleNamespace(done=lambda: True, result=lambda: None)

    monkeypatch.setattr("src.pipeline_runner.LocalProvider", FakeProvider)
    monkeypatch.setattr("src.pipeline_runner.PathParser", FakeParser)
    monkeypatch.setattr("src.pipeline_runner.ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.pipeline_runner.wait", lambda futures, timeout=None: (list(futures), []))

    pipeline.run_by_folders([str(target_folder)], recursive=True)

    assert pipeline.existing_hashes == {"old"}
    assert processed == [("a.jpg", "20260322"), ("b.jpeg", "20260322")]
    assert history[0]["range_start"] == f"Folders: {target_folder}"
    assert history[0]["processed_count"] == 2


def test_run_stops_submitting_new_tasks_when_stop_requested(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    valid_a = source_root / "20260320_Beijing" / "a.jpg"
    valid_b = source_root / "20260320_Beijing" / "b.jpg"
    valid_a.parent.mkdir(parents=True, exist_ok=True)
    valid_a.write_bytes(b"a")
    valid_b.write_bytes(b"b")

    pipeline = MockPipeline()
    pipeline.config = {"paths": {"sources": [{"path": str(source_root), "recursive": False, "enabled": True}]}}
    pipeline.source_dir = str(source_root)
    pipeline.output_root = ""
    pipeline.total_files = 0
    pipeline.processed_count = 0
    pipeline._progress_callback = None
    pipeline.existing_hashes = set()

    stop_state = {"requested": False}
    pipeline.set_stop_checker(lambda: stop_state["requested"])

    processed = []

    def process_image(provider, entry, meta):
        processed.append(entry.name)
        stop_state["requested"] = True

    pipeline.process_image = process_image

    history = []
    pipeline.db = SimpleNamespace(
        get_all_hashes=lambda: set(),
        add_scan_history=lambda record: history.append(record),
    )

    class FakeProvider:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def exists(self, path):
            return True

        def get_local_path(self, path):
            return path

        def list_dir(self, path, recursive=False):
            return [_make_entry(valid_a), _make_entry(valid_b)]

    class FakeParser:
        def __init__(self, source_root_abs, structure_pattern):
            self.source_root_abs = source_root_abs
            self.structure_pattern = structure_pattern

        def parse(self, entry_path):
            return {"captured_date": "20260320", "location_tag": "Beijing"}

    class ImmediateExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return SimpleNamespace(done=lambda: True, result=lambda: None)

    monkeypatch.setattr("src.pipeline_runner.LocalProvider", FakeProvider)
    monkeypatch.setattr("src.pipeline_runner.PathParser", FakeParser)
    monkeypatch.setattr("src.pipeline_runner.ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.pipeline_runner.wait", lambda futures, timeout=None: (list(futures), []))

    pipeline.run(existing_hashes=set())

    assert processed == ["a.jpg"]
    assert history[0]["processed_count"] == 1
    assert history[0]["status"] == "Stopped"


def test_run_by_folders_stops_submitting_new_tasks_when_stop_requested(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    target_folder = source_root / "trip"
    target_folder.mkdir(parents=True)
    valid_a = target_folder / "a.jpg"
    valid_b = target_folder / "b.jpg"
    valid_a.write_bytes(b"a")
    valid_b.write_bytes(b"b")

    pipeline = MockPipeline()
    pipeline.config = {"paths": {"sources": [{"path": str(source_root), "enabled": True}]}}
    pipeline.source_dir = str(source_root)
    pipeline.output_root = ""
    pipeline.total_files = 0
    pipeline.processed_count = 0
    pipeline._progress_callback = None
    pipeline.existing_hashes = None

    stop_state = {"requested": False}
    pipeline.set_stop_checker(lambda: stop_state["requested"])

    processed = []

    def process_image(provider, entry, meta):
        processed.append(entry.name)
        stop_state["requested"] = True

    pipeline.process_image = process_image

    history = []
    pipeline.db = SimpleNamespace(
        get_all_hashes=lambda: set(),
        add_scan_history=lambda record: history.append(record),
    )
    pipeline._scan_folder_recursive = lambda provider, folder_path: [_make_entry(valid_a), _make_entry(valid_b)]

    class FakeProvider:
        def __init__(self, base_dir):
            self.base_dir = base_dir

        def exists(self, path):
            return True

        def list_dir(self, path, recursive=False):
            return []

    class FakeParser:
        def __init__(self, source_root_abs, structure_pattern):
            self.source_root_abs = source_root_abs

        def parse(self, entry_path):
            return {"captured_date": "20260322", "location_tag": "Trip"}

    class ImmediateExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return SimpleNamespace(done=lambda: True, result=lambda: None)

    monkeypatch.setattr("src.pipeline_runner.LocalProvider", FakeProvider)
    monkeypatch.setattr("src.pipeline_runner.PathParser", FakeParser)
    monkeypatch.setattr("src.pipeline_runner.ThreadPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.pipeline_runner.wait", lambda futures, timeout=None: (list(futures), []))

    pipeline.run_by_folders([str(target_folder)], recursive=True)

    assert processed == ["a.jpg"]
    assert history[0]["processed_count"] == 1
    assert history[0]["status"] == "Stopped"
