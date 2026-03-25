import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.web import app as web_app
from src.web import path_helpers


def test_app_reexports_path_helpers(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "db_path", tmp_path / "data.db")
    monkeypatch.setattr(web_app, "source_dir", tmp_path / "raw")
    monkeypatch.setattr(web_app, "processed_dir", tmp_path / "processed")

    conn = web_app.get_db_conn()
    try:
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()

    assert web_app.is_absolute_path("D:/photos")
    assert web_app.resolve_web_path("bird.jpg") == path_helpers.resolve_web_path(
        "bird.jpg",
        web_app.source_dir,
        web_app.logger,
    )


def test_get_processed_file_response_returns_file(tmp_path):
    processed_file = tmp_path / "birds" / "output.jpg"
    processed_file.parent.mkdir(parents=True, exist_ok=True)
    processed_file.write_bytes(b"data")

    response = path_helpers.get_processed_file_response("birds/output.jpg", tmp_path)

    assert str(response.path) == str(processed_file)


def test_get_processed_file_response_raises_404_for_missing_file(tmp_path):
    with pytest.raises(HTTPException) as exc_info:
        path_helpers.get_processed_file_response("birds/missing.jpg", tmp_path)

    assert exc_info.value.status_code == 404


def test_create_db_manager_uses_separate_roots(tmp_path):
    manager = path_helpers.create_db_manager(
        tmp_path / "data.db",
        tmp_path / "raw",
        tmp_path / "processed",
    )

    try:
        assert Path(manager.source_base_dir) == tmp_path / "raw"
        assert Path(manager.processed_base_dir) == tmp_path / "processed"
    finally:
        manager.close()
