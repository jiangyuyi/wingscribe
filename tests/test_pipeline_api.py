from src.web import app as web_app


class StubThread:
    def __init__(self, target=None, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True


def test_task_manager_start_pipeline_starts_background_thread(monkeypatch):
    created_threads = []

    def fake_thread(target=None, args=(), daemon=None):
        thread = StubThread(target=target, args=args, daemon=daemon)
        created_threads.append(thread)
        return thread

    monkeypatch.setattr(web_app.threading, "Thread", fake_thread)

    manager = web_app.TaskManager()
    manager.should_stop = True

    result = manager.start_pipeline("20260101", "20260131")

    assert result is True
    assert manager.is_running is True
    assert manager.should_stop is False
    assert manager.logs == ["Starting pipeline..."]
    assert len(created_threads) == 1
    assert created_threads[0].target == manager._run_pipeline_thread
    assert created_threads[0].args == ("20260101", "20260131")
    assert created_threads[0].daemon is True
    assert created_threads[0].started is True


def test_task_manager_start_pipeline_by_folders_starts_background_thread(monkeypatch):
    created_threads = []

    def fake_thread(target=None, args=(), daemon=None):
        thread = StubThread(target=target, args=args, daemon=daemon)
        created_threads.append(thread)
        return thread

    monkeypatch.setattr(web_app.threading, "Thread", fake_thread)

    manager = web_app.TaskManager()
    manager.should_stop = True

    result = manager.start_pipeline_by_folders(["D:/photos/trip"], recursive=False)

    assert result is True
    assert manager.is_running is True
    assert manager.should_stop is False
    assert manager.logs == ["Starting pipeline for selected folders..."]
    assert len(created_threads) == 1
    assert created_threads[0].target == manager._run_pipeline_thread_by_folders
    assert created_threads[0].args == (["D:/photos/trip"], False)
    assert created_threads[0].daemon is True
    assert created_threads[0].started is True


def test_task_manager_rejects_duplicate_start():
    manager = web_app.TaskManager()
    manager.is_running = True

    result = manager.start_pipeline("20260101", "20260131")

    assert result is False


def test_start_pipeline_endpoint_normalizes_empty_dates(monkeypatch):
    calls = []

    class StubTaskManager:
        is_running = False

        def start_pipeline(self, start_date, end_date):
            calls.append((start_date, end_date))
            return True

    monkeypatch.setattr(web_app, "task_manager", StubTaskManager())

    response = web_app.start_pipeline(
        web_app.StartPipelineRequest(start_date="", end_date="")
    )

    assert response == {"status": "success", "message": "Pipeline started"}
    assert calls == [(None, None)]


def test_start_pipeline_by_folders_endpoint_forwards_request(monkeypatch):
    calls = []

    class StubTaskManager:
        is_running = False

        def start_pipeline_by_folders(self, paths, recursive):
            calls.append((paths, recursive))
            return True

    monkeypatch.setattr(web_app, "task_manager", StubTaskManager())

    response = web_app.start_pipeline_by_folders(
        web_app.StartPipelineByFoldersRequest(paths=["D:/photos/a", "D:/photos/b"], recursive=False)
    )

    assert response == {"status": "success", "message": "Pipeline started for 2 folder(s)"}
    assert calls == [(["D:/photos/a", "D:/photos/b"], False)]


def test_start_pipeline_by_folders_endpoint_rejects_when_running(monkeypatch):
    class StubTaskManager:
        is_running = True

    monkeypatch.setattr(web_app, "task_manager", StubTaskManager())

    response = web_app.start_pipeline_by_folders(
        web_app.StartPipelineByFoldersRequest(paths=["D:/photos/a"], recursive=True)
    )

    assert response == {"status": "error", "message": "Pipeline already running"}


def test_stop_pipeline_endpoint_sets_stop_flag(monkeypatch):
    class StubTaskManager:
        def __init__(self):
            self.is_running = True
            self.stop_called = False

        def stop(self):
            self.stop_called = True

    manager = StubTaskManager()
    monkeypatch.setattr(web_app, "task_manager", manager)

    response = web_app.stop_pipeline()

    assert response == {"status": "success", "message": "Pipeline stop requested"}
    assert manager.stop_called is True


def test_stop_pipeline_endpoint_rejects_when_not_running(monkeypatch):
    class StubTaskManager:
        is_running = False

    monkeypatch.setattr(web_app, "task_manager", StubTaskManager())

    response = web_app.stop_pipeline()

    assert response == {"status": "error", "message": "Pipeline is not running"}


def test_build_folder_tree_filters_system_directories(tmp_path):
    (tmp_path / "trip-a").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "$RECYCLE.BIN").mkdir()
    (tmp_path / "@Recycle").mkdir()
    (tmp_path / "notes.txt").write_text("not a folder", encoding="utf-8")

    result = web_app._build_folder_tree(tmp_path, recursive=False, base_rel_path="", max_depth=1)

    assert result == [
        {
            "name": "trip-a",
            "path": "trip-a",
            "type": "folder",
        }
    ]


def test_build_folder_tree_recursive_adds_children(tmp_path):
    child = tmp_path / "trip-a"
    grandchild = child / "day-1"
    grandchild.mkdir(parents=True)

    result = web_app._build_folder_tree(tmp_path, recursive=True, base_rel_path="", max_depth=3)

    assert result == [
        {
            "name": "trip-a",
            "path": "trip-a",
            "type": "folder",
            "children": [
                {
                    "name": "day-1",
                    "path": "trip-a/day-1",
                    "type": "folder",
                }
            ],
        }
    ]


def test_get_folder_tree_uses_enabled_existing_sources_only(tmp_path, monkeypatch):
    enabled_source = tmp_path / "enabled"
    enabled_source.mkdir()
    (enabled_source / "trip-a").mkdir()

    disabled_source = tmp_path / "disabled"
    disabled_source.mkdir()
    (disabled_source / "trip-b").mkdir()

    missing_source = tmp_path / "missing"

    monkeypatch.setattr(
        web_app,
        "config",
        {
            "paths": {
                "sources": [
                    {"path": str(enabled_source), "enabled": True},
                    {"path": str(disabled_source), "enabled": False},
                    {"path": str(missing_source), "enabled": True},
                ]
            }
        },
    )

    response = web_app.get_folder_tree()
    expected_path = f"{str(enabled_source)}/trip-a"

    assert response == {
        "tree": [
            {
                "name": "trip-a",
                "path": expected_path,
                "type": "folder",
            }
        ]
    }


def test_get_folder_children_returns_one_level_for_absolute_path(tmp_path):
    target = tmp_path / "trip-a"
    target.mkdir()
    (target / "day-1").mkdir()
    (target / "day-2").mkdir()
    (target / ".hidden").mkdir()

    response = web_app.get_folder_children(str(target))
    expected_base = str(target)

    assert response == {
        "children": [
            {
                "name": "day-1",
                "path": f"{expected_base}/day-1",
                "type": "folder",
            },
            {
                "name": "day-2",
                "path": f"{expected_base}/day-2",
                "type": "folder",
            },
        ]
    }


def test_get_folder_children_returns_empty_for_missing_path(tmp_path):
    response = web_app.get_folder_children(str(tmp_path / "missing"))

    assert response == {"children": []}
