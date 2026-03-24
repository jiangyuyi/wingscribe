import threading
from pathlib import Path

import pandas as pd
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


def test_photo_paths_use_separate_source_and_processed_roots(tmp_path):
    source_root = tmp_path / "source"
    processed_root = tmp_path / "processed"
    source_root.mkdir()
    processed_root.mkdir()

    mgr = IOCManager(
        ":memory:",
        source_base_dir=str(source_root),
        processed_base_dir=str(processed_root),
    )

    try:
        photo_id = mgr.add_photo_record({
            "file_path": str(processed_root / "2026" / "bird.jpg"),
            "original_path": str(source_root / "trip" / "bird.jpg"),
            "filename": "bird.jpg",
            "captured_date": "20260320",
            "location_tag": "Park",
            "primary_bird_cn": "麻雀",
            "scientific_name": "Passer montanus",
            "confidence_score": 0.99,
            "width": 100,
            "height": 100
        })

        row = mgr.conn.execute(
            "SELECT file_path, original_path FROM photos WHERE id = ?",
            (photo_id,)
        ).fetchone()

        assert row["file_path"] == "2026/bird.jpg"
        assert row["original_path"] == "trip/bird.jpg"
        assert mgr.resolve_processed_path(row["file_path"]) == str(processed_root / "2026" / "bird.jpg")
        assert mgr.resolve_original_path(row["original_path"]) == str(source_root / "trip" / "bird.jpg")
    finally:
        mgr.close()


