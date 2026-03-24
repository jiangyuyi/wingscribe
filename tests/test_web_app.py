import asyncio
from pathlib import Path
from unittest.mock import ANY

import pytest
import yaml

from src.metadata.ioc_manager import IOCManager
from src.web import app as web_app


class StubExifWriter:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def write_metadata(self, image_path, tags):
        self.calls.append((image_path, tags))
        if self.results:
            return self.results.pop(0)
        return True


def _create_test_manager(db_path: Path, source_root: Path, processed_root: Path) -> IOCManager:
    return IOCManager(
        str(db_path),
        source_base_dir=str(source_root),
        processed_base_dir=str(processed_root),
    )


class TemplateRecorder:
    def __init__(self):
        self.calls = []

    def TemplateResponse(self, template_name, context):
        payload = {"template": template_name, "context": context}
        self.calls.append(payload)
        return payload


def test_resolve_processed_web_path_uses_processed_root(tmp_path, monkeypatch):
    processed_root = tmp_path / "processed"
    processed_root.mkdir()
    monkeypatch.setattr(web_app, "processed_dir", processed_root)

    result = web_app.resolve_processed_web_path("birds/output.jpg")

    assert result == "/processed/birds/output.jpg"


def test_serve_processed_file_returns_file_response_for_existing_file(tmp_path, monkeypatch):
    processed_root = tmp_path / "processed"
    processed_root.mkdir()
    image_path = processed_root / "birds" / "output.jpg"
    image_path.parent.mkdir()
    image_path.write_bytes(b"image")
    monkeypatch.setattr(web_app, "processed_dir", processed_root)

    response = web_app.serve_processed_file("birds/output.jpg")

    assert Path(response.path) == image_path


def test_serve_processed_file_raises_404_for_missing_file(tmp_path, monkeypatch):
    processed_root = tmp_path / "processed"
    processed_root.mkdir()
    monkeypatch.setattr(web_app, "processed_dir", processed_root)

    with pytest.raises(web_app.HTTPException) as exc_info:
        web_app.serve_processed_file("birds/missing.jpg")

    assert exc_info.value.status_code == 404


def test_index_redirects_to_settings_when_first_run(monkeypatch):
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)
    monkeypatch.setattr(web_app, "is_first_run", lambda: True)
    monkeypatch.setattr(web_app, "is_paths_configured", lambda: False)

    result = web_app.index(request=object())

    assert result == {
        "template": "settings.html",
        "context": {"request": ANY, "is_first_run": True},
    }


