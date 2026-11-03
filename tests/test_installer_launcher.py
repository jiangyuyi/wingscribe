import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('content', [None, 'invalid: [', 'web:\n  port: 8000\n'])
def test_launcher_preserves_configuration_and_delegates_to_web(tmp_path, monkeypatch, content):
    path = Path(__file__).resolve().parents[1] / 'installer/scripts/launch_web.py'
    spec = importlib.util.spec_from_file_location('portable_launcher', path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setattr(launcher, '__file__', str(tmp_path / 'scripts/launch_web.py'))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    config = tmp_path / 'config/settings.yaml'
    config.parent.mkdir()
    if content is not None:
        config.write_text(content)
    runtime = SimpleNamespace(config={'web': {'host': '127.0.0.1', 'port': 8000}})
    application = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
    calls = []
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(__version__='fixture'))
    monkeypatch.setitem(sys.modules, 'src.web.app', SimpleNamespace(create_app=lambda: application))
    class Server:
        started = False
        def __init__(self, config): self.config = config
        def run(self): calls.append(self.config)
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(
        Config=lambda app, **kw: (app, kw), Server=Server))
    assert launcher.main(['--host', '127.0.0.1', '--port', '8881', '--config-guide']) == 0
    assert calls == [(application, {'host': '127.0.0.1', 'port': 8881})]
    assert runtime._startup_port == 8881
    assert Path(os.environ['YOLO_CONFIG_DIR']).is_dir()
    assert (config.read_text() if config.exists() else None) == content
    assert not (config.parent / 'secrets.yaml').exists()
    calls.clear()
    assert launcher.main(['--self-test']) == 0
    assert not calls
    assert (config.read_text() if config.exists() else None) == content


@pytest.mark.parametrize('configured,guide,host,page', [
    (False, False, '127.0.0.1', '/settings'),
    (True, False, '0.0.0.0', '/'),
    (True, True, '127.0.0.1', '/settings'),
    (True, False, '::', '/'),
])
def test_open_browser_after_ready(monkeypatch, configured, guide, host, page):
    import threading
    path = Path(__file__).resolve().parents[1] / 'installer/scripts/launch_web.py'
    spec = importlib.util.spec_from_file_location('ready_launcher', path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    opened = []
    monkeypatch.setattr(launcher.webbrowser, 'open', lambda url: opened.append(url) or True)
    server = SimpleNamespace(started=False)
    stopped = threading.Event()
    runtime = SimpleNamespace(is_paths_configured=lambda: configured)
    # With startup already failed, no other service on this port should be opened.
    stopped.set()
    launcher.open_when_ready(server, runtime, host, 8881, guide, stopped)
    assert not opened
    stopped.clear()
    server.started = True
    launcher.open_when_ready(server, runtime, host, 8881, guide, stopped)
    local = '[::1]' if host == '::' else '127.0.0.1'
    assert opened == [f'http://{local}:8881{page}']
