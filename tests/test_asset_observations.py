"""Unreadable inputs must be visible without fabricated file-version evidence."""
import sqlite3

import pytest

from src.storage import catalogue as module
from src.storage.catalogue import AssetCatalogue


@pytest.fixture
def store(tmp_path):
    store = AssetCatalogue(tmp_path / 'assets.db')
    store.initialize()
    return store


def version(tx, source, path='bird.jpg'):
    return tx.register_asset(source, path, size_bytes=10, mtime_ns=1, fingerprint='sha256:sample')


def test_read_failure_records_asset_without_fake_version(store):
    with store.transaction() as tx:
        source = tx.register_source('Y:/photos')
        asset = tx.discover_asset(source, 'bird.jpg')
        observation = tx.record_observation(asset, 'scan-1/photo-1', outcome='failed',
                                            reason='read_failed', error='PermissionError')
        assert tx.discover_asset(source, 'BIRD.JPG') == asset
        assert tx.record_observation(asset, 'scan-1/photo-1', outcome='failed',
                                     reason='read_failed', error='PermissionError') == observation
    assert store.list_versions(asset) == []
    assert store.list_assets(source)[0]['availability'] == 'unknown'
    assert store.list_observations(asset)[0]['version_id'] is None


def test_recovery_uses_same_asset_and_preserves_earlier_failure(store):
    with store.transaction() as tx:
        source = tx.register_source('Y:/photos')
        asset = tx.discover_asset(source, 'bird.jpg')
        tx.record_observation(asset, 'first', outcome='failed', error='disconnected')
    with store.transaction() as tx:
        recovered = version(tx, source)
        tx.record_observation(asset, 'second', outcome='no_detection', version_id=recovered['version_id'])
    assert recovered['asset_id'] == asset
    assert store.list_assets(source)[0]['availability'] == 'available'
    assert [o['outcome'] for o in store.list_observations(asset)] == ['failed', 'no_detection']
    assert len(store.list_versions(asset)) == 1


def test_failure_after_previous_success_does_not_retarget_old_version(store):
    with store.transaction() as tx:
        source = tx.register_source('Y:/photos')
        previous = version(tx, source)
    with store.transaction() as tx:
        asset = tx.discover_asset(source, 'bird.jpg')
        tx.record_observation(asset, 'failed-current-read', outcome='failed', error='cannot establish current version')
    assert store.list_observations(asset)[0]['version_id'] is None
    assert store.list_versions(asset)[0]['id'] == previous['version_id']


def test_observation_cannot_reference_other_asset_or_version(store):
    with store.transaction() as tx:
        source = tx.register_source('Y:/photos')
        first, second = version(tx, source), version(tx, source, 'other.jpg')
        analysis = tx.record_analysis(second['version_id'], 'run-1', model='detector', parameters={},
                                     taxonomy_version='AviList-v2025b', outcome='no_detection')
        with pytest.raises(ValueError, match='Version does not belong'):
            tx.record_observation(first['asset_id'], 'bad-1', outcome='no_detection', version_id=second['version_id'])
        with pytest.raises(ValueError, match='Analysis does not belong'):
            tx.record_observation(first['asset_id'], 'bad-2', outcome='no_detection',
                                  version_id=first['version_id'], analysis_id=analysis)
    assert store.list_observations(first['asset_id']) == []


@pytest.mark.parametrize('kwargs', [dict(outcome='failed'), dict(outcome='skipped'),
                                  dict(outcome='succeeded'), dict(outcome='no_detection'),
                                  dict(outcome='quality_filtered'), dict(outcome='invalid')])
def test_missing_evidence_is_rejected(store, kwargs):
    with store.transaction() as tx:
        asset = tx.discover_asset(tx.register_source('Y:/photos'), 'bird.jpg')
        with pytest.raises(ValueError):
            tx.record_observation(asset, 'attempt', **kwargs)
    assert store.list_observations(asset) == []


def test_skip_retains_reason_and_conflicting_idempotency_key_is_refused(store):
    with store.transaction() as tx:
        asset = tx.discover_asset(tx.register_source('Y:/photos'), 'bird.jpg')
        tx.record_observation(asset, 'attempt', outcome='skipped', reason='outside_date_filter')
        with pytest.raises(ValueError, match='different result'):
            tx.record_observation(asset, 'attempt', outcome='failed', error='different')
    assert store.list_observations(asset)[0]['reason'] == 'outside_date_filter'


def seed_v1(store):
    with store.transaction() as tx:
        source = tx.register_source('Y:/photos')
        asset = version(tx, source)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute('DROP TABLE asset_observations')
        conn.execute('DELETE FROM asset_schema_migrations WHERE version=2')
    return source, asset


def test_v1_upgrade_requires_backup_and_preserves_records(store, tmp_path):
    source, asset = seed_v1(store)
    with pytest.raises(ValueError, match='backup'):
        store.initialize()
    backup = store.initialize(backup_dir=tmp_path / 'backups')
    assert backup.is_file()
    assert store.list_assets(source)[0]['id'] == asset['asset_id']
    assert store.list_versions(asset['asset_id'])[0]['id'] == asset['version_id']
    assert store.list_observations(asset['asset_id']) == []
    assert store.initialize() is None
    with sqlite3.connect(backup) as conn:
        assert conn.execute('SELECT version FROM asset_schema_migrations').fetchall() == [(1,)]


def test_v1_upgrade_failure_rolls_back_new_table_and_version(store, tmp_path, monkeypatch):
    source, asset = seed_v1(store)
    monkeypatch.setattr(module, 'OBSERVATION_DDL', (*module.OBSERVATION_DDL, 'invalid SQL'))
    with pytest.raises(sqlite3.OperationalError):
        store.initialize(backup_dir=tmp_path / 'backups')
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute('SELECT version FROM asset_schema_migrations').fetchall() == [(1,)]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='asset_observations'").fetchall() == []
    assert store.list_assets(source)[0]['id'] == asset['asset_id']


def test_discovery_and_observation_rollback_together(store):
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            source = tx.register_source('Y:/photos')
            asset = tx.discover_asset(source, 'bird.jpg')
            tx.record_observation(asset, 'attempt', outcome='failed', error='read error')
            raise RuntimeError('commit interrupted')
    assert store.list_assets(source) == []
    assert store.list_observations(asset) == []