def test_index_builds_photo_page_and_pagination(monkeypatch):
    templates = TemplateRecorder()

    class StubCursor:
        def __init__(self):
            self.executed = []
            self._last_sql = None

        def execute(self, sql, params=None):
            self._last_sql = sql
            self.executed.append((sql, list(params or [])))

        def fetchone(self):
            if "COUNT(*) FROM photos" in self._last_sql:
                return (4,)
            raise AssertionError(f"unexpected fetchone for {self._last_sql}")

        def fetchall(self):
            if "SELECT * FROM photos" in self._last_sql:
                return [
                    {
                        "id": 3,
                        "original_path": "raw/a.jpg",
                        "file_path": "processed/a.jpg",
                        "captured_date": "20260320",
                    },
                    {
                        "id": 2,
                        "original_path": "raw/b.jpg",
                        "file_path": "processed/b.jpg",
                        "captured_date": "20260319",
                    },
                ]
            if "SELECT DISTINCT captured_date" in self._last_sql:
                return [("20260320",), ("20260319",), (None,)]
            raise AssertionError(f"unexpected fetchall for {self._last_sql}")

    class StubConn:
        def __init__(self):
            self.cursor_obj = StubCursor()
            self.closed = False

        def cursor(self):
            return self.cursor_obj

        def close(self):
            self.closed = True

    conn = StubConn()
    monkeypatch.setattr(web_app, "templates", templates)
    monkeypatch.setattr(web_app, "is_first_run", lambda: False)
    monkeypatch.setattr(web_app, "is_paths_configured", lambda: True)
    monkeypatch.setattr(web_app, "get_db_conn", lambda: conn)
    monkeypatch.setattr(web_app, "resolve_web_path", lambda path: f"/raw/{path}")
    monkeypatch.setattr(web_app, "resolve_processed_web_path", lambda path: f"/processed/{path}")

    result = web_app.index(
        request=object(),
        q="sparrow",
        filter="uncertain",
        date="20260320",
        limit=2,
        offset=1,
    )

    assert result["template"] == "index.html"
    context = result["context"]
    assert context["query"] == "sparrow"
    assert context["current_filter"] == "uncertain"
    assert context["current_date"] == "20260320"
    assert context["available_dates"] == ["20260320", "20260319"]
    assert context["has_next"] is True
    assert context["has_prev"] is True
    assert context["next_offset"] == 3
    assert context["prev_offset"] == 0
    assert context["photos"] == [
        {
            "id": 3,
            "original_path": "raw/a.jpg",
            "file_path": "processed/a.jpg",
            "captured_date": "20260320",
            "web_raw_path": "/raw/raw/a.jpg",
            "web_processed_path": "/processed/processed/a.jpg",
        },
        {
            "id": 2,
            "original_path": "raw/b.jpg",
            "file_path": "processed/b.jpg",
            "captured_date": "20260319",
            "web_raw_path": "/raw/raw/b.jpg",
            "web_processed_path": "/processed/processed/b.jpg",
        },
    ]
    assert conn.closed is True
    assert conn.cursor_obj.executed[0][1] == [
        "%sparrow%",
        "%sparrow%",
        "%sparrow%",
        "%sparrow%",
        "待确认鸟种",
        "Uncertain",
        "20260320",
    ]
    assert conn.cursor_obj.executed[1][1][-2:] == [2, 1]


def test_admin_dashboard_uses_settings_template_when_paths_missing(monkeypatch):
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)
    monkeypatch.setattr(web_app, "is_paths_configured", lambda: False)

    result = web_app.admin_dashboard(request=object())

    assert result == {
        "template": "settings.html",
        "context": {"request": ANY, "is_first_run": False},
    }


def test_admin_dashboard_renders_stats_when_paths_configured(monkeypatch):
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)
    monkeypatch.setattr(web_app, "is_paths_configured", lambda: True)
    monkeypatch.setattr(web_app, "get_stats", lambda: {"total_photos": 12, "total_species": 4})

    result = web_app.admin_dashboard(request=object())

    assert result == {
        "template": "admin.html",
        "context": {"request": ANY, "stats": {"total_photos": 12, "total_species": 4}},
    }


def test_settings_page_renders_template(monkeypatch):
    templates = TemplateRecorder()
    monkeypatch.setattr(web_app, "templates", templates)

    result = asyncio.run(web_app.settings_page())

    assert result == {"template": "settings.html", "context": {"request": {}}}


