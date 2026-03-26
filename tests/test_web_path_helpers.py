import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.web import app as web_app
from src.web import path_helpers


def test_app_reexports_path_helpers(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "db_path", tmp_path / "data.db")
    monkeypatch.setattr(web_app, "source_dir", tmp_path / "raw")
    monkeypatch.setattr(web_app, "source_dirs", [tmp_path / "raw"])
    monkeypatch.setattr(web_app, "processed_dir", tmp_path / "processed")

    conn = web_app.get_db_conn()
    try:
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()

    assert web_app.is_absolute_path("D:/photos")
    assert web_app.resolve_web_path("bird.jpg") == path_helpers.resolve_web_path(
        "bird.jpg",
        web_app.source_dirs,
        web_app.logger,
    )


def test_resolve_web_path_selects_matching_source_for_absolute_path(tmp_path):
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    image_path = source_b / "nested" / "bird.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"image")

    result = path_helpers.resolve_web_path(str(image_path), [source_a, source_b], web_app.logger)

    assert result == "/raw/source-1/nested/bird.jpg"


def test_get_raw_file_response_returns_file_for_source_key(tmp_path):
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    image_path = source_b / "nested" / "bird.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"image")

    response = path_helpers.get_raw_file_response("source-1/nested/bird.jpg", [source_a, source_b])

    assert Path(response.path) == image_path


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
