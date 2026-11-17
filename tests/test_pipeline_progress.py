from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from src.pipeline_runner import WingScribePipeline


def make_runner(tmp_path):
    sources = []
    for name, count in [('20250101', 2), ('20250102', 3)]:
        source = tmp_path / name
        source.mkdir()
        for index in range(count):
            (source / f'{index}.jpg').write_bytes(b'test')
        sources.append(str(source))
    runner = WingScribePipeline.__new__(WingScribePipeline)
    runner.config = {'paths': {'sources': [{'path': p} for p in sources]}}
    runner.source_dir = str(tmp_path)
    runner.output_root = str(tmp_path / 'output')
    runner.existing_hashes = set()
    runner.total_files = runner.processed_count = 0
    runner._stop_checker = None
    runner._progress_callback = None
    runner.db = SimpleNamespace(add_scan_history=lambda row: None)
    return runner, sources


@pytest.mark.parametrize('by_folders', [False, True])
def test_all_roots_scanned_before_fixed_total_processing(tmp_path, by_folders):
    runner, sources = make_runner(tmp_path)
    enumerated = []
    original_scan = runner._scan_folder_recursive
    def scan(provider, path):
        yield from original_scan(provider, path)
        enumerated.append(path)
    runner._scan_folder_recursive = scan
    phases, progress = [], []
    runner._phase_callback = phases.append
    runner._progress_callback = lambda done, total: progress.append((done, total))
    def process(provider, entry, meta):
        assert enumerated == sources
        assert runner.total_files == 5
        runner.processed_count += 1
        runner._emit_progress()
    runner.process_image = process
    for _ in range(2):  # Reusing a runner must not accumulate a previous run's total.
        enumerated.clear()
        if by_folders:
            runner._run_folders(sources)
        else:
            runner._run_dates()
        assert runner.processed_count == runner.total_files == 5
    assert phases == ['scanning', 'processing'] * 2
    assert progress == [(n, 5) for n in range(6)] * 2


@pytest.mark.parametrize('by_folders', [False, True])
def test_stop_during_enumeration_does_not_start_photos(tmp_path, by_folders):
    runner, sources = make_runner(tmp_path)
    stopped = False
    runner._stop_checker = lambda: stopped
    def scan(provider, path):
        nonlocal stopped
        stopped = True
        yield SimpleNamespace(is_dir=False, name='0.jpg', path=str(Path(path) / '0.jpg'))
        pytest.fail('Enumeration must stop promptly')
    runner._scan_folder_recursive = scan
    runner.process_image = lambda *args: pytest.fail('Must not process after scan cancellation')
    phases = []
    runner._phase_callback = phases.append
    if by_folders:
        runner._run_folders(sources)
    else:
        runner._run_dates()
    assert phases == ['scanning']
    assert runner.total_files == 0


def test_date_filtered_files_excluded_from_progress_total(tmp_path, monkeypatch):
    runner, sources = make_runner(tmp_path)
    from src import pipeline_runner
    monkeypatch.setattr(pipeline_runner.PathParser, 'parse',
                        lambda self, path: {'captured_date': Path(path).parent.name})
    # Use ordinary recursive enumeration to test the per-file date filter too.
    monkeypatch.setattr(pipeline_runner.SmartScanner, 'scan',
                        lambda self, path: runner._scan_folder_recursive(
                            pipeline_runner.LocalProvider(str(path)), str(path)))
    runner.process_image = lambda *args: None
    runner._run_dates(start_date='20250102', end_date='20250102')
    assert runner.total_files == 3


def test_admin_uses_status_instead_of_replayed_progress_logs():
    template = (Path(__file__).parents[1] / 'src/web/templates/admin.html').read_text(encoding='utf-8')
    websocket_handler = template.split('ws.onmessage =', 1)[1].split('ws.onerror', 1)[0]
    assert 'updateProgress(' not in websocket_handler
    assert "task.phase === 'scanning'" in template


def test_admin_scan_has_no_percentage_then_shows_fixed_total(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required to execute the actual progress UI functions')
    template = (Path(__file__).parents[1] / 'src/web/templates/admin.html').read_text(encoding='utf-8')
    functions = template.split('        function showProgress()', 1)[1].split('        function connectWS()', 1)[0]
    refresh = template.split('        async function refreshTaskState()', 1)[1].split('        refreshTaskState();', 1)[0]
    script = '''
const assert = require('node:assert/strict');
const elements = {};
const document = {getElementById(id) { return elements[id] ||= {
    style: {}, classList: {add(){},remove(){}}, textContent:''}; }};
const startBtn = {};
const setTimeout = () => {};
let lastTaskState = '';
let task;
const fetch = async () => ({ok:true,json:async()=>task});
''' + 'function showProgress()' + functions + 'async function refreshTaskState()' + refresh + '''
(async () => {
    task = {task_id:'one',state:'running',is_running:true,phase:'scanning',processed:0,total:0};
    await refreshTaskState();
    assert.equal(elements['progress-percent'].textContent, '—');
    assert.match(elements['progress-text'].textContent, /文件总数尚未确定/);
    task = {...task,phase:'processing',processed:2,total:5};
    await refreshTaskState();
    assert.equal(elements['progress-percent'].textContent, '40%');
    assert.equal(elements['progress-text'].textContent, '2/5');
    task = {...task,state:'stopping',phase:'scanning'};
    await refreshTaskState();
    assert.match(elements['task-state'].textContent, /正在停止/);
})().catch(error => {console.error(error);process.exitCode=1;});
'''
    path = tmp_path / 'progress-ui.cjs'
    path.write_text(script, encoding='utf-8')
    subprocess.run([node, str(path)], check=True, capture_output=True, text=True, timeout=15)
