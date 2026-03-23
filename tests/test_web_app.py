from pathlib import Path

import pytest

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


def test_resolve_processed_web_path_uses_processed_root(tmp_path, monkeypatch):
    processed_root = tmp_path / "processed"
    processed_root.mkdir()
    monkeypatch.setattr(web_app, "processed_dir", processed_root)

    result = web_app.resolve_processed_web_path("birds/output.jpg")

    assert result == "/processed/birds/output.jpg"


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
            ("Passer montanus", "麻雀", "雀科"),
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
            ("Passer montanus", "麻雀", "雀科"),
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
