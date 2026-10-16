"""Isolate legacy import-time application setup from the personal workspace.

Remove this bootstrap when application construction accepts explicit settings.
The configuration loader itself is restored immediately and remains testable.
"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def pytest_configure(config):
    sandbox = TemporaryDirectory(prefix="wingscribe-tests-")
    config.add_cleanup(sandbox.cleanup)
    root = Path(sandbox.name)
    source = root / "source"
    output = root / "output"
    source.mkdir()
    output.mkdir()
    settings = {
        "paths": {
            "sources": [{"path": str(source), "enabled": True}],
            "output": {"root_dir": str(output)},
            "db_path": str(root / "test.db"),
        }
    }
    from src.utils import config_loader

    real_loader = config_loader.load_config
    with patch.object(config_loader, "load_config", side_effect=lambda *a, **k: deepcopy(settings)):
        from src.web import app as web_app
        from src import recognition_service

    web_app.load_config = real_loader
    recognition_service.load_config = real_loader
