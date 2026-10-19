"""B4a persistence contracts; never open the user's settings or database."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.storage import catalogue as module
from src.storage.catalogue import AssetCatalogue


@pytest.fixture
def store(tmp_path):
    value = AssetCatalogue(tmp_path / 'catalogue.db')
    value.initialize()
    return value


def register(tx, source, path='20261001/bird.JPG', **overrides):
    attributes = dict(size_bytes=123, mtime_ns=100, fingerprint='sha256:example', width=7008, height=4672)
    attributes.update(overrides)
    return tx.register_asset(source, path, **attributes)


def query(store, sql):
    with sqlite3.connect(store.db_path) as conn:
        return conn.execute(sql).fetchall()


def test_constructor_does_not_create_directory(tmp_path):
    path = tmp_path / 'absent' / 'db.sqlite'
    AssetCatalogue(path)
    assert not path.parent.exists()


def test_legacy_migration_backup_and_reopen_preserve_labels(tmp_path):
    store = AssetCatalogue(tmp_path / 'legacy.db')
    with sqlite3.connect(store.db_path) as conn:
        conn.execute('CREATE TABLE photos (id INTEGER PRIMARY KEY, label TEXT, manual_verified_at TEXT)')
        conn.execute("INSERT INTO photos VALUES (1, '人工确认鸟种', '2026-10-18')")
        conn.execute('PRAGMA user_version=42')
    with pytest.raises(ValueError, match='backup'):
        store.initialize()
    backup = store.initialize(backup_dir=tmp_path / 'backups')
    assert backup.is_file()
    with sqlite3.connect(backup) as conn:
        assert conn.execute('SELECT * FROM photos').fetchall() == query(store, 'SELECT * FROM photos')
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='assets'").fetchall() == []
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert query(store, 'PRAGMA user_version') == [(42,)]
    assert AssetCatalogue(store.db_path).initialize() is None
    assert len(list((tmp_path / 'backups').iterdir())) == 1
    assert query(store, 'SELECT version FROM asset_schema_migrations ORDER BY version') == [(1,), (2,)]


def test_ddl_failure_rolls_back_entire_migration(tmp_path, monkeypatch):
    store = AssetCatalogue(tmp_path / 'db.sqlite')
    monkeypatch.setattr(module, 'DDL', (*module.DDL[:2], 'not valid SQL'))
    with pytest.raises(sqlite3.OperationalError):
        store.initialize()
    assert query(store, "SELECT name FROM sqlite_master WHERE type='table'") == []


def test_unknown_schema_version_refused(store):
    with sqlite3.connect(store.db_path) as conn:
        conn.execute('UPDATE asset_schema_migrations SET version=999 WHERE version=2')
    with pytest.raises(ValueError, match='Unsupported'):
        store.initialize()


def test_incomplete_schema_refused_instead_of_silent_success(store):
    with sqlite3.connect(store.db_path) as conn:
        conn.execute('DROP TABLE detections')
    with pytest.raises(ValueError, match='Incomplete'):
        store.initialize()


def test_failed_migration_preserves_existing_database(tmp_path, monkeypatch):
    store = AssetCatalogue(tmp_path / 'existing.db')
    with sqlite3.connect(store.db_path) as conn:
        conn.execute('CREATE TABLE photos (label TEXT)')
        conn.execute("INSERT INTO photos VALUES ('manual-label')")
    monkeypatch.setattr(module, 'DDL', (*module.DDL[:2], 'not valid SQL'))
    with pytest.raises(sqlite3.OperationalError):
        store.initialize(backup_dir=tmp_path / 'backups')
    assert query(store, 'SELECT * FROM photos') == [('manual-label',)]
    assert query(store, "SELECT name FROM sqlite_master WHERE type='table'") == [('photos',)]


def test_repeat_registration_and_source_rebinding_preserve_identity(store):
    with store.transaction() as tx:
        source = tx.register_source('Y:/Photos')
        assert source == tx.register_source('y:\\Photos')
        first = register(tx, source)
        again = register(tx, source, '20261001\\BIRD.jpg')
        assert again['asset_id'] == first['asset_id']
        assert again['version_id'] == first['version_id']
        assert not again['created']
        tx.rebind_source(source, '//NAS/photos')
    assert len(store.list_assets(source)) == 1
    assert store.get_source(source)['id'] == source
    assert store.get_source('missing') is None
    assert query(store, 'SELECT root_path FROM asset_sources') == [('//NAS/photos/',)]
    assert len(query(store, 'SELECT * FROM asset_versions')) == 1


def test_two_sources_same_name_and_fingerprint_stay_separate(store):
    with store.transaction() as tx:
        first = register(tx, tx.register_source('Y:/photos'))
        second = register(tx, tx.register_source('Z:/photos'))
    assert first['asset_id'] != second['asset_id']


@pytest.mark.parametrize('changed', [dict(size_bytes=124), dict(mtime_ns=101), dict(fingerprint='sha256:changed')])
def test_file_change_creates_version_without_retargeting_old_job(store, changed):
    with store.transaction() as tx:
        source = tx.register_source('Y:/photos')
        original = register(tx, source)
        job = tx.create_job('request-1', {'model': 'bioclip-2'})
        item = tx.enqueue(job, original['version_id'])
        newer = register(tx, source, **changed)
    assert newer['asset_id'] == original['asset_id']
    assert newer['revision'] == 2
    assert newer['version_id'] != original['version_id']
    assert [row['revision'] for row in store.list_versions(original['asset_id'])] == [1, 2]
    assert store.list_job_items(job)[0]['version_id'] == original['version_id']
    assert store.list_job_items(job)[0]['id'] == item


def test_transaction_failure_rolls_back_related_records(store):
    with pytest.raises(RuntimeError, match='interrupted'):
        with store.transaction() as tx:
            source = tx.register_source('Y:/photos')
            asset = register(tx, source)
            tx.enqueue(tx.create_job('request-1', {}), asset['version_id'])
            raise RuntimeError('interrupted before commit')
    for table in ('asset_sources', 'assets', 'asset_versions', 'processing_jobs', 'job_items'):
        assert query(store, f'SELECT count(*) FROM {table}') == [(0,)]


@pytest.mark.parametrize('path', ['../bird.jpg', '/bird.jpg', 'C:/bird.jpg', 'C:bird.jpg',
                                 'folder/../bird.jpg', 'folder/./bird.jpg', 'bird.jpg:stream',
                                 '//NAS/share/bird.jpg', 'folder./bird.jpg', ''])
def test_invalid_relative_paths_rejected_without_rows(store, path):
    with store.transaction() as tx:
        source = tx.register_source('Y:/photos')
        with pytest.raises(ValueError):
            register(tx, source, path)
    assert store.list_assets(source) == []


def test_foreign_keys_protect_missing_source_and_version(store):
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as tx:
            register(tx, 'missing')
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as tx:
            tx.enqueue(tx.create_job('bad', {}), 'missing')
    assert query(store, 'SELECT count(*) FROM processing_jobs') == [(0,)]


def test_source_rebinding_collision_is_not_a_merge(store):
    with store.transaction() as tx:
        first = tx.register_source('Y:/photos')
        second = tx.register_source('Z:/photos')
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as tx:
            tx.rebind_source(second, 'Y:/photos')
    assert len(query(store, 'SELECT * FROM asset_sources')) == 2
    assert first != second


@pytest.mark.parametrize('outcome', ['succeeded', 'no_detection', 'quality_filtered', 'failed'])
def test_analysis_outcomes_persist_without_changing_asset_identity(store, outcome):
    with store.transaction() as tx:
        asset = register(tx, tx.register_source('Y:/photos'))
        kwargs = dict(model='yolo26n+bioclip2', parameters={'quality_mode': 'score_only'},
                      taxonomy_version='AviList-v2025b', outcome=outcome,
                      error='Unreadable image' if outcome == 'failed' else None)
        analysis = tx.record_analysis(asset['version_id'], 'run-1', **kwargs)
        assert analysis == tx.record_analysis(asset['version_id'], 'run-1', **kwargs)
        with pytest.raises(ValueError, match='different result'):
            tx.record_analysis(asset['version_id'], 'run-1', **{**kwargs, 'model': 'other'})
    assert query(store, 'SELECT outcome FROM analysis_runs') == [(outcome,)]
    assert len(query(store, 'SELECT * FROM assets')) == 1


def test_multiple_birds_are_children_of_one_analysis_and_asset(store):
    with store.transaction() as tx:
        asset = register(tx, tx.register_source('Y:/photos'))
        tx.record_analysis(asset['version_id'], 'run-1', model='yolo26n+bioclip2', parameters={},
                           taxonomy_version='AviList-v2025b', outcome='succeeded', detections=[
                               {'bbox': [1, 2, 30, 40], 'confidence': .9, 'result': {'quality': .7}, 'output_path': 'out/1.jpg'},
                               {'bbox': [50, 60, 90, 100], 'confidence': .8, 'result': {'quality': .6}}])
    assert query(store, 'SELECT count(*) FROM assets') == [(1,)]
    assert query(store, 'SELECT count(*) FROM detections') == [(2,)]
    analyses = store.list_analyses(asset['version_id'])
    assert len(analyses) == 1
    assert [d['ordinal'] for d in store.list_detections(analyses[0]['id'])] == [0, 1]


def test_invalid_second_detection_leaves_no_partial_analysis(store):
    with store.transaction() as tx:
        asset = register(tx, tx.register_source('Y:/photos'))
        with pytest.raises(ValueError):
            tx.record_analysis(asset['version_id'], 'run-1', model='model', parameters={},
                               taxonomy_version='AviList-v2025b', outcome='succeeded', detections=[
                                   {'bbox': [0, 0, 10, 10], 'confidence': .8},
                                   {'bbox': [0, 0, float('nan'), 10], 'confidence': .8}])
    assert query(store, 'SELECT count(*) FROM analysis_runs') == [(0,)]


def test_job_request_idempotency_and_durable_items(store):
    with store.transaction() as tx:
        asset = register(tx, tx.register_source('Y:/photos'))
        job = tx.create_job('request-1', {'model': 'bioclip-2'})
        assert job == tx.create_job('request-1', {'model': 'bioclip-2'})
        with pytest.raises(ValueError, match='different parameters'):
            tx.create_job('request-1', {'model': 'other'})
        item = tx.enqueue(job, asset['version_id'])
        assert tx.enqueue(job, asset['version_id']) == item
    reopened = AssetCatalogue(store.db_path)
    assert reopened.list_job_items(job)[0]['status'] == 'pending'
    assert len(reopened.list_job_items(job)) == 1
    assert reopened.get_job(job)['request_key'] == 'request-1'
    assert reopened.get_job('missing') is None


def test_independent_instances_cannot_duplicate_registration(store):
    def work(_):
        instance = AssetCatalogue(store.db_path)
        with instance.transaction() as tx:
            source = tx.register_source('Y:/photos')
            return register(tx, source)['version_id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(work, range(8)))) == 1
    assert query(store, 'SELECT count(*) FROM assets') == [(1,)]
    assert query(store, 'SELECT count(*) FROM asset_versions') == [(1,)]
