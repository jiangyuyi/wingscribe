import json
import logging
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from src.core.io.folder_selection import FolderSelection


def test_sparse_rules_prune_redundant_roots_and_allow_deeper_reinclude(tmp_path):
    a, b, c = tmp_path / 'A', tmp_path / 'A/B', tmp_path / 'A/B/C'
    selection = FolderSelection([str(a), str(a / 'same'), str(c)], [str(b), str(b / 'same')])
    assert selection.paths == [str(a), str(c)]
    assert selection.excluded_paths == [str(b)]
    assert selection.includes(a / 'root.jpg')
    assert not selection.includes(b / 'excluded.jpg')
    assert selection.includes(c / 'kept.jpg')
    assert selection.includes(a / 'B2/kept.jpg')
    assert not selection.includes(tmp_path / 'A2/file.jpg')


def test_nonrecursive_keeps_parent_and_child_independent(tmp_path):
    selection = FolderSelection([str(tmp_path), str(tmp_path / 'B')], recursive=False)
    assert len(selection.paths) == 2
    with pytest.raises(ValueError, match='仅适用'):
        FolderSelection([str(tmp_path)], [str(tmp_path / 'B')], recursive=False)


def test_selecting_only_child_does_not_include_parent_direct_photos(tmp_path):
    selection = FolderSelection([str(tmp_path / 'B')])
    assert not selection.includes(tmp_path / 'direct.jpg')
    assert selection.includes(tmp_path / 'B/included.jpg')


def test_lazy_directory_failure_is_reported_instead_of_cached_as_empty(tmp_path, monkeypatch):
    from src.web.pipeline_service import build_folder_tree, get_folder_children
    def denied(path):
        raise PermissionError('read denied')
    monkeypatch.setattr(Path, 'iterdir', denied)
    result = get_folder_children(str(tmp_path), logging.getLogger(__name__), build_folder_tree)
    assert result['children'] == []
    assert 'read denied' in result['error']


@pytest.mark.parametrize('suffix', ['', '/../other'])
def test_invalid_exclusion_rejected_before_task_start(tmp_path, suffix):
    from src.web.app import StartPipelineByFoldersRequest
    from src.web.pipeline_service import start_pipeline_by_folders
    task = SimpleNamespace(is_running=False, start_pipeline_by_folders=lambda *args, **kw: pytest.fail('Must not start'))
    request = StartPipelineByFoldersRequest(paths=[str(tmp_path)], excluded_paths=[str(tmp_path) + suffix])
    assert start_pipeline_by_folders(task, request, logging.getLogger(__name__))['status'] == 'error'


def test_request_forwards_exclusion_and_worker_persists_it(tmp_path):
    from src.web.app import StartPipelineByFoldersRequest
    from src.web.pipeline_service import start_pipeline_by_folders
    from src.web.task_manager import TaskManager
    calls = []
    task = SimpleNamespace(is_running=False, start_pipeline_by_folders=lambda *args, **kw: calls.append((args, kw)) or True)
    root, excluded = str(tmp_path), str(tmp_path / 'B')
    request = StartPipelineByFoldersRequest(paths=[root], excluded_paths=[excluded])
    assert start_pipeline_by_folders(task, request, logging.getLogger(__name__))['status'] == 'success'
    assert calls == [(([root], True), {'excluded_paths': [excluded]})]
    manager = TaskManager()
    manager._execute = lambda callback: callback(SimpleNamespace(run_by_folders=lambda *args, **kw: calls.append((args, kw))))
    manager._run_pipeline_thread_by_folders([root], True, [excluded])
    assert calls[-1] == (([root],), {'recursive': True, 'excluded_paths': [excluded]})


def test_http_folder_request_parses_and_forwards_exclusions(web_app, monkeypatch):
    from fastapi.testclient import TestClient
    source = web_app.config['paths']['sources'][0]['path']
    excluded = str(Path(source) / 'B')
    calls = []
    manager = SimpleNamespace(is_running=False,
        start_pipeline_by_folders=lambda *args, **kwargs: calls.append((args, kwargs)) or True)
    monkeypatch.setattr(web_app, 'task_manager', manager)
    with TestClient(web_app.app) as client:
        response = client.post('/api/pipeline/start_by_folders', json={
            'paths': [source], 'recursive': True, 'excluded_paths': [excluded]})
    assert response.status_code == 200
    assert response.json()['status'] == 'success'
    assert calls == [(([source], True), {'excluded_paths': [excluded]})]


