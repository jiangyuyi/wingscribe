import json
import sqlite3
from pathlib import Path

import pytest
from openpyxl import Workbook

from src.metadata.avilist import DEFAULT_CATALOGUE, FIELDS, load_catalogue, read_species, sha256
from src.metadata.ioc_manager import IOCManager
from src.metadata.taxonomy_catalogue import current_release, ensure_taxonomy, replace_catalogue


def species(name="Testus alpha", identity="avibase-TEST0001"):
    return dict(zip(FIELDS, (name, "显示名", "科", "目", "属", name.split()[0], "Testidae", "Testiformes", "Test Bird", identity, "test display alias")))


def manifest(count=1):
    return {"version": "test-release", "species_count": count, "catalogue_sha256": "test-checksum"}


@pytest.fixture
def legacy(tmp_path):
    manager = IOCManager(str(tmp_path / "legacy.db"))
    manager.conn.execute("INSERT INTO taxonomy (scientific_name,chinese_name) VALUES ('Testus alpha','原名')")
    manager.conn.commit()
    manager.add_photo_record({"scientific_name": "Testus alpha", "primary_bird_cn": "原名", "label_source": "manual"})
    yield manager
    manager.close()


def test_pinned_catalogue_is_complete_and_names_are_sourced():
    rows, release = load_catalogue()
    assert len(rows) == 11131
    assert release["version"] == "AviList-v2025b"
    assert len({row["taxon_id"] for row in rows}) == 11131
    bulbul = next(row for row in rows if row["scientific_name"] == "Pycnonotus sinensis")
    assert bulbul["chinese_name"] == "白头鹎"
    assert "concept unverified" in bulbul["chinese_name_source"]
    assert bulbul["order_cn"] == "雀形目"


def test_catalogue_tampering_is_rejected(tmp_path):
    path = tmp_path / "catalogue.csv"
    path.write_bytes(DEFAULT_CATALOGUE.read_bytes() + b"tampering")
    path.with_suffix(".json").write_bytes(DEFAULT_CATALOGUE.with_suffix(".json").read_bytes())
    with pytest.raises(ValueError, match="checksum"):
        load_catalogue(path)


def test_parser_filters_rank_and_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "list.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(["Taxon_rank", "Scientific_name", "Order", "Family", "English_name_AviList", "AvibaseID"])
    sheet.append(["genus", "Testus", "Order", "Family", None, None])
    sheet.append(["species", "Testus alpha", "Order", "Family", "Test bird", "id-1"])
    sheet.append(["subspecies", "Testus alpha alpha", "Order", "Family", None, None])
    book.save(path)
    assert [row["scientific_name"] for row in read_species(path)] == ["Testus alpha"]
    sheet.append(["species", "Testus beta", "Order", "Family", "Test bird 2", "id-1"])
    book.save(path)
    book.close()
    with pytest.raises(ValueError, match="duplicate taxon_id"):
        read_species(path)


def test_migration_preserves_labels_and_backup_and_is_idempotent(legacy, tmp_path):
    before = dict(legacy.conn.execute("SELECT * FROM photos").fetchone())
    report = replace_catalogue(legacy, [species()], manifest(), tmp_path / "backups")
    assert report["photo_labels_rewritten"] == 0
    assert dict(legacy.conn.execute("SELECT * FROM photos").fetchone()) == before
    assert legacy.conn.execute("SELECT chinese_name FROM taxonomy_legacy").fetchone()[0] == "原名"
    assert report["review"][0]["status"] == "same_name_unverified"
    backup = sqlite3.connect(report["backup_path"])
    try:
        assert backup.execute("SELECT chinese_name FROM taxonomy").fetchone()[0] == "原名"
        assert backup.execute("SELECT primary_bird_cn FROM photos").fetchone()[0] == "原名"
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        backup.close()
    assert current_release(legacy.conn)["version"] == "test-release"
    assert replace_catalogue(legacy, [species()], manifest(), tmp_path / "backups")["status"] == "already_current"
    assert len(list((tmp_path / "backups").iterdir())) == 1
    new_id = legacy.add_photo_record({"scientific_name": "Testus alpha"})
    assert legacy.conn.execute("SELECT taxonomy_version FROM photos WHERE id=?", (new_id,)).fetchone()[0] == "test-release"


def test_migration_rolls_back_catalogue_and_schema_on_insert_failure(legacy, tmp_path):
    bad = species()
    bad["chinese_name"] = object()  # Invalid SQLite parameter after DDL begins.
    with pytest.raises(sqlite3.ProgrammingError):
        replace_catalogue(legacy, [bad], manifest(), tmp_path / "backups")
    assert current_release(legacy.conn) is None
    assert legacy.conn.execute("SELECT chinese_name FROM taxonomy").fetchone()[0] == "原名"
    assert not legacy.conn.execute("SELECT 1 FROM sqlite_master WHERE name='taxonomy_legacy'").fetchone()
    assert legacy.conn.execute("SELECT count(*) FROM photos").fetchone()[0] == 1


def test_unknown_split_or_merge_never_guesses_photo_assignment(legacy, tmp_path):
    # Similar names or more new species cannot establish an equivalent concept.
    rows = [species("Testus beta", "id-2"), species("Testus gamma", "id-3")]
    report = replace_catalogue(legacy, rows, manifest(2), tmp_path / "backups")
    assert report["review"] == [{"legacy_name": "Testus alpha", "candidate_name": None, "status": "unmatched"}]
    assert legacy.conn.execute("SELECT scientific_name FROM photos").fetchone()[0] == "Testus alpha"


def test_existing_database_requires_backup(legacy):
    with pytest.raises(ValueError, match="backup directory"):
        replace_catalogue(legacy, [species()], manifest())
    assert current_release(legacy.conn) is None


def test_unversioned_region_list_cannot_exclude_new_avilist_species():
    from src.pipeline_runner import WingScribePipeline

    pipeline = WingScribePipeline.__new__(WingScribePipeline)
    pipeline.config = {"recognition": {"region_filter": "china"}}
    pipeline.taxonomy_version = "AviList-v2025b"
    pipeline.all_labels = ["Testus alpha", "Testus beta"]
    pipeline.china_allowlist = {"Testus alpha"}
    assert pipeline._select_candidate_labels("Beijing") == pipeline.all_labels
    pipeline.config["paths"] = {"china_list_taxonomy_version": "AviList-v2025b"}
    assert pipeline._select_candidate_labels("Beijing") == ["Testus alpha"]


def test_empty_database_bootstraps_avilist_and_legacy_database_is_not_auto_migrated(legacy, tmp_path):
    ensure_taxonomy(legacy, {})
    assert current_release(legacy.conn) is None
    manager = IOCManager(str(tmp_path / "new.db"))
    try:
        ensure_taxonomy(manager, {})
        assert manager.conn.execute("SELECT count(*) FROM taxonomy").fetchone()[0] == 11131
        assert current_release(manager.conn)["version"] == "AviList-v2025b"
        with pytest.raises(ValueError, match="versioned"):
            manager.import_from_excel("unused.xlsx")
    finally:
        manager.close()
