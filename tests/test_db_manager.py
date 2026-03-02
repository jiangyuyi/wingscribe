import pytest
import sqlite3
from src.metadata.ioc_manager import IOCManager

@pytest.fixture
def db_manager():
    # Use in-memory DB for testing
    mgr = IOCManager(":memory:")
    yield mgr
    mgr.close()

def test_init_db(db_manager):
    cursor = db_manager.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    assert "taxonomy" in tables
    assert "photos" in tables

def test_add_and_search_photo(db_manager):
    record = {
        "file_path": "/tmp/test.jpg",
        "filename": "test.jpg",
        "captured_date": "20230101",
        "location_tag": "Park",
        "primary_bird_cn": "麻雀",
        "scientific_name": "Passer montanus",
        "confidence_score": 0.99,
        "width": 100,
        "height": 100
    }
    db_manager.add_photo_record(record)
    
    cursor = db_manager.conn.cursor()
    cursor.execute("SELECT * FROM photos WHERE filename='test.jpg'")
    row = cursor.fetchone()
    assert row["primary_bird_cn"] == "麻雀"

def test_taxonomy_search(db_manager):
    # Manually insert taxonomy using conn directly
    db_manager.conn.execute("INSERT INTO taxonomy (scientific_name, chinese_name) VALUES ('Passer montanus', '麻雀')")
    db_manager.conn.commit()

    results = db_manager.search_species("Passer")
    assert len(results) == 1
    assert results[0]["chinese_name"] == "麻雀"

    results_cn = db_manager.search_species("麻雀")
    assert len(results_cn) == 1