def test_actual_scan_skips_excluded_subtree_before_listing_and_counts_only_included(tmp_path, monkeypatch):
    from src.pipeline_runner import WingScribePipeline
    from src.core.io.local import LocalProvider
    a, b, c = tmp_path / 'A', tmp_path / 'A/B', tmp_path / 'A/B/C'
    for path in (a / 'root.jpg', b / 'excluded.jpg', c / 'kept.jpg', a / 'B2/kept.jpg'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'jpeg')
    listed = []
    original = LocalProvider.list_dir
    def list_dir(self, path, **kwargs):
        listed.append(Path(path))
        yield from original(self, path, **kwargs)
    monkeypatch.setattr(LocalProvider, 'list_dir', list_dir)
    runner = WingScribePipeline.__new__(WingScribePipeline)
    runner.config = {'paths': {'sources': [{'path': str(a)}]}}
    runner.source_dir = str(a)
    runner.output_root = str(tmp_path / 'output')
    runner.existing_hashes = set()
    runner._stop_checker = runner._progress_callback = None
    runner.db = SimpleNamespace(add_scan_history=lambda value: None)
    processed = []
    runner.process_image = lambda provider, entry, meta: processed.append(Path(entry.path))
    runner._run_folders([str(a), str(c)], excluded_paths=[str(b)])
    assert b not in listed  # Critical NAS boundary: no enumeration of B.
    assert set(processed) == {a / 'root.jpg', c / 'kept.jpg', a / 'B2/kept.jpg'}
    assert runner.total_files == 3


def test_exclusions_are_stored_in_persistent_job_parameters(tmp_path):
    from src.pipeline_runner import WingScribePipeline
    from src.storage.catalogue import AssetCatalogue
    runner = WingScribePipeline.__new__(WingScribePipeline)
    runner.catalogue = AssetCatalogue(tmp_path / 'job.db')
    runner.catalogue.initialize()
    captured = []
    runner._run_folders = lambda *args: captured.append(args)
    root, excluded = str(tmp_path / 'A'), str(tmp_path / 'A/B')
    runner.run_by_folders([root], excluded_paths=[excluded])
    rows = runner.catalogue._read('SELECT parameters_json FROM processing_jobs', ())
    assert len(rows) == 1
    assert json.loads(rows[0]['parameters_json']) == {
        'mode': 'folders', 'paths': [root], 'recursive': True, 'excluded_paths': [excluded]}
    assert captured == [([root], True, [excluded])]


def test_browser_rule_model_handles_lazy_children_and_mixed_selection(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is needed to execute actual UI selection rules')
    module = Path(__file__).parents[1] / 'src/web/static/folder_selection.js'
    script = '''
const assert = require('node:assert/strict');
const Selection = require(MODULE);
const s = new Selection();
s.set('Y:\\Photos\\A', true);
assert.deepEqual(s.state('Y:/Photos/A/new/unloaded'), {checked:true,indeterminate:false});
s.set('y:/photos/a/B', false);
assert.deepEqual(s.state('Y:/Photos/A'), {checked:false,indeterminate:true});
assert.deepEqual(s.state('Y:/Photos/A/B'), {checked:false,indeterminate:false});
assert.equal(s.included('Y:/Photos/A/B2'), true);
s.set('Y:/Photos/A/B/C', true);
assert.deepEqual(s.state('Y:/Photos/A/B'), {checked:false,indeterminate:true});
assert.deepEqual(s.state('Y:/Photos/A/B/C'), {checked:true,indeterminate:false});
assert.equal(s.payload().paths.length, 2);
s.set('Y:/Photos/A', true);
assert.equal(s.payload().paths.length, 1);
assert.equal(s.payload().excluded_paths.length, 0);
s.set('Y:/Photos/A', false);
assert.deepEqual(s.payload(), {paths:[],excluded_paths:[]});
assert.deepEqual(s.state('Y:/Photos/A/new'), {checked:false,indeterminate:false});
s.set('/photos/A', true);
assert.equal(s.included('/photos/a'), false);
s.set('/', true);
assert.equal(s.included('/photos/unloaded'), true);
const childOnly = new Selection();
childOnly.set('/root/child', true);
assert.deepEqual(childOnly.state('/root'), {checked:false,indeterminate:true});
assert.equal(childOnly.included('/root'), false);
'''.replace('MODULE', json.dumps(str(module)))
    # Keep literal backslashes through Python and JS string decoding.
    script = script.replace("'Y:\\Photos\\A'", json.dumps('Y:\\Photos\\A'))
    path = tmp_path / 'selection.cjs'
    path.write_text(script, encoding='utf-8')
    subprocess.run([node, str(path)], check=True, capture_output=True, text=True, timeout=15)
