import base64
import json
from types import SimpleNamespace

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
