from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.pipeline_runner import WingScribePipeline
from src.storage.catalogue import AssetCatalogue
from src.core.io.local import LocalProvider


@pytest.fixture
def setup(tmp_path):
    pipeline = WingScribePipeline.__new__(WingScribePipeline)
    pipeline.catalogue = AssetCatalogue(tmp_path / 'catalogue.db')
    pipeline.catalogue.initialize()
    pipeline.config = {'processing': {'target_size': 32, 'crop_padding': 0, 'quality_mode': 'disabled'}}
    pipeline.taxonomy_version = 'test-v1'
    pipeline.all_labels = ['bird']
    pipeline.output_root = str(tmp_path / 'out')
    pipeline.existing_hashes = set()
    pipeline.recognizer = SimpleNamespace(predict_batch=lambda paths, labels, top_k: [
        [{'scientific_name': 'bird', 'confidence': .9}] for _ in paths])
    pipeline._detector = SimpleNamespace(detect=Mock(return_value=[]))
    pipeline._archive_item = lambda item, *args: item['catalogue_detection'].update(output_path=None)
    path = tmp_path / 'input' / '20261001park' / 'bird.jpg'
    path.parent.mkdir(parents=True)
    Image.new('RGB', (32, 32), 'white').save(path)
    pipeline.source_dir = str(tmp_path / 'input')
    pipeline.config['paths'] = {'sources': [{'path': pipeline.source_dir, 'enabled': True}]}
    pipeline.db = SimpleNamespace(get_all_hashes=lambda: set(), add_scan_history=Mock())
    pipeline.total_files = pipeline.processed_count = 0
    pipeline._progress_callback = None
    entry = SimpleNamespace(path=str(path), name=path.name, size=path.stat().st_size)
    return pipeline, LocalProvider(pipeline.source_dir), entry


def rows(p, table):
    return p.catalogue._read(f'SELECT * FROM {table}', ())


@pytest.mark.parametrize('folders', [False, True])
def test_both_scanners_register_and_skip_unchanged(setup, folders):
    p, provider, entry = setup
    run = lambda: p.run_by_folders([p.source_dir]) if folders else p.run('20261001', '20261001')
    run()
    run()
    assert len(rows(p, 'assets')) == len(rows(p, 'asset_versions')) == 1
    assert [r['outcome'] for r in rows(p, 'asset_observations')] == ['no_detection', 'skipped']
    assert p._detector.detect.call_count == 1


def test_changed_file_and_parameters_trigger_new_analysis(setup):
    p, provider, entry = setup
    p.process_image(provider, entry, {})
    Image.new('RGB', (33, 33), 'black').save(entry.path)
    p.process_image(provider, entry, {})
    p.config['processing']['quality_mode'] = 'score_only'
    p.process_image(provider, entry, {})
    assert len(rows(p, 'assets')) == 1
    assert len(rows(p, 'asset_versions')) == 2
    assert len(rows(p, 'analysis_runs')) == 3


def test_missing_photo_retains_failure_without_version(setup):
    p, provider, entry = setup
    Path(entry.path).unlink()
    with pytest.raises(FileNotFoundError):
        p.process_image(provider, entry, {})
    assert len(rows(p, 'assets')) == 1
    assert not rows(p, 'asset_versions')
    assert rows(p, 'asset_observations')[0]['outcome'] == 'failed'


@pytest.mark.parametrize('filtered', [False, True])
def test_multibird_and_quality_outcomes(setup, filtered):
    p, provider, entry = setup
    p._detector.detect.return_value = [([0, 0, 16, 16], .9), ([16, 16, 32, 32], .8)]
    p._evaluate_crop_quality = lambda *args, **kwargs: (not filtered, None)
    p.process_image(provider, entry, {})
    assert len(rows(p, 'assets')) == 1
    assert len(rows(p, 'detections')) == 2
    assert rows(p, 'analysis_runs')[0]['outcome'] == ('quality_filtered' if filtered else 'succeeded')


def test_detector_failure_retries(setup):
    p, provider, entry = setup
    p._detector.detect.side_effect = RuntimeError('model failed')
    with pytest.raises(RuntimeError, match='model failed'):
        p.process_image(provider, entry, {})
    p._detector.detect.side_effect = None
    p.process_image(provider, entry, {})
    assert [r['outcome'] for r in rows(p, 'analysis_runs')] == ['failed', 'no_detection']


def test_incomplete_recognition_is_failure(setup):
    p, provider, entry = setup
    p._detector.detect.return_value = [([0, 0, 16, 16], .9)]
    p.recognizer.predict_batch = lambda *args, **kwargs: []
    with pytest.raises(RuntimeError, match='incomplete'):
        p.process_image(provider, entry, {})
    assert rows(p, 'analysis_runs')[0]['outcome'] == 'failed'


def test_multiple_sources_same_bytes_remain_distinct(setup, tmp_path):
    p, provider, entry = setup
    second = tmp_path / 'second'
    second.mkdir()
    (second / entry.name).write_bytes(Path(entry.path).read_bytes())
    p.config['paths']['sources'].append({'path': str(second)})
    p.run()
    assert len(rows(p, 'asset_sources')) == len(rows(p, 'assets')) == 2
    assert p._detector.detect.call_count == 2


def test_crop_failure_is_not_quality_filtered(setup, monkeypatch):
    p, provider, entry = setup
    p._detector.detect.return_value = [([0, 0, 16, 16], .9)]
    monkeypatch.setattr('src.pipeline_runner.ImageProcessor.crop_and_resize', lambda *args, **kwargs: False)
    with pytest.raises(RuntimeError, match='Crop failed'):
        p.process_image(provider, entry, {})
    assert rows(p, 'analysis_runs')[0]['outcome'] == 'failed'


def test_archive_outputs_preserved_and_missing_output_reprocessed(setup):
    from src.core.io.path_generator import PathGenerator
    p, provider, entry = setup
    p._archive_item = WingScribePipeline._archive_item.__get__(p)
    p.path_generator = PathGenerator('{filename}', p.output_root)
    p.exif_writer = SimpleNamespace(write_metadata=lambda *args: True)
    p.db.get_bird_info = lambda *args: None
    p.db.add_photo_record = Mock()
    p.log_level = 'info'
    p._detector.detect.return_value = [([0, 0, 16, 16], .9)]
    p.process_image(provider, entry, {})
    first = Path(rows(p, 'detections')[0]['output_path'])
    assert first.is_file()
    p.config['processing']['target_size'] = 40
    p.process_image(provider, entry, {})
    second = Path(rows(p, 'detections')[1]['output_path'])
    assert first != second and first.is_file() and second.is_file()
    second.unlink()
    p.process_image(provider, entry, {})
    assert len(rows(p, 'analysis_runs')) == 3


def test_partial_archive_error_keeps_output_evidence(setup):
    from src.core.io.path_generator import PathGenerator
    p, provider, entry = setup
    p._archive_item = WingScribePipeline._archive_item.__get__(p)
    p.path_generator = PathGenerator('{filename}', p.output_root)
    p.exif_writer = SimpleNamespace(write_metadata=lambda *args: False)
    p.db.get_bird_info = lambda *args: None
    p._detector.detect.return_value = [([0, 0, 16, 16], .9)]
    with pytest.raises(RuntimeError, match='metadata'):
        p.process_image(provider, entry, {})
    assert rows(p, 'analysis_runs')[0]['outcome'] == 'failed'
    assert Path(rows(p, 'detections')[0]['output_path']).is_file()
