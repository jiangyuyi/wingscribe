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
    assert ':' not in first.name
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


@pytest.mark.parametrize('folders', [False, True])
def test_scans_persist_jobs_and_progress_per_original(setup, folders):
    p, provider, entry = setup
    run = lambda: p.run_by_folders([p.source_dir]) if folders else p.run()
    run()
    assert rows(p, 'processing_jobs')[0]['status'] == 'completed'
    assert rows(p, 'job_items')[0]['status'] == 'completed'
    assert p.processed_count == p.total_files == 1
    run()
    assert len(rows(p, 'processing_jobs')) == 2
    assert rows(p, 'job_items')[1]['status'] == 'skipped'
    assert p.processed_count == p.total_files == 1


def test_failed_image_finishes_persistent_job(setup):
    p, provider, entry = setup
    p._detector.detect.side_effect = RuntimeError('broken model')
    with pytest.raises(RuntimeError, match='broken model'):
        p.run()
    assert rows(p, 'processing_jobs')[0]['status'] == 'failed'
    assert rows(p, 'job_items')[0]['status'] == 'failed'
    p._detector.detect.side_effect = None
    p.run()
    assert [r['status'] for r in rows(p, 'processing_jobs')] == ['failed', 'completed']


def test_second_scanner_rejected_before_model_work(setup):
    from src.storage.job_session import JobBusyError, JobSession
    p, provider, entry = setup
    with JobSession(p.catalogue):
        with pytest.raises(JobBusyError):
            p.run()
    p._detector.detect.assert_not_called()
    assert not rows(p, 'processing_jobs')


def test_overlapping_folders_do_not_repeat_item(setup):
    p, provider, entry = setup
    p.run_by_folders([p.source_dir, str(Path(entry.path).parent)])
    assert len(rows(p, 'job_items')) == 1
    p._detector.detect.assert_called_once()