@pytest.fixture
def seeded_db_manager():
    mgr = IOCManager(":memory:")
    try:
        mgr.conn.executemany(
            """
            INSERT INTO taxonomy (
                scientific_name, chinese_name, family_cn, order_cn,
                genus_cn, genus_sci, family_sci, order_sci, english_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "Passer montanus", "楹婚泙", "雀科", "雀形目",
                    "麻雀属", "Passer", "Passeridae", "Passeriformes", "Eurasian Tree Sparrow",
                ),
                (
                    "Parus minor", "大山雀", "山雀科", "雀形目",
                    "山雀属", "Parus", "Paridae", "Passeriformes", "Japanese Tit",
                ),
                (
                    "Cyanopica cyanus", "灰喜鹊", "鸦科", "雀形目",
                    "蓝鹊属", "Cyanopica", "Corvidae", "Passeriformes", "Azure-winged Magpie",
                ),
            ],
        )
        mgr.conn.commit()

        mgr.add_photo_record(
            {
                "file_path": "processed/sparrow-1.jpg",
                "filename": "sparrow-1.jpg",
                "original_path": "source/sparrow-1.jpg",
                "file_hash": "hash-1",
                "captured_date": "20260320",
                "location_tag": "Park",
                "primary_bird_cn": "楹婚泙",
                "scientific_name": "Passer montanus",
                "confidence_score": 0.95,
                "width": 100,
                "height": 100,
            }
        )
        mgr.add_photo_record(
            {
                "file_path": "processed/sparrow-2.jpg",
                "filename": "sparrow-2.jpg",
                "original_path": "source/sparrow-2.jpg",
                "file_hash": "hash-2",
                "captured_date": "20260320",
                "location_tag": "Lake",
                "primary_bird_cn": "楹婚泙",
                "scientific_name": "Passer montanus",
                "confidence_score": 0.88,
                "width": 100,
                "height": 100,
            }
        )
        mgr.add_photo_record(
            {
                "file_path": "processed/tit-1.jpg",
                "filename": "tit-1.jpg",
                "original_path": "source/tit-1.jpg",
                "file_hash": "hash-3",
                "captured_date": "20260321",
                "location_tag": "Forest",
                "primary_bird_cn": "大山雀",
                "scientific_name": "Parus minor",
                "confidence_score": 0.91,
                "width": 100,
                "height": 100,
            }
        )

        yield mgr
    finally:
        mgr.close()


def test_get_bird_info_returns_taxonomy_row(seeded_db_manager):
    result = seeded_db_manager.get_bird_info("Passer montanus")

    assert result is not None
    assert result["chinese_name"] == "楹婚泙"
    assert result["family_cn"] == "雀科"
    assert seeded_db_manager.get_bird_info("") is None


def test_search_taxonomy_returns_mixed_levels_and_respects_limit(seeded_db_manager):
    results = seeded_db_manager.search_taxonomy("山雀", limit=10)

    assert len(results) <= 10
    assert {item["level"] for item in results}.issubset({"order", "family", "genus", "species"})
    assert any(item["level"] == "family" and item["name_cn"] == "山雀科" for item in results)
    assert any(item["level"] == "species" and item["name_cn"] == "大山雀" for item in results)


def test_get_stats_by_level_counts_photos_and_supports_date_filter(seeded_db_manager):
    species_stats = seeded_db_manager.get_stats_by_level("species")
    order_stats_filtered = seeded_db_manager.get_stats_by_level("order", date_filter="20260321")

    assert species_stats[0] == {"name": "楹婚泙", "sci": "Passer montanus", "count": 2}
    assert order_stats_filtered == [{"name": "雀形目", "sci": "Passeriformes", "count": 1}]
    assert seeded_db_manager.get_stats_by_level("invalid") == []


def test_scan_history_round_trip_returns_most_recent_first(seeded_db_manager):
    seeded_db_manager.add_scan_history(
        {
            "start_time": "2026-03-20T10:00:00",
            "end_time": "2026-03-20T10:05:00",
            "range_start": "20260320",
            "range_end": "20260320",
            "processed_count": 2,
            "duration_seconds": 300.0,
            "status": "success",
        }
    )
    seeded_db_manager.add_scan_history(
        {
            "start_time": "2026-03-21T10:00:00",
            "end_time": "2026-03-21T10:03:00",
            "range_start": "20260321",
            "range_end": "20260321",
            "processed_count": 1,
            "duration_seconds": 180.0,
            "status": "success",
        }
    )

    results = seeded_db_manager.get_recent_scans(limit=1)

    assert len(results) == 1
    assert results[0]["range_start"] == "20260321"
    assert results[0]["processed_count"] == 1


def test_species_stats_fast_and_tree_fast_reflect_photo_counts(seeded_db_manager):
    seeded_db_manager.rebuild_species_stats()

    stats = seeded_db_manager.get_species_stats_fast()
    tree = seeded_db_manager.get_taxonomy_tree_fast()

    assert [item["scientific_name"] for item in stats] == ["Passer montanus", "Parus minor"]
    assert stats[0]["photo_count"] == 2
    assert len(tree) == 1
    assert tree[0]["order_cn"] == "雀形目"
    assert tree[0]["photo_count"] == 3
    assert tree[0]["families_count"] == 2


def test_update_photo_species_updates_photo_and_species_stats(seeded_db_manager):
    seeded_db_manager.rebuild_species_stats()
    photo_id = seeded_db_manager.conn.execute(
        "SELECT id FROM photos WHERE filename = ?",
        ("tit-1.jpg",),
    ).fetchone()[0]

    seeded_db_manager.update_photo_species(photo_id, "Passer montanus", "楹婚泙")

    updated_photo = seeded_db_manager.conn.execute(
        "SELECT scientific_name, primary_bird_cn, confidence_score FROM photos WHERE id = ?",
        (photo_id,),
    ).fetchone()
    stats = seeded_db_manager.get_species_stats_fast()
    stats_by_sci = {item["scientific_name"]: item for item in stats}
    all_stats = seeded_db_manager.get_species_stats_fast(min_count=0)
    all_stats_by_sci = {item["scientific_name"]: item for item in all_stats}

    assert updated_photo["scientific_name"] == "Passer montanus"
    assert updated_photo["primary_bird_cn"] == "楹婚泙"
    assert updated_photo["confidence_score"] == 1.0
    assert stats_by_sci["Passer montanus"]["photo_count"] == 3
    assert "Parus minor" not in stats_by_sci
    assert all_stats_by_sci["Parus minor"]["photo_count"] == 0


def test_hash_helpers_report_existing_hashes(seeded_db_manager):
    assert seeded_db_manager.check_hash_exists("hash-1") is True
    assert seeded_db_manager.check_hash_exists("missing-hash") is False
    assert seeded_db_manager.get_all_hashes() == {"hash-1", "hash-2", "hash-3"}


def test_get_taxonomy_tree_supports_include_empty_and_date_filter(seeded_db_manager):
    full_tree = seeded_db_manager.get_taxonomy_tree(include_empty=True)
    filtered_tree = seeded_db_manager.get_taxonomy_tree(include_empty=False, date_filter="20260321")

    assert len(full_tree) == 1
    assert full_tree[0]["order_cn"] == "雀形目"
    assert full_tree[0]["families_count"] == 3

    assert len(filtered_tree) == 1
    assert filtered_tree[0]["photo_count"] == 1
    assert filtered_tree[0]["families_count"] == 1
    assert filtered_tree[0]["families"][0]["family_cn"] == "山雀科"
    assert filtered_tree[0]["families"][0]["genera"][0]["species"][0]["scientific_name"] == "Parus minor"


def test_load_csv_mapping_reads_utf8_sig_file(tmp_path):
    csv_path = tmp_path / "mapping.csv"
    csv_path.write_text(
        "Genus_SCI,Genus_CN\nPasser,麻雀属\nParus,山雀属\n",
        encoding="utf-8-sig",
    )

    mgr = IOCManager(":memory:")
    try:
        mapping = mgr.load_csv_mapping(str(csv_path), "Genus_SCI", "Genus_CN")
    finally:
        mgr.close()

    assert mapping == {"Passer": "麻雀属", "Parus": "山雀属"}


def test_load_genus_mapping_reads_excel_columns(monkeypatch):
    mgr = IOCManager(":memory:")
    fake_df = pd.DataFrame(
        [
            {"属拉丁名": "Passer", "属中文名": "麻雀属"},
            {"属拉丁名": "Parus", "属中文名": "山雀属"},
        ]
    )

    monkeypatch.setattr(pd, "read_excel", lambda *args, **kwargs: fake_df)

    try:
        mapping = mgr.load_genus_mapping("dummy.xlsx")
    finally:
        mgr.close()

    assert mapping == {"Passer": "麻雀属", "Parus": "山雀属"}


def test_import_from_excel_uses_refs_dir_mappings(monkeypatch, tmp_path):
    mgr = IOCManager(":memory:")
    fake_df = pd.DataFrame(
        [
            {
                "IOC_15.1": "Passer montanus",
                "Chinese": "楹婚泙",
                "Family": "Passeridae",
                "Order": "Passeriformes",
                "English": "Eurasian Tree Sparrow",
            },
            {
                "IOC_15.1": "Parus minor",
                "Chinese": "大山雀",
                "Family": "Paridae",
                "Order": "Passeriformes",
                "English": "Japanese Tit",
            },
        ]
    )

    refs_dir = tmp_path / "refs"
    refs_dir.mkdir()
    (refs_dir / "bird_genus_mapping_complete.csv").write_text(
        "Genus_SCI,Genus_CN\nPasser,麻雀属\nParus,山雀属\n",
        encoding="utf-8",
    )
    (refs_dir / "bird_order_mapping_complete.csv").write_text(
        "Order_SCI,Order_CN\nPasseriformes,雀形目\n",
        encoding="utf-8",
    )
    (refs_dir / "bird_family_mapping_complete.csv").write_text(
        "Family_SCI,Family_CN\nPasseridae,雀科\nParidae,山雀科\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mgr, "_read_excel_as_dataframe", lambda _path: fake_df)

    try:
        mgr.import_from_excel("dummy.xlsx", refs_dir=str(refs_dir))
        rows = mgr.conn.execute(
            """
            SELECT scientific_name, chinese_name, family_cn, order_cn, genus_cn, genus_sci, family_sci, order_sci, english_name
            FROM taxonomy
            ORDER BY scientific_name
            """
        ).fetchall()
    finally:
        mgr.close()

    assert [dict(row) for row in rows] == [
        {
            "scientific_name": "Parus minor",
            "chinese_name": "大山雀",
            "family_cn": "山雀科",
            "order_cn": "雀形目",
            "genus_cn": "山雀属",
            "genus_sci": "Parus",
            "family_sci": "Paridae",
            "order_sci": "Passeriformes",
            "english_name": "Japanese Tit",
        },
        {
            "scientific_name": "Passer montanus",
            "chinese_name": "楹婚泙",
            "family_cn": "雀科",
            "order_cn": "雀形目",
            "genus_cn": "麻雀属",
            "genus_sci": "Passer",
            "family_sci": "Passeridae",
            "order_sci": "Passeriformes",
            "english_name": "Eurasian Tree Sparrow",
        },
    ]


def test_pipeline_hot_path_methods_do_not_depend_on_shared_self_conn(tmp_path):
    db_path = tmp_path / "ioc.db"
    mgr = IOCManager(str(db_path))
    original_conn = mgr.conn
    try:
        original_conn.execute(
            """
            INSERT INTO taxonomy (
                scientific_name, chinese_name, family_cn, order_cn,
                genus_cn, genus_sci, family_sci, order_sci, english_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Passer montanus", "麻雀", "雀科", "雀形目",
                "麻雀属", "Passer", "Passeridae", "Passeriformes", "Eurasian Tree Sparrow",
            ),
        )
        original_conn.commit()

        class PoisonConn:
            def execute(self, *args, **kwargs):
                raise AssertionError("shared self.conn should not be used here")

            def commit(self):
                raise AssertionError("shared self.conn should not be used here")

        mgr.conn = PoisonConn()

        assert mgr.get_bird_info("Passer montanus")["chinese_name"] == "麻雀"
        assert mgr.check_hash_exists("missing") is False
        assert mgr.get_all_hashes() == set()

        photo_id = mgr.add_photo_record(
            {
                "file_path": str(tmp_path / "processed" / "bird.jpg"),
                "original_path": str(tmp_path / "source" / "bird.jpg"),
                "filename": "bird.jpg",
                "file_hash": "hash-1",
                "captured_date": "20260324",
                "location_tag": "Park",
                "primary_bird_cn": "麻雀",
                "scientific_name": "Passer montanus",
                "confidence_score": 0.99,
                "width": 100,
                "height": 100,
            }
        )
        assert isinstance(photo_id, int)

        mgr.add_scan_history(
            {
                "start_time": "2026-03-24T10:00:00",
                "end_time": "2026-03-24T10:01:00",
                "range_start": "20260324",
                "range_end": "20260324",
                "processed_count": 1,
                "duration_seconds": 60.0,
                "status": "Stopped",
            }
        )

        verify = sqlite3.connect(str(db_path))
        try:
            photo_count = verify.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            stats_count = verify.execute(
                "SELECT photo_count FROM species_stats WHERE scientific_name = ?",
                ("Passer montanus",),
            ).fetchone()[0]
            history_count = verify.execute("SELECT COUNT(*) FROM scan_history").fetchone()[0]
        finally:
            verify.close()

        assert photo_count == 1
        assert stats_count == 1
        assert history_count == 1
    finally:
        mgr.conn = original_conn
        mgr.close()


