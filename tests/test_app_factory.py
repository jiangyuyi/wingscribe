import asyncio
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.recognition.protocol import BatchRecognizeRequest, RecognizeRequest


def settings(root, model="bioclip-2"):
    return {"paths": {"sources": [{"path": str(root / "source")}],
                      "output": {"root_dir": str(root / "output")}, "db_path": "db/test.db"},
            "recognition": {"local": {"model_type": model}}}


def test_import_does_not_load_config_or_construct_services(tmp_path):
    script = """
from src.utils import config_loader
from src.metadata.exif_writer import ExifWriter

def forbidden(*args, **kwargs):
    raise AssertionError('Import must not load configuration or create services')
config_loader.load_config = forbidden
config_loader.get_config = forbidden
ExifWriter.__init__ = forbidden
import src.web.app as web
import src.recognition_service as recognition
assert callable(web.create_app)
assert callable(recognition.create_app)
assert not hasattr(web, 'app')
assert not hasattr(recognition, 'app')
"""
    project = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(project))
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_apps_have_separate_paths_tasks_batches_and_models(tmp_path):
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    config = settings(root_a, "bioclip")
    app_a = create_app(root_a, config_override=config)
    app_b = create_app(root_b, config_override=settings(root_b))
    assert not root_a.exists() and not root_b.exists()
    a, b = app_a.state.runtime, app_b.state.runtime
    assert a.task_manager is not b.task_manager
    assert a.db_path == root_a / "db/test.db"
    assert b.db_path == root_b / "db/test.db"
    config["paths"]["sources"][0]["path"] = "changed"
    assert str(a.source_dir) == str(root_a / "source")
    a.task_manager.state = "failed"
    a.task_manager.error = "only app a"
    factory_a, factory_b = app_a.state.recognizer_factory, app_b.state.recognizer_factory
    assert factory_a.create("local").model_options["model_name"] == "bioclip"
    assert factory_b.create("local").model_options["model_name"] == "bioclip-2"
    assert factory_a.create("local") is not factory_b.create("local")
    request = BatchRecognizeRequest(images=[RecognizeRequest(platform="local", image_path="bird.jpg")])
    batch = app_a.state.batch_service.create_batch(request)
    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        assert client_a.get("/api/pipeline/status").json()["error"] == "only app a"
        assert client_b.get("/api/pipeline/status").json()["state"] == "idle"
        assert client_a.get(f"/api/recognition/batch/{batch.batch_id}").status_code == 200
        assert client_b.get(f"/api/recognition/batch/{batch.batch_id}").status_code == 404
    assert a.db_path.exists() and b.db_path.exists()
    assert factory_a._local_instances == {}
    assert factory_b._local_instances == {}


def test_first_run_and_database_failure_keep_settings_available(tmp_path, monkeypatch):
    missing = create_app(tmp_path / "missing")
    with TestClient(missing) as client:
        assert client.get("/settings").status_code == 200
        assert client.get("/api/pipeline/status").status_code == 409
    assert not (tmp_path / "missing").exists()
    broken = create_app(tmp_path / "broken", config_override=settings(tmp_path / "broken"))
    def fail():
        raise OSError("database unavailable")
    monkeypatch.setattr(broken.state.runtime, "create_db_manager", fail)
    with TestClient(broken) as client:
        assert client.get("/settings").status_code == 200
        assert client.get("/api/pipeline/status").status_code == 409
    assert broken.state.runtime.startup_errors


def test_task_uses_application_snapshot(monkeypatch, tmp_path):
    from src.web import task_manager
    config = settings(tmp_path)
    app = create_app(tmp_path, config_override=config)
    captured = {}
    class Runner:
        def __init__(self, path, init_timeout, config_override):
            captured.update(config_override)
            self.db = SimpleNamespace(close=lambda: None)
        def set_progress_callback(self, callback):
            pass
        def set_stop_checker(self, callback):
            pass
        def run(self, **kwargs):
            pass
    monkeypatch.setattr(task_manager, "WingScribePipeline", Runner)
    manager = app.state.runtime.task_manager
    assert manager.start_pipeline()
    manager.wait()
    assert manager.state == "completed"
    assert captured["paths"]["db_path"] == str(tmp_path / "db/test.db")
    assert captured["recognition"]["local"]["model_type"] == "bioclip-2"


def test_cloud_config_injection_does_not_read_personal_settings(monkeypatch):
    from src.recognition.cloud.factory import RecognizerFactory
    def fail():
        pytest.fail("Unexpected personal configuration read")
    monkeypatch.setattr("src.recognition.cloud.huggingface.get_config", fail)
    monkeypatch.setattr("src.recognition.cloud.huggingface.httpx.get", lambda *args, **kwargs: SimpleNamespace(status_code=200))
    factory = RecognizerFactory.configured({"cloud": {"huggingface": {"api_token": "test", "model_id": "example"}}})
    recognizer = factory.create("huggingface")
    assert recognizer._api_token == "test"
    assert recognizer._model_id == "example"


def test_worker_logs_do_not_cross_application_tasks():
    from src.web.task_manager import ListLogHandler, TaskManager
    manager = TaskManager()
    manager.task_id = "task-a"
    handler = ListLogHandler(manager, owner=-1)
    record = logging.LogRecord("test", logging.ERROR, "", 0, "failure", (), None)
    record.threadName = "wingscribe-photo-task-b_0"
    handler.emit(record)
    assert manager.logs == []
    assert manager.error is None
    record.threadName = "wingscribe-photo-task-a_0"
    handler.emit(record)
    assert manager.error == "failure"


def test_shutdown_cancels_owned_batch_work():
    from src.recognition.batch import BatchRecognitionService
    from src.recognition.protocol import BatchJobStatus
    class Recognizer:
        async def recognize_batch(self, *args, **kwargs):
            await asyncio.Event().wait()
    service = BatchRecognitionService(recognizer_factory=SimpleNamespace(create=lambda platform: Recognizer()))
    batch = service.create_batch(BatchRecognizeRequest(images=[RecognizeRequest(platform="local", image_path="bird.jpg")]))
    async def run():
        assert await service.start_batch(batch.batch_id)
        await asyncio.sleep(0)
        await service.close()
        assert service.get_status(batch.batch_id).status == BatchJobStatus.failed
        assert service._running_tasks == {}
    asyncio.run(run())