def test_update_label_updates_db_after_file_and_metadata_success(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    processed_root = tmp_path / "processed"
    source_root.mkdir()
    processed_root.mkdir()
    db_path = tmp_path / "wingscribe.db"

    original_file = source_root / "trip" / "bird.jpg"
    original_file.parent.mkdir(parents=True, exist_ok=True)
    original_file.write_bytes(b"original")

    processed_file = processed_root / "trip" / "bird.jpg"
    processed_file.parent.mkdir(parents=True, exist_ok=True)
    processed_file.write_bytes(b"processed")

    manager = _create_test_manager(db_path, source_root, processed_root)
    try:
        manager.conn.execute(
            """
            INSERT INTO taxonomy (scientific_name, chinese_name, family_cn)
            VALUES (?, ?, ?)
            """,
            ("Passer montanus", "麻雀", "雀形目"),
        )
        manager.conn.execute(
            """
            INSERT INTO taxonomy (scientific_name, chinese_name, family_cn)
            VALUES (?, ?, ?)
            """,
            ("Parus minor", "大山雀", "山雀科"),
        )
        manager.conn.commit()

        photo_id = manager.add_photo_record(
            {
                "file_path": str(processed_file),
                "original_path": str(original_file),
                "filename": processed_file.name,
                "captured_date": "20260320",
                "location_tag": "Beijing",
                "primary_bird_cn": "麻雀",
                "scientific_name": "Passer montanus",
                "confidence_score": 0.8,
                "width": 100,
                "height": 100,
                "candidates_json": '[{"sci":"Passer montanus","cn":"麻雀","score":0.8}]',
            }
        )
    finally:
        manager.close()

    monkeypatch.setattr(web_app, "source_dir", source_root)
    monkeypatch.setattr(web_app, "processed_dir", processed_root)
    monkeypatch.setattr(
        web_app,
        "config",
        {
            "recognition": {"alternatives_threshold": 70},
            "paths": {
                "sources": [{"path": str(source_root)}],
                "output": {
                    "root_dir": str(processed_root),
                    "structure_template": "{source_structure}/{filename}_{species_cn}_{confidence}",
                },
            },
        },
    )
    monkeypatch.setattr(
        web_app,
        "create_db_manager",
        lambda: _create_test_manager(db_path, source_root, processed_root),
    )
    exif_writer = StubExifWriter([True, True])
    monkeypatch.setattr(web_app, "exif_writer", exif_writer)

    response = web_app.update_label(
        web_app.UpdateLabelRequest(
            photo_id=photo_id,
            scientific_name="Parus minor",
            chinese_name="大山雀",
        )
    )

    assert response == {"status": "success"}

    verify_manager = _create_test_manager(db_path, source_root, processed_root)
    try:
        row = verify_manager.conn.execute(
            "SELECT scientific_name, primary_bird_cn, confidence_score, file_path, filename FROM photos WHERE id = ?",
            (photo_id,),
        ).fetchone()
    finally:
        verify_manager.close()

    assert row["scientific_name"] == "Parus minor"
    assert row["primary_bird_cn"] == "大山雀"
    assert row["confidence_score"] == 1.0
    assert row["file_path"] == "trip/bird_大山雀_100pct.jpg"
    assert row["filename"] == "bird_大山雀_100pct.jpg"
    assert (processed_root / row["file_path"]).exists()
    assert len(exif_writer.calls) == 2


def test_update_label_does_not_commit_db_when_processed_metadata_write_fails(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    processed_root = tmp_path / "processed"
    source_root.mkdir()
    processed_root.mkdir()
    db_path = tmp_path / "wingscribe.db"

    original_file = source_root / "trip" / "bird.jpg"
    original_file.parent.mkdir(parents=True, exist_ok=True)
    original_file.write_bytes(b"original")

    processed_file = processed_root / "trip" / "bird.jpg"
    processed_file.parent.mkdir(parents=True, exist_ok=True)
    processed_file.write_bytes(b"processed")

    manager = _create_test_manager(db_path, source_root, processed_root)
    try:
        manager.conn.execute(
            """
            INSERT INTO taxonomy (scientific_name, chinese_name, family_cn)
            VALUES (?, ?, ?)
            """,
            ("Passer montanus", "麻雀", "雀形目"),
        )
        manager.conn.execute(
            """
            INSERT INTO taxonomy (scientific_name, chinese_name, family_cn)
            VALUES (?, ?, ?)
            """,
            ("Parus minor", "大山雀", "山雀科"),
        )
        manager.conn.commit()

        photo_id = manager.add_photo_record(
            {
                "file_path": str(processed_file),
                "original_path": str(original_file),
                "filename": processed_file.name,
                "captured_date": "20260320",
                "location_tag": "Beijing",
                "primary_bird_cn": "麻雀",
                "scientific_name": "Passer montanus",
                "confidence_score": 0.8,
                "width": 100,
                "height": 100,
            }
        )
    finally:
        manager.close()

    monkeypatch.setattr(web_app, "source_dir", source_root)
    monkeypatch.setattr(web_app, "processed_dir", processed_root)
    monkeypatch.setattr(
        web_app,
        "config",
        {
            "recognition": {"alternatives_threshold": 70},
            "paths": {
                "sources": [{"path": str(source_root)}],
                "output": {
                    "root_dir": str(processed_root),
                    "structure_template": "{source_structure}/{filename}_{species_cn}_{confidence}",
                },
            },
        },
    )
    monkeypatch.setattr(
        web_app,
        "create_db_manager",
        lambda: _create_test_manager(db_path, source_root, processed_root),
    )
    monkeypatch.setattr(web_app, "exif_writer", StubExifWriter([False]))

    with pytest.raises(web_app.HTTPException) as exc_info:
        web_app.update_label(
            web_app.UpdateLabelRequest(
                photo_id=photo_id,
                scientific_name="Parus minor",
                chinese_name="大山雀",
            )
        )

    assert exc_info.value.status_code == 500

    verify_manager = _create_test_manager(db_path, source_root, processed_root)
    try:
        row = verify_manager.conn.execute(
            "SELECT scientific_name, primary_bird_cn, file_path, filename FROM photos WHERE id = ?",
            (photo_id,),
        ).fetchone()
    finally:
        verify_manager.close()

    assert row["scientific_name"] == "Passer montanus"
    assert row["primary_bird_cn"] == "麻雀"
    assert row["file_path"] == "trip/bird.jpg"
    assert row["filename"] == "bird.jpg"
    assert processed_file.exists()
    assert not (processed_root / "trip" / "bird_大山雀_100pct.jpg").exists()


def test_get_api_stats_returns_get_stats(monkeypatch):
    expected = {"photos": 12, "species": 4}
    monkeypatch.setattr(web_app, "get_stats", lambda: expected)

    assert web_app.get_api_stats() == expected


def test_get_scan_history_uses_manager_and_closes(monkeypatch):
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
    monkeypatch.setattr(web_app, "create_db_manager", lambda: manager)

    result = web_app.get_scan_history()

    assert result == [{"folder_path": "D:/birds"}]
    assert manager.limit == 10
    assert manager.closed is True


def test_taxonomy_and_search_endpoints_forward_requests(monkeypatch):
    class StubManager:
        def __init__(self):
            self.closed = False
            self.calls = []

        def search_species(self, query, limit):
            self.calls.append(("search_species", query, limit))
            return [{"scientific_name": "Parus minor"}]

        def get_taxonomy_tree_fast(self, include_empty):
            self.calls.append(("tree_fast", include_empty))
            return [{"name": "fast"}]

        def get_taxonomy_tree(self, include_empty, date_filter):
            self.calls.append(("tree_date", include_empty, date_filter))
            return [{"name": date_filter}]

        def get_stats_by_level(self, level, date_filter):
            self.calls.append(("stats", level, date_filter))
            return [{"name": level, "count": 2}]

        def search_taxonomy(self, query, limit):
            self.calls.append(("search_taxonomy", query, limit))
            return [{"level": "species", "name": query}]

        def close(self):
            self.closed = True

    managers = []

    def factory():
        manager = StubManager()
        managers.append(manager)
        return manager

    monkeypatch.setattr(web_app, "create_db_manager", factory)

    assert web_app.search_species("tit") == [{"scientific_name": "Parus minor"}]
    assert web_app.get_taxonomy_tree(include_empty=False) == [{"name": "fast"}]
    assert web_app.get_taxonomy_tree(include_empty=True, date="20260320") == [{"name": "20260320"}]
    assert web_app.get_taxonomy_stats(level="family", date="20260320") == [{"name": "family", "count": 2}]
    assert web_app.search_taxonomy(q="sparrow", limit=5) == [{"level": "species", "name": "sparrow"}]

    assert managers[0].calls == [("search_species", "tit", 20)]
    assert managers[1].calls == [("tree_fast", False)]
    assert managers[2].calls == [("tree_date", True, "20260320")]
    assert managers[3].calls == [("stats", "family", "20260320")]
    assert managers[4].calls == [("search_taxonomy", "sparrow", 5)]
    assert all(manager.closed for manager in managers)


def test_validate_config_path_reports_file_and_directory_state(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    data_file = data_dir / "taxonomy.xlsx"
    data_file.write_text("ok", encoding="utf-8")

    directory_result = asyncio.run(web_app.validate_config_path(str(data_dir), path_type="directory"))
    file_result = asyncio.run(web_app.validate_config_path(str(data_file), path_type="file"))
    missing_result = asyncio.run(web_app.validate_config_path(str(tmp_path / "missing"), path_type="directory"))

    assert directory_result == {
        "exists": True,
        "is_directory": True,
        "is_file": False,
        "can_write": True,
        "can_read": True,
    }
    assert file_result == {
        "exists": True,
        "is_directory": False,
        "is_file": True,
        "can_write": True,
        "can_read": True,
    }
    assert missing_result == {
        "exists": False,
        "is_directory": False,
        "is_file": False,
        "can_write": False,
        "can_read": False,
    }


def test_browse_folder_and_file_api_return_success_and_error(monkeypatch):
    async def run_success_cases():
        folder = await web_app.browse_folder_api(title="Folder", initial_path="D:/birds")
        file = await web_app.browse_file_api(title="File", initial_path="D:/birds/list.xlsx", file_types="xlsx|xls")
        return folder, file

    monkeypatch.setattr(
        web_app.asyncio,
        "to_thread",
        lambda func, *args: asyncio.sleep(0, result=func(*args)),
    )
    monkeypatch.setattr(web_app, "open_folder_dialog", lambda title, initial: f"{title}|{initial}")
    monkeypatch.setattr(
        web_app,
        "open_file_dialog",
        lambda title, initial, file_types: f"{title}|{initial}|{file_types}",
    )

    folder_result, file_result = asyncio.run(run_success_cases())

    assert folder_result == {"path": "Folder|D:/birds"}
    assert file_result == {"path": "File|D:/birds/list.xlsx|xlsx|xls"}

    async def run_error_cases():
        folder = await web_app.browse_folder_api()
        file = await web_app.browse_file_api()
        return folder, file

    def fail_to_thread(func, *args):
        raise RuntimeError("dialog unavailable")

    monkeypatch.setattr(web_app.asyncio, "to_thread", fail_to_thread)

    folder_error, file_error = asyncio.run(run_error_cases())

    assert folder_error == {"error": "dialog unavailable", "path": None}
    assert file_error == {"error": "dialog unavailable", "path": None}


def test_download_raw_returns_guidance_message():
    assert web_app.download_raw("raw/a.jpg") == {"error": "Use context menu to save image"}


def test_reset_system_clears_processed_and_reimports_taxonomy(tmp_path, monkeypatch):
    base_dir = tmp_path / "repo"
    base_dir.mkdir()
    processed_root = tmp_path / "processed"
    processed_root.mkdir()
    (processed_root / "bird.jpg").write_bytes(b"processed")
    nested_dir = processed_root / "nested"
    nested_dir.mkdir()
    (nested_dir / "keep.txt").write_text("x", encoding="utf-8")

    db_root = tmp_path / "db"
    db_root.mkdir()
    db_file = db_root / "wingscribe.db"
    db_file.write_text("db", encoding="utf-8")

    source_root = tmp_path / "source"
    source_root.mkdir()

    init_calls = []

    class StubConn:
        def execute(self, sql):
            class StubResult:
                def fetchone(self_inner):
                    return (0,)

            return StubResult()

    class StubManager:
        def __init__(self):
            self.conn = StubConn()
            self.import_calls = []
            self.closed = False

        def import_from_excel(self, excel_path, refs_dir):
            self.import_calls.append((excel_path, refs_dir))

        def close(self):
            self.closed = True

    manager = StubManager()
    monkeypatch.setattr(web_app, "BASE_DIR", base_dir)
    monkeypatch.setattr(web_app, "processed_dir", processed_root)
    monkeypatch.setattr(web_app, "db_path", db_file)
    monkeypatch.setattr(
        web_app,
        "config",
        {
            "paths": {
                "sources": [{"path": str(source_root)}],
                "references_path": "data/references",
                "ioc_list_path": "data/references/ioc.xlsx",
            }
        },
    )
    monkeypatch.setattr(web_app, "init_app_db", lambda: init_calls.append("called"))
    monkeypatch.setattr(web_app, "create_db_manager", lambda: manager)

    result = web_app.reset_system()

    assert result == {"status": "success"}
    assert init_calls == ["called"]
    assert manager.import_calls == [
        (
            str(base_dir / "data/references/ioc.xlsx"),
            str(base_dir / "data/references"),
        )
    ]
    assert manager.closed is True
    assert list(processed_root.iterdir()) == []
    assert not db_file.exists()


def test_rebuild_species_stats_returns_success(monkeypatch):
    class StubManager:
        def __init__(self):
            self.rebuilt = False
            self.closed = False

        def rebuild_species_stats(self):
            self.rebuilt = True

        def close(self):
            self.closed = True

    manager = StubManager()
    monkeypatch.setattr(web_app, "create_db_manager", lambda: manager)

    result = web_app.rebuild_species_stats()

    assert result == {"status": "success", "message": "Species stats table rebuilt"}
    assert manager.rebuilt is True
    assert manager.closed is True


def test_rebuild_species_stats_closes_manager_on_error(monkeypatch):
    class StubManager:
        def __init__(self):
            self.closed = False

        def rebuild_species_stats(self):
            raise RuntimeError("rebuild failed")

        def close(self):
            self.closed = True

    manager = StubManager()
    monkeypatch.setattr(web_app, "create_db_manager", lambda: manager)

    result = web_app.rebuild_species_stats()

    assert result == {"status": "error", "detail": "rebuild failed"}
    assert manager.closed is True


def test_get_config_returns_first_run_when_settings_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "BASE_DIR", tmp_path)

    result = asyncio.run(web_app.get_config())

    assert result == {"error": "Configuration file not found", "is_first_run": True}


def test_search_species_closes_manager_on_error(monkeypatch):
    class StubManager:
        def __init__(self):
            self.closed = False

        def search_species(self, query, limit):
            raise RuntimeError("search failed")

        def close(self):
            self.closed = True

    manager = StubManager()
    monkeypatch.setattr(web_app, "create_db_manager", lambda: manager)

    with pytest.raises(RuntimeError, match="search failed"):
        web_app.search_species("tit")

    assert manager.closed is True


def test_get_config_reads_yaml_when_settings_exists(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.yaml"
    settings_path.write_text(
        yaml.safe_dump({"paths": {"sources": [{"path": "D:/birds"}]}, "web": {"port": 8000}}, sort_keys=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(web_app, "BASE_DIR", tmp_path)
    monkeypatch.setattr(web_app, "get_config_definition", lambda: {"basic": {"web": []}})

    result = asyncio.run(web_app.get_config())

    assert result == {
        "config": {"paths": {"sources": [{"path": "D:/birds"}]}, "web": {"port": 8000}},
        "definition": {"basic": {"web": []}},
        "is_first_run": False,
    }


def test_restart_server_returns_restarting_status(monkeypatch, tmp_path):
    base_dir = tmp_path / "repo"
    base_dir.mkdir()
    popen_calls = {}
    thread_calls = {}

    class StubThread:
        def __init__(self, target=None, daemon=None):
            thread_calls["target"] = target
            thread_calls["daemon"] = daemon
            thread_calls["started"] = False

        def start(self):
            thread_calls["started"] = True

    def fake_popen(cmd, cwd, creationflags):
        popen_calls["cmd"] = cmd
        popen_calls["cwd"] = cwd
        popen_calls["creationflags"] = creationflags

    monkeypatch.setattr(web_app, "BASE_DIR", base_dir)
    monkeypatch.setattr(web_app, "_startup_host", "127.0.0.1")
    monkeypatch.setattr(web_app, "_startup_port", 9000)
    monkeypatch.setattr(web_app, "_startup_python", "python-test")
    monkeypatch.setattr(web_app, "config", {"web": {"host": "0.0.0.0", "port": 8000}})
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr("threading.Thread", StubThread)

    result = asyncio.run(web_app.restart_server())

    assert result == {"status": "restarting", "message": "Server restarting..."}
    assert popen_calls == {
        "cmd": [
            "python-test",
            str(base_dir / "src" / "web" / "app.py"),
            "--host",
            "127.0.0.1",
            "--port",
            "9000",
        ],
        "cwd": str(base_dir),
        "creationflags": ANY,
    }
    assert thread_calls["daemon"] is True
    assert thread_calls["started"] is True


def test_restart_server_returns_error_when_spawn_fails(monkeypatch, tmp_path):
    base_dir = tmp_path / "repo"
    base_dir.mkdir()

    class StubThread:
        def __init__(self, target=None, daemon=None):
            raise AssertionError("exit thread should not be created when spawn fails")

    def fail_popen(*args, **kwargs):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(web_app, "BASE_DIR", base_dir)
    monkeypatch.setattr(web_app, "_startup_host", "127.0.0.1")
    monkeypatch.setattr(web_app, "_startup_port", 9000)
    monkeypatch.setattr(web_app, "_startup_python", "python-test")
    monkeypatch.setattr(web_app, "config", {"web": {"host": "0.0.0.0", "port": 8000}})
    monkeypatch.setattr("subprocess.Popen", fail_popen)
    monkeypatch.setattr("threading.Thread", StubThread)

    result = asyncio.run(web_app.restart_server())

    assert result == {"error": "spawn failed"}


def test_websocket_endpoint_sends_new_logs_and_handles_cancel(monkeypatch):
    accepted = {"value": False}
    sent = []

    class StubWebSocket:
        async def accept(self):
            accepted["value"] = True

        async def send_text(self, text):
            sent.append(text)

    sleep_calls = {"count": 0}

    async def fake_sleep(_seconds):
        sleep_calls["count"] += 1
        raise asyncio.CancelledError()

    monkeypatch.setattr(web_app.task_manager, "logs", ["log-1", "log-2"])
    monkeypatch.setattr(web_app.asyncio, "sleep", fake_sleep)

    asyncio.run(web_app.websocket_endpoint(StubWebSocket()))

    assert accepted["value"] is True
    assert sent == ["log-1", "log-2"]
    assert sleep_calls["count"] == 1


def test_get_stats_returns_counts_and_closes_connection(monkeypatch):
    class StubCursor:
        def __init__(self):
            self.calls = []
            self.results = [(12,), (4,)]

        def execute(self, sql):
            self.calls.append(sql)

        def fetchone(self):
            return self.results.pop(0)

    class StubConn:
        def __init__(self):
            self.cursor_obj = StubCursor()
            self.closed = False

        def cursor(self):
            return self.cursor_obj

        def close(self):
            self.closed = True

    conn = StubConn()
    monkeypatch.setattr(web_app, "get_db_conn", lambda: conn)

    result = web_app.get_stats()

    assert result == {"total_photos": 12, "total_species": 4}
    assert conn.closed is True
    assert conn.cursor_obj.calls == [
        "SELECT COUNT(*) FROM photos",
        "SELECT COUNT(DISTINCT scientific_name) FROM photos",
    ]


def test_get_stats_returns_zero_on_query_error(monkeypatch):
    class StubCursor:
        def execute(self, sql):
            raise RuntimeError("db unavailable")

    class StubConn:
        def __init__(self):
            self.closed = False

        def cursor(self):
            return StubCursor()

        def close(self):
            self.closed = True

    conn = StubConn()
    monkeypatch.setattr(web_app, "get_db_conn", lambda: conn)

    result = web_app.get_stats()

    assert result == {"total_photos": 0, "total_species": 0}
    assert conn.closed is True


def test_get_photos_by_taxonomy_prefers_cn_filters_and_resolves_web_paths(monkeypatch):
    class StubManager:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class StubCursor:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params):
            self.executed.append((sql, list(params)))

        def fetchone(self):
            return (2,)

        def fetchall(self):
            return [
                {"id": 9, "original_path": "raw/a.jpg", "file_path": "processed/a.jpg", "scientific_name": "Parus minor"},
                {"id": 8, "original_path": "raw/b.jpg", "file_path": "processed/b.jpg", "scientific_name": "Parus minor"},
            ]

    class StubConn:
        def __init__(self):
            self.cursor_obj = StubCursor()
            self.closed = False

        def cursor(self):
            return self.cursor_obj

        def close(self):
            self.closed = True

    manager = StubManager()
    conn = StubConn()
    monkeypatch.setattr(web_app, "create_db_manager", lambda: manager)
    monkeypatch.setattr(web_app, "get_db_conn", lambda: conn)
    monkeypatch.setattr(web_app, "resolve_web_path", lambda path: f"/raw/{path}")
    monkeypatch.setattr(web_app, "resolve_processed_web_path", lambda path: f"/processed/{path}")

    result = web_app.get_photos_by_taxonomy(
        order_cn="雀形目",
        order_sci="Passeriformes",
        family_sci="Paridae",
        genus_cn="山雀属",
        genus_sci="Parus",
        scientific_name="Parus minor",
        date="20260320",
        limit=10,
        offset=20,
    )

    assert result == {
        "photos": [
            {
                "id": 9,
                "original_path": "raw/a.jpg",
                "file_path": "processed/a.jpg",
                "scientific_name": "Parus minor",
                "web_raw_path": "/raw/raw/a.jpg",
                "web_processed_path": "/processed/processed/a.jpg",
            },
            {
                "id": 8,
                "original_path": "raw/b.jpg",
                "file_path": "processed/b.jpg",
                "scientific_name": "Parus minor",
                "web_raw_path": "/raw/raw/b.jpg",
                "web_processed_path": "/processed/processed/b.jpg",
            },
        ],
        "total_count": 2,
        "limit": 10,
        "offset": 20,
    }
    assert manager.closed is True
    assert conn.closed is True
    assert conn.cursor_obj.executed[0][1] == ["雀形目", "Paridae", "山雀属", "Parus minor", "20260320"]
    assert conn.cursor_obj.executed[1][1] == ["雀形目", "Paridae", "山雀属", "Parus minor", "20260320", 10, 20]


def test_get_photos_by_taxonomy_uses_scientific_fallback_filters(monkeypatch):
    class StubManager:
        def close(self):
            pass

    class StubCursor:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params):
            self.executed.append((sql, list(params)))

        def fetchone(self):
            return (0,)

        def fetchall(self):
            return []

    class StubConn:
        def __init__(self):
            self.cursor_obj = StubCursor()

        def cursor(self):
            return self.cursor_obj

        def close(self):
            pass

    conn = StubConn()
    monkeypatch.setattr(web_app, "create_db_manager", lambda: StubManager())
    monkeypatch.setattr(web_app, "get_db_conn", lambda: conn)
    monkeypatch.setattr(web_app, "resolve_web_path", lambda path: path)
    monkeypatch.setattr(web_app, "resolve_processed_web_path", lambda path: path)

    web_app.get_photos_by_taxonomy(
        order_sci="Passeriformes",
        family_sci="Paridae",
        genus_sci="Parus",
        limit=5,
        offset=0,
    )

    assert conn.cursor_obj.executed[0][1] == ["Passeriformes", "Paridae", "Parus"]
    assert conn.cursor_obj.executed[1][1] == ["Passeriformes", "Paridae", "Parus", 5, 0]