def test_add_photo_record_allows_shared_manager_calls_from_multiple_threads(tmp_path):
    db_path = tmp_path / "ioc_threads.db"
    mgr = IOCManager(str(db_path))
    try:
        mgr.conn.execute(
            """
            INSERT INTO taxonomy (
                scientific_name, chinese_name, family_cn, order_cn,
                genus_cn, genus_sci, family_sci, order_sci, english_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Passer montanus", "麻雀", "雀科", "雀形目",
                "麻雀属", "Passer", "Passeridae", "Passeriformes", "Eurasian Tree Sparrow",
            ),
        )
        mgr.conn.commit()

        errors = []

        def worker(index: int):
            try:
                mgr.add_photo_record(
                    {
                        "file_path": str(tmp_path / "processed" / f"bird-{index}.jpg"),
                        "original_path": str(tmp_path / "source" / f"bird-{index}.jpg"),
                        "filename": f"bird-{index}.jpg",
                        "file_hash": f"hash-{index}",
                        "captured_date": "20260324",
                        "location_tag": "Park",
                        "primary_bird_cn": "麻雀",
                        "scientific_name": "Passer montanus",
                        "confidence_score": 0.99,
                        "width": 100,
                        "height": 100,
                    }
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []

        verify = sqlite3.connect(str(db_path))
        try:
            photo_count = verify.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
            stats_count = verify.execute(
                "SELECT photo_count FROM species_stats WHERE scientific_name = ?",
                ("Passer montanus",),
            ).fetchone()[0]
        finally:
            verify.close()

        assert photo_count == 4
        assert stats_count == 4
    finally:
        mgr.close()
