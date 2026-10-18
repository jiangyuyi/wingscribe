"""Explicit application fixtures; importing modules never reads personal settings."""
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def web_app(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("web-app")
    from src.web.app import create_app
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    settings = {"paths": {"sources": [{"path": str(source), "enabled": True}],
                          "output": {"root_dir": str(output)},
                          "db_path": str(tmp_path / "test.db")}}
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    return create_app(tmp_path).state.runtime
