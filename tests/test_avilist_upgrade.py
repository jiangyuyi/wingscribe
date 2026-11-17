import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from src.metadata.avilist import (DEFAULT_CATALOGUE, LEGACY_VERSION, VERSION,
                                 load_catalogue, read_species)
from src.metadata.ioc_manager import IOCManager
from src.metadata.taxonomy_catalogue import current_release, replace_catalogue, migration_guard
from src.storage.catalogue import AssetCatalogue
from src.storage.job_session import JobBusyError, JobSession
from scripts.compare_avilist import compare


@pytest.fixture
def old_library(tmp_path):
    manager = IOCManager(str(tmp_path / 'photos.db'))
    rows, manifest = load_catalogue(DEFAULT_CATALOGUE.with_name('avilist-v2025b.csv'))
    replace_catalogue(manager, rows, manifest)
    manager.add_photo_record({'scientific_name': 'Emberiza aureola', 'primary_bird_cn': '黄胸鹀',
                              'label_source': 'manual', 'file_path': 'preserved.jpg'})
    yield manager
    manager.close()


def test_2026_column_names_are_supported(tmp_path):
    p = tmp_path / '2026.xlsx'
    w = Workbook()
    s = w.active
    s.append(['RANK', 'SCIENTIFIC NAME', 'ORDER', 'FAMILY', 'ENGLISH NAME: AVILIST', 'AVIBASE ID'])
    s.append(['species', 'Testus alpha', 'Testiformes', 'Testidae', 'Test Bird', 'avibase-TEST'])
    w.save(p)
    w.close()
    assert read_species(p)[0]['scientific_name'] == 'Testus alpha'


def test_renamed_chinese_aliases_and_changed_concepts_are_visible():
    rows, _ = load_catalogue()
    bunting = next(r for r in rows if r['scientific_name'] == 'Schoeniclus aureolus')
    assert bunting['chinese_name'] == '黄胸鹀'
    assert 'matching AvibaseID' in bunting['chinese_name_source']
    report = compare(DEFAULT_CATALOGUE.with_name('avilist-v2025b.csv'), DEFAULT_CATALOGUE)
    assert len(report['renamed_same_id']) == 43
    assert len(report['same_name_changed_id']) == 43
    assert report['new_count'] == 11172


def test_upgrade_requires_explicit_version_and_keeps_photos_backups_and_history(old_library, tmp_path):
    rows, manifest = load_catalogue()
    before = [dict(r) for r in old_library.conn.execute('SELECT * FROM photos')]
    with pytest.raises(ValueError, match='release-specific'):
        replace_catalogue(old_library, rows, manifest, tmp_path / 'backups')
    report = replace_catalogue(old_library, rows, manifest, tmp_path / 'backups', upgrade_from=LEGACY_VERSION)
    assert current_release(old_library.conn)['version'] == VERSION
    assert old_library.conn.execute('SELECT count(*) FROM taxonomy').fetchone()[0] == 11172
    assert [dict(r) for r in old_library.conn.execute('SELECT * FROM photos')] == before
    history = old_library.conn.execute('SELECT * FROM taxonomy_release_history').fetchone()
    assert json.loads(history['manifest_json'])['version'] == LEGACY_VERSION
    assert len(json.loads(history['taxonomy_json'])) == 11131
    with sqlite3.connect(report['backup_path']) as backup:
        assert current_release(backup)['version'] == LEGACY_VERSION
        assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert backup.execute('SELECT scientific_name FROM photos').fetchone()[0] == 'Emberiza aureola'
    assert replace_catalogue(old_library, rows, manifest, tmp_path / 'backups',
                             upgrade_from=LEGACY_VERSION)['status'] == 'already_current'
    assert len(list((tmp_path / 'backups').glob('*.db'))) == 1


def test_upgrade_rolls_back_snapshot_and_taxonomy_on_insert_failure(old_library, tmp_path):
    old_library.conn.execute("CREATE TRIGGER reject_new BEFORE INSERT ON taxonomy BEGIN SELECT RAISE(ABORT,'test failure'); END")
    old_library.conn.commit()
    rows, manifest = load_catalogue()
    with pytest.raises(sqlite3.IntegrityError, match='test failure'):
        replace_catalogue(old_library, rows, manifest, tmp_path / 'backups', upgrade_from=LEGACY_VERSION)
    assert current_release(old_library.conn)['version'] == LEGACY_VERSION
    assert old_library.conn.execute('SELECT count(*) FROM taxonomy').fetchone()[0] == 11131
    assert not old_library.conn.execute("SELECT name FROM sqlite_master WHERE name='taxonomy_release_history'").fetchone()


def test_upgrade_rejects_changed_old_data_or_new_payload(old_library, tmp_path):
    rows, manifest = load_catalogue()
    bad = [dict(r) for r in rows]
    bad[0]['chinese_name'] = 'unexpected edit'
    with pytest.raises(ValueError, match='Target catalogue'):
        replace_catalogue(old_library, bad, manifest, tmp_path / 'backups', upgrade_from=LEGACY_VERSION)
    old_library.conn.execute("UPDATE taxonomy SET chinese_name='unexpected edit' WHERE scientific_name='Passer montanus'")
    old_library.conn.commit()
    with pytest.raises(ValueError, match='Active legacy catalogue'):
        replace_catalogue(old_library, rows, manifest, tmp_path / 'backups', upgrade_from=LEGACY_VERSION)
    assert current_release(old_library.conn)['version'] == LEGACY_VERSION


def test_live_worker_blocks_migration_before_writes(old_library, tmp_path):
    rows, manifest = load_catalogue()
    with JobSession(SimpleNamespace(db_path=old_library.db_path)):
        with pytest.raises(JobBusyError):
            replace_catalogue(old_library, rows, manifest, tmp_path / 'backups', upgrade_from=LEGACY_VERSION)
    assert not (tmp_path / 'backups').exists()
    assert current_release(old_library.conn)['version'] == LEGACY_VERSION


def test_unrecovered_running_job_blocks_migration(old_library):
    catalogue = AssetCatalogue(old_library.db_path)
    catalogue.initialize(backup_dir=Path(old_library.db_path).parent / 'schema-backups')
    with JobSession(catalogue) as session:
        session.start('interrupted', {})
    with pytest.raises(RuntimeError, match='recover the running job'):
        with migration_guard(Path(old_library.db_path)):
            pytest.fail('Must reject an unrecovered running job')