def test_bounded_submission_and_cooperative_stop(setup, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    p, provider, entry = setup
    for n in range(20):
        Path(entry.path).with_name(f'bird{n}.jpg').write_bytes(Path(entry.path).read_bytes())
    entered, submitted_four, release = threading.Event(), threading.Event(), threading.Event()
    submissions = []
    class TrackingExecutor(ThreadPoolExecutor):
        def submit(self, *args, **kwargs):
            future = super().submit(*args, **kwargs)
            submissions.append(future)
            if len(submissions) == 4:
                submitted_four.set()
            return future
    monkeypatch.setattr('src.pipeline_runner.ThreadPoolExecutor', TrackingExecutor)
    stop = threading.Event()
    p.set_stop_checker(stop.is_set)
    def detect(*args):
        entered.set()
        assert release.wait(10)
        return []
    p._detector.detect.side_effect = detect
    errors = []
    def run():
        try:
            p.run()
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(5) and submitted_four.wait(5)
        assert len(submissions) == 4
        stop.set()
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and not errors
    assert len(submissions) == 4
    assert rows(p, 'processing_jobs')[0]['status'] == 'stopped'
    assert sorted(i['status'] for i in rows(p, 'job_items')) == ['completed', 'interrupted', 'interrupted', 'interrupted']
    assert p._detector.detect.call_count == 1


def test_task_manager_links_job_and_restores_terminal_status(setup, monkeypatch):
    from src.web.task_manager import TaskManager
    p, provider, entry = setup
    p.db.close = lambda: None
    monkeypatch.setattr('src.web.task_manager.WingScribePipeline', lambda *args, **kwargs: p)
    config = {'paths': {'db_path': str(p.catalogue.db_path)}}
    manager = TaskManager(config_override=config)
    assert manager.start_pipeline()
    manager.wait()
    status = manager.snapshot()
    assert status['job_id'] == p.job_id
    assert status['persisted_job']['status'] == status['state'] == 'completed'
    restored = TaskManager(config_override=config).snapshot()
    assert restored['job_id'] == p.job_id
    assert restored['state'] == 'completed'
    assert restored['processed'] == restored['total'] == 1


def test_crashed_scan_recovered_and_rescan_uses_current_version(setup):
    import subprocess
    import sys
    from src.web.task_manager import TaskManager
    p, provider, entry = setup
    script = '''
import os,sys
from types import SimpleNamespace
from src.pipeline_runner import WingScribePipeline
from src.storage.catalogue import AssetCatalogue
p=WingScribePipeline.__new__(WingScribePipeline)
p.catalogue=AssetCatalogue(sys.argv[1])
p.source_dir=sys.argv[2]
p.output_root=sys.argv[3]
p.config={'paths':{'sources':[{'path':p.source_dir}]}}
p.taxonomy_version='test-v1'
p.all_labels=['bird']
p.existing_hashes=set()
p._progress_callback=None
p.db=SimpleNamespace(add_scan_history=lambda data: None)
p._detector=SimpleNamespace(detect=lambda path: os._exit(19))
p.run()
'''
    result = subprocess.run([sys.executable, '-c', script, str(p.catalogue.db_path), p.source_dir, p.output_root], timeout=45)
    assert result.returncode == 19
    assert rows(p, 'processing_jobs')[0]['status'] == 'running'
    manager = TaskManager(config_override={'paths': {'db_path': str(p.catalogue.db_path)}})
    assert manager.snapshot()['state'] == 'interrupted'
    assert manager.snapshot()['recovered_jobs'] == 1
    assert rows(p, 'job_items')[0]['status'] == 'interrupted'
    Image.new('RGB', (40, 40), 'black').save(entry.path)
    p.run()
    assert len(rows(p, 'asset_versions')) == 2
    assert rows(p, 'job_items')[0]['version_id'] != rows(p, 'job_items')[1]['version_id']
    assert [r['status'] for r in rows(p, 'processing_jobs')] == ['interrupted', 'completed']


@pytest.mark.parametrize('folders', [False, True])
def test_source_disappears_and_recovers_without_deleting_records(setup, folders):
    p, provider, entry = setup
    run = lambda: p.run_by_folders([p.source_dir]) if folders else p.run()
    run()
    old_asset = rows(p, 'assets')[0]['id']
    source = Path(p.source_dir)
    offline = source.with_name('offline-test-source')
    source.rename(offline)
    try:
        with pytest.raises(RuntimeError, match='Cannot scan'):
            run()
        assert rows(p, 'assets')[0]['availability'] == 'unavailable'
        assert len(rows(p, 'asset_versions')) == 1
        assert rows(p, 'processing_jobs')[-1]['status'] == 'failed'
        assert p.db.add_scan_history.call_args.args[0]['status'] == 'Failed'
    finally:
        offline.rename(source)
    run()
    assert rows(p, 'assets')[0]['id'] == old_asset
    assert rows(p, 'assets')[0]['availability'] == 'available'
    assert len(rows(p, 'analysis_runs')) == 1


@pytest.mark.parametrize('mode', ['recursive', 'dates', 'folders'])
def test_nested_permission_failure_is_not_success(setup, monkeypatch, mode):
    import os
    p, provider, entry = setup
    p.run()
    blocked = Path(entry.path).parent
    original = os.scandir
    def scandir(path):
        if Path(path) == blocked:
            raise PermissionError(13, 'injected directory denial', str(path))
        return original(path)
    monkeypatch.setattr('src.core.io.local.os.scandir', scandir)
    with pytest.raises(RuntimeError, match='directory denial'):
        if mode == 'folders':
            p.run_by_folders([p.source_dir])
        elif mode == 'dates':
            p.run('20261001', '20261001')
        else:
            p.run()
    assert rows(p, 'assets')[0]['availability'] == 'unknown'
    assert rows(p, 'processing_jobs')[-1]['status'] == 'failed'
    assert p.db.add_scan_history.call_args.args[0]['status'] == 'Failed'


def test_unavailable_subfolder_does_not_mark_sibling(setup):
    p, provider, entry = setup
    sibling = Path(p.source_dir) / '20261002other'
    sibling.mkdir()
    (sibling / 'other.jpg').write_bytes(Path(entry.path).read_bytes())
    p.run()
    folder = Path(entry.path).parent
    offline = folder.with_name('offline')
    folder.rename(offline)
    try:
        with pytest.raises(RuntimeError):
            p.run_by_folders([str(folder)])
        availability = {a['relative_path']: a['availability'] for a in rows(p, 'assets')}
        assert availability['20261001park/bird.jpg'] == 'unavailable'
        assert availability['20261002other/other.jpg'] == 'available'
    finally:
        offline.rename(folder)


def test_individual_missing_source_keeps_previous_version(setup):
    p, provider, entry = setup
    p.process_image(provider, entry, {})
    Path(entry.path).unlink()
    with pytest.raises(FileNotFoundError):
        p.process_image(provider, entry, {})
    assert rows(p, 'assets')[0]['availability'] == 'unavailable'
    assert len(rows(p, 'asset_versions')) == 1
    assert rows(p, 'asset_observations')[-1]['version_id'] is None


def test_source_rebind_then_rescan_preserves_asset_identity(setup):
    p, provider, entry = setup
    p.run()
    before = rows(p, 'assets')[0]
    old_root = Path(p.source_dir)
    new_root = old_root.with_name('new-source-binding')
    old_root.rename(new_root)
    with p.catalogue.transaction() as tx:
        tx.rebind_source(before['source_id'], str(new_root))
    p.source_dir = str(new_root)
    p.config['paths']['sources'][0]['path'] = str(new_root)
    p.run()
    assert len(rows(p, 'assets')) == len(rows(p, 'asset_versions')) == 1
    assert rows(p, 'assets')[0]['id'] == before['id']
    assert rows(p, 'job_items')[-1]['status'] == 'skipped'


def test_unreadable_excluded_output_is_not_scanned(setup, monkeypatch):
    import os
    p, provider, entry = setup
    p.output_root = str(Path(p.source_dir) / 'output')
    Path(p.output_root).mkdir()
    original = os.scandir
    def scandir(path):
        if Path(path) == Path(p.output_root):
            raise PermissionError('output is deliberately unreadable')
        return original(path)
    monkeypatch.setattr('src.core.io.local.os.scandir', scandir)
    p.run()
    assert rows(p, 'processing_jobs')[0]['status'] == 'completed'


def test_directory_link_cycle_is_not_followed(setup):
    p, provider, entry = setup
    link = Path(entry.path).parent / 'cycle'
    try:
        link.symlink_to(Path(p.source_dir), target_is_directory=True)
    except OSError:
        pytest.skip('Creating directory links requires Windows privilege')
    p.run()
    assert len(rows(p, 'assets')) == 1
    assert rows(p, 'processing_jobs')[0]['status'] == 'completed'


def test_offline_scope_marking_does_not_require_path_resolution(setup, monkeypatch):
    p, provider, entry = setup
    p.run()
    monkeypatch.setattr('src.pipeline_runner.is_within_directory', lambda *args: False)
    errors = []
    p._record_scan_failure(provider, p.source_dir, FileNotFoundError('offline'), errors)
    assert errors and rows(p, 'assets')[0]['availability'] == 'unavailable'
