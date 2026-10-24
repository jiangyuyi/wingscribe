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
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=lambda app, **kw: calls.append((app, kw))))
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
