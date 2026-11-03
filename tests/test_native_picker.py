import base64
import json
from types import SimpleNamespace
import os

import pytest

from src.web import native_picker


@pytest.mark.parametrize('selected', [r'C:\鸟类照片', r'\\nas\photos\birds', None])
def test_selection_and_cancel_use_json_without_shell_interpolation(monkeypatch, selected):
    title = "选择'; $(throw 'injected')"
    def run(command, **kwargs):
        assert command[1:3] == ['-NoProfile', '-STA']
        script = base64.b64decode(command[-1]).decode('utf-16le')
        assert title not in script
        assert json.loads(kwargs['input'])['title'] == title
        assert kwargs.get('shell', False) is False
        return SimpleNamespace(returncode=0, stdout=json.dumps({'path': selected}).encode('utf-8'))
    monkeypatch.setattr(native_picker.subprocess, 'run', run)
    assert native_picker.choose_path('folder', title) == selected


@pytest.mark.parametrize('code,output', [(1, ''), (0, 'not json'), (0, '{"path": 12}')])
def test_failed_picker_does_not_look_like_cancellation(monkeypatch, code, output):
    monkeypatch.setattr(native_picker.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=code, stdout=output.encode('utf-8')))
    with pytest.raises(RuntimeError):
        native_picker.choose_path('file', '选择文件')


def test_browser_query_parameters_reach_picker(web_app, monkeypatch):
    from fastapi.testclient import TestClient
    calls = []
    monkeypatch.setattr(web_app, 'open_folder_dialog', lambda *args: calls.append(args) or r'C:\照片')
    monkeypatch.setattr(web_app, 'open_file_dialog', lambda *args: calls.append(args) or None)
    with TestClient(web_app.app) as client:
        folder = client.post('/api/config/browse_folder', params={'title': '选择目录', 'initial_path': r'\\nas\照片'})
        file = client.post('/api/config/browse_file', params={'title': '选择名录', 'initial_path': 'D:/birds.csv', 'file_types': 'csv|json'})
    assert folder.json() == {'path': r'C:\照片'}
    assert file.json() == {'path': None}
    assert calls == [('选择目录', r'\\nas\照片'), ('选择名录', 'D:/birds.csv', 'csv|json')]


@pytest.mark.skipif(os.name != 'nt', reason='Windows native dialog initialization')
@pytest.mark.parametrize('kind,initial', [('file', ''), ('save', ''), ('save', r'C:\new-database\birds.db')])
def test_windows_file_picker_initializes_before_cancel(monkeypatch, kind, initial):
    # Exercise the real PowerShell and WinForms setup without opening a window.
    monkeypatch.setattr(native_picker, 'SCRIPT', native_picker.SCRIPT.replace(
        '$dialog.ShowDialog()', '[System.Windows.Forms.DialogResult]::Cancel'))
    assert native_picker.choose_path(kind, '选择数据库', initial, 'db|sqlite') is None


def test_database_picker_supports_new_file(web_app, monkeypatch):
    from fastapi.testclient import TestClient
    from src.web import config_service
    calls = []
    monkeypatch.setattr(config_service, 'open_file_dialog', lambda *args: calls.append(args) or 'D:/new/birds.db')
    with TestClient(web_app.app) as client:
        result = client.post('/api/config/browse_file', params={
            'title': '数据库', 'initial_path': '', 'file_types': 'db|sqlite', 'save': True})
    assert result.json() == {'path': 'D:/new/birds.db'}
    assert calls == [('数据库', '', 'db|sqlite', True)]
