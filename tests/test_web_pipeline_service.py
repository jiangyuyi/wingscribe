from pathlib import Path

from src.web import pipeline_service


def test_start_pipeline_normalizes_blank_dates_via_request_object():
    class StubTaskManager:
        def __init__(self):
            self.is_running = False
            self.calls = []

        def start_pipeline(self, start_date, end_date):
            self.calls.append((start_date, end_date))

    class Req:
        start_date = ""
        end_date = "20260131"

    manager = StubTaskManager()
    result = pipeline_service.start_pipeline(manager, Req())

    assert result == {"status": "success", "message": "Pipeline started"}
    assert manager.calls == [(None, "20260131")]


def test_stop_pipeline_rejects_when_not_running():
    class StubTaskManager:
        is_running = False

    assert pipeline_service.stop_pipeline(StubTaskManager()) == {
        "status": "error",
        "message": "Pipeline is not running",
    }


def test_build_folder_tree_filters_system_directories(tmp_path):
    (tmp_path / "trip-a").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "$RECYCLE.BIN").mkdir()

    result = pipeline_service.build_folder_tree(tmp_path, recursive=False, max_depth=1)

    assert result == [{"name": "trip-a", "path": "trip-a", "type": "folder"}]


def test_get_folder_children_returns_empty_for_missing_path():
    response = pipeline_service.get_folder_children("D:/missing", logger=_StubLogger(), build_folder_tree=lambda *args, **kwargs: [])
    assert response == {"children": []}


class _StubLogger:
    def error(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass
