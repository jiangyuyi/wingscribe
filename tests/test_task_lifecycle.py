import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.web import task_manager as module
from src.web.task_manager import TaskManager


def install_runner(monkeypatch, run):
    closed = []
    class Runner:
        def __init__(self, config, init_timeout):
            assert Path(config).is_absolute()
            self.db = SimpleNamespace(close=lambda: closed.append(True))
        def set_progress_callback(self, callback):
            self.progress = callback
        def set_stop_checker(self, callback):
            self.stop = callback
        def run(self, **kwargs):
            run(self)
        def run_by_folders(self, *args, **kwargs):
            run(self)
    monkeypatch.setattr(module, "WingScribePipeline", Runner)
    return closed


def test_simultaneous_starts_allow_only_one_and_preserve_cwd(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    def run(runner):
        entered.set()
        assert release.wait(5)
    closed = install_runner(monkeypatch, run)
    monkeypatch.chdir(tmp_path)
    manager = TaskManager()
    barrier = threading.Barrier(8)
    def start(index):
        barrier.wait()
        return manager.start_pipeline() if index % 2 else manager.start_pipeline_by_folders([str(tmp_path)])
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(start, range(8)))
        assert sum(results) == 1
        assert entered.wait(2)
        assert Path.cwd() == tmp_path
        assert manager.stop()
        assert manager.snapshot()["state"] == "stopping"
        assert manager.is_running
    finally:
        release.set()
        manager._thread.join(5)
    assert manager.snapshot()["state"] == "stopped"
    assert not manager.is_running
    assert closed == [True]
    assert Path.cwd() == tmp_path


@pytest.mark.parametrize("failure", ["exception", "logged"])
def test_failures_are_retained_and_resources_closed(monkeypatch, failure):
    def run(runner):
        runner.progress(1, 3)
        if failure == "logged":
            logging.error("photo failed")
        else:
            raise RuntimeError("photo failed")
    closed = install_runner(monkeypatch, run)
    manager = TaskManager()
    original_handlers = list(logging.getLogger().handlers)
    assert manager.start_pipeline()
    manager._thread.join(5)
    status = manager.snapshot()
    assert status["state"] == "failed"
    assert status["error"] == "photo failed"
    assert status["processed"] == 1
    assert status["finished_at"]
    assert closed == [True]
    assert logging.getLogger().handlers == original_handlers
    install_runner(monkeypatch, lambda runner: None)
    assert manager.start_pipeline()
    manager._thread.join(5)
    assert manager.snapshot()["state"] == "completed"
    assert manager.error is None


def test_thread_start_failure_releases_running_flag(monkeypatch):
    class BrokenThread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            raise RuntimeError("cannot start")
    monkeypatch.setattr(module.threading, "Thread", BrokenThread)
    manager = TaskManager()
    assert not manager.start_pipeline()
    assert manager.snapshot()["state"] == "failed"
    assert not manager.is_running


def test_log_cursor_survives_rollover_and_new_task(monkeypatch):
    manager = TaskManager()
    for i in range(1001):
        manager.broadcast_log(str(i))
    cursor, logs = manager.logs_since()
    assert len(logs) == 1000
    manager.broadcast_log("next")
    cursor, logs = manager.logs_since(cursor)
    assert logs == ["next"]
    manager.task_id = "new"
    manager.logs = ["new task"]
    manager._log_offset = 0
    assert manager.logs_since(cursor)[1] == ["new task"]


def test_service_reports_rejected_start():
    from src.web.pipeline_service import start_pipeline
    manager = SimpleNamespace(is_running=False, start_pipeline=lambda *args: False)
    assert start_pipeline(manager, SimpleNamespace(start_date=None, end_date=None))["status"] == "error"


@pytest.mark.parametrize("by_folders", [False, True])
def test_worker_exception_marks_scan_failed(tmp_path, by_folders):
    from src.pipeline_runner import WingScribePipeline
    source = tmp_path / "source"
    source.mkdir()
    (source / "bird.jpg").write_bytes(b"test")
    runner = WingScribePipeline.__new__(WingScribePipeline)
    runner.config = {"paths": {"sources": [{"path": str(source)}]}}
    runner.source_dir = str(source)
    runner.output_root = str(tmp_path / "output")
    runner.existing_hashes = set()
    runner.total_files = runner.processed_count = 0
    runner._progress_callback = runner._stop_checker = None
    history = []
    runner.db = SimpleNamespace(add_scan_history=history.append)
    def fail(*args):
        raise RuntimeError("worker failure")
    runner.process_image = fail
    with pytest.raises(RuntimeError, match="worker failure"):
        if by_folders:
            runner.run_by_folders([str(source)])
        else:
            runner.run()
    assert history[0]["status"] == "Failed"


def test_pipeline_paths_and_secrets_do_not_depend_on_cwd(tmp_path, monkeypatch):
    import yaml
    import src.pipeline_runner as pipeline
    from src.utils.config_loader import load_config
    monkeypatch.setattr(pipeline, "load_config", load_config)
    project = tmp_path / "project"
    config_dir = project / "config"
    config_dir.mkdir(parents=True)
    other = tmp_path / "unrelated"
    other.mkdir()
    settings = {"paths": {"sources": [{"path": str(project / "source")}],
                            "output": {"root_dir": str(project / "output")},
                            "db_path": "data/db/test.db"},
                "processing": {"yolo_model": "models/detector.pt"}}
    (config_dir / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    (config_dir / "secrets.yaml").write_text("recognition:\n  test_value: correct\n", encoding="utf-8")
    monkeypatch.setattr(pipeline, "PROJECT_ROOT", str(project))
    captured = {}
    def database(path, **kwargs):
        captured["path"] = path
        return SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(pipeline, "IOCManager", database)
    monkeypatch.setattr(pipeline.WingScribePipeline, "_get_taxonomy_labels", lambda self: [])
    monkeypatch.chdir(other)
    runner = pipeline.WingScribePipeline()
    assert captured["path"] == str(project / "data/db/test.db")
    assert runner.config["recognition"]["test_value"] == "correct"
    assert runner.config["processing"]["yolo_model"] == str(project / "models/detector.pt")
    assert Path.cwd() == other


def test_initialization_failure_retains_error(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("initialization failed")
    monkeypatch.setattr(module, "WingScribePipeline", fail)
    manager = TaskManager()
    assert manager.start_pipeline()
    manager._thread.join(5)
    assert manager.snapshot()["state"] == "failed"
    assert manager.error == "initialization failed"


def test_status_endpoint_and_admin_render(web_app, monkeypatch):
    from fastapi.testclient import TestClient
    from src.web import app as web_module
    manager = TaskManager()
    manager.state = "failed"
    manager.error = "test failure"
    monkeypatch.setattr(web_app, "task_manager", manager)
    monkeypatch.setattr(web_app, "get_stats", lambda: {"total_photos": 0, "total_species": 0})
    client = TestClient(web_app.app)
    response = client.get("/api/pipeline/status")
    assert response.status_code == 200
    assert response.json()["state"] == "failed"
    assert response.json()["error"] == "test failure"
    page = client.get("/admin")
    assert page.status_code == 200
    assert 'id="task-state"' in page.text
