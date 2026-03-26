from src.web import admin_service


class TemplateRecorder:
    def TemplateResponse(self, template_name=None, context=None, *, name=None, **kwargs):
        if name is not None:
            template_name = name
        if context is None:
            context = {}
        return {"template": template_name, "context": context}


def test_admin_dashboard_uses_settings_template_when_paths_missing():
    templates = TemplateRecorder()

    result = admin_service.admin_dashboard(
        request=object(),
        templates=templates,
        is_paths_configured=lambda: False,
        get_stats=lambda: {"total_photos": 1, "total_species": 1},
    )

    assert result == {
        "template": "settings.html",
        "context": {"request": result["context"]["request"], "is_first_run": False},
    }


def test_admin_dashboard_renders_stats_when_paths_configured():
    templates = TemplateRecorder()

    result = admin_service.admin_dashboard(
        request=object(),
        templates=templates,
        is_paths_configured=lambda: True,
        get_stats=lambda: {"total_photos": 12, "total_species": 4},
    )

    assert result == {
        "template": "admin.html",
        "context": {
            "request": result["context"]["request"],
            "stats": {"total_photos": 12, "total_species": 4},
        },
    }


def test_get_stats_returns_counts_and_closes_connection():
    class StubCursor:
        def __init__(self):
            self.calls = []
            self.results = [12, 4]

        def execute(self, sql):
            self.calls.append(sql)

        def fetchone(self):
            return [self.results.pop(0)]

    class StubConn:
        def __init__(self):
            self.cursor_obj = StubCursor()
            self.closed = False

        def cursor(self):
            return self.cursor_obj

        def close(self):
            self.closed = True

    conn = StubConn()

    result = admin_service.get_stats(lambda: conn)

    assert result == {"total_photos": 12, "total_species": 4}
    assert conn.closed is True


def test_get_scan_history_uses_manager_and_closes():
    class StubManager:
        def __init__(self):
            self.closed = False
            self.limit = None

        def get_recent_scans(self, limit):
            self.limit = limit
            return [{"folder_path": "D:/birds"}]

        def close(self):
            self.closed = True

    manager = StubManager()

    result = admin_service.get_scan_history(lambda: manager)

    assert result == [{"folder_path": "D:/birds"}]
    assert manager.limit == 10
    assert manager.closed is True


def test_rebuild_species_stats_closes_manager_on_error():
    class StubManager:
        def __init__(self):
            self.closed = False

        def rebuild_species_stats(self):
            raise RuntimeError("rebuild failed")

        def close(self):
            self.closed = True

    manager = StubManager()

    result = admin_service.rebuild_species_stats(lambda: manager)

    assert result == {"status": "error", "detail": "rebuild failed"}
    assert manager.closed is True
