import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.metadata.ioc_manager import IOCManager
from src.storage.archive_publication import ArchivePublisher
from src.storage.catalogue import AssetCatalogue


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / 'output'
    store = IOCManager(str(tmp_path / 'db.sqlite'), source_base_dir=str(tmp_path), processed_base_dir=str(root))
    catalogue = AssetCatalogue(store.db_path)
    catalogue.initialize(backup_dir=tmp_path / 'backups')
    with catalogue.transaction() as tx:
        source = tx.register_source(str(tmp_path))
        version = tx.register_asset(source, 'source.jpg', size_bytes=1, mtime_ns=1, fingerprint='sha256:a')['version_id']
    crop = tmp_path / 'crop.jpg'
    crop.write_bytes(b'prepared jpeg fixture')
    publisher = ArchivePublisher(catalogue, store, root)
    record = {'file_path': str(root / 'bird.jpg'), 'filename': 'bird.jpg', 'scientific_name': 'Bird one',
              'original_path': str(tmp_path / 'source.jpg'), 'label_source': 'automatic'}
    def publish(writer=None, **changes):
        return publisher.publish(crop, record['file_path'], record, {},
                                 writer or SimpleNamespace(write_metadata=lambda *args: True),
                                 version_id=version, reuse_key=changes.get('reuse_key', 'same'))
    yield publisher, store, catalogue, publish, record
    store.close()


def query(cat, table):
    return cat._read(f'SELECT * FROM {table}', ())


def test_publish_and_reuse_preserve_manual_labels(archive):
    publisher, store, cat, publish, record = archive
    path = publish()
    photo = query(cat, 'photos')[0]
    store.update_photo_species(photo['id'], 'Manual bird', 'manual')
    assert publish() == path
    assert publisher.recover() == 0
    assert len(query(cat, 'photos')) == len(query(cat, 'archive_publications')) == 1
    assert query(cat, 'photos')[0]['scientific_name'] == 'Manual bird'


def test_metadata_failure_never_publishes_or_registers(archive):
    publisher, store, cat, publish, record = archive
    with pytest.raises(RuntimeError, match='metadata'):
        publish(SimpleNamespace(write_metadata=lambda *args: False))
    assert not Path(record['file_path']).exists()
    assert not query(cat, 'photos') and not query(cat, 'archive_publications')
    assert list(publisher.output_root.glob('.wingscribe-*.pending.jpg'))


def test_photo_and_journal_commit_roll_back_together_then_recover(archive, monkeypatch):
    publisher, store, cat, publish, record = archive
    original = store.insert_photo_record_conn
    def fail(conn, data):
        original(conn, data)
        raise RuntimeError('injected failure after photo insert')
    monkeypatch.setattr(store, 'insert_photo_record_conn', fail)
    with pytest.raises(RuntimeError, match='after photo insert'):
        publish()
    assert Path(record['file_path']).is_file()
    assert not query(cat, 'photos')
    assert query(cat, 'archive_publications')[0]['status'] == 'pending'
    monkeypatch.setattr(store, 'insert_photo_record_conn', original)
    assert publisher.recover() == 1
    assert publisher.recover() == 0
    assert publish() == record['file_path']
    assert len(query(cat, 'photos')) == 1


def test_pending_published_hash_conflict_is_not_overwritten(archive, monkeypatch):
    publisher, store, cat, publish, record = archive
    original = store.insert_photo_record_conn
    monkeypatch.setattr(store, 'insert_photo_record_conn', lambda *args: (_ for _ in ()).throw(RuntimeError('database offline')))
    with pytest.raises(RuntimeError):
        publish()
    Path(record['file_path']).write_bytes(b'user-modified contents')
    monkeypatch.setattr(store, 'insert_photo_record_conn', original)
    with pytest.raises(RuntimeError, match='hash conflict'):
        publisher.recover()
    assert Path(record['file_path']).read_bytes() == b'user-modified contents'
    assert not query(cat, 'photos')
    assert query(cat, 'archive_publications')[0]['error']


def test_prepared_stage_can_be_published_after_interruption(archive, monkeypatch):
    publisher, store, cat, publish, record = archive
    complete = publisher._complete
    monkeypatch.setattr(publisher, '_complete', lambda *args: (_ for _ in ()).throw(RuntimeError('before publish')))
    with pytest.raises(RuntimeError):
        publish()
    assert not Path(record['file_path']).exists()
    monkeypatch.setattr(publisher, '_complete', complete)
    assert publisher.recover() == 1
    assert Path(record['file_path']).is_file() and len(query(cat, 'photos')) == 1


def test_existing_destination_and_external_path_are_rejected(archive):
    publisher, store, cat, publish, record = archive
    path = Path(record['file_path'])
    path.parent.mkdir()
    path.write_bytes(b'preexisting')
    with pytest.raises(FileExistsError):
        publish()
    assert path.read_bytes() == b'preexisting'
    record['file_path'] = str(path.parent.parent / 'outside.jpg')
    with pytest.raises(ValueError, match='outside'):
        publish()


def test_real_process_death_after_publish_recovers_once(archive):
    publisher, store, cat, publish, record = archive
    version = query(cat, 'asset_versions')[0]['id']
    script = '''
import os,sys,json
from types import SimpleNamespace
from src.metadata.ioc_manager import IOCManager
from src.storage.catalogue import AssetCatalogue
from src.storage.archive_publication import ArchivePublisher
store=IOCManager(sys.argv[1],source_base_dir=sys.argv[2],processed_base_dir=sys.argv[3])
store.insert_photo_record_conn=lambda *args: os._exit(23)
p=ArchivePublisher(AssetCatalogue(sys.argv[1]),store,sys.argv[3])
r=json.loads(sys.argv[5])
p.publish(sys.argv[2]+'/crop.jpg',r['file_path'],r,{},SimpleNamespace(write_metadata=lambda *args: True),version_id=sys.argv[4],reuse_key='same')
'''
    result = subprocess.run([sys.executable, '-c', script, str(cat.db_path), str(cat.db_path.parent),
                             str(publisher.output_root), version, json.dumps(record)], timeout=30)
    assert result.returncode == 23
    assert Path(record['file_path']).is_file() and not query(cat, 'photos')
    assert publisher.recover() == 1
    assert publisher.recover() == 0 and len(query(cat, 'photos')) == 1


def test_v2_upgrade_backed_up_and_atomic(archive, tmp_path, monkeypatch):
    import src.storage.catalogue as module
    _, _, cat, _, _ = archive
    with sqlite3.connect(cat.db_path) as conn:
        conn.execute('DROP TABLE archive_publications')
        conn.execute('DELETE FROM asset_schema_migrations WHERE version=3')
    ddl = module.ARCHIVE_DDL
    monkeypatch.setattr(module, 'ARCHIVE_DDL', (*ddl, 'invalid SQL'))
    with pytest.raises(sqlite3.OperationalError):
        cat.initialize(backup_dir=tmp_path / 'failed-backup')
    with sqlite3.connect(cat.db_path) as conn:
        assert conn.execute('SELECT version FROM asset_schema_migrations').fetchall() == [(1,), (2,)]
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='archive_publications'").fetchall()
    monkeypatch.setattr(module, 'ARCHIVE_DDL', ddl)
    backup = cat.initialize(backup_dir=tmp_path / 'upgrade-backup')
    with sqlite3.connect(backup) as conn:
        assert conn.execute('SELECT version FROM asset_schema_migrations').fetchall() == [(1,), (2,)]
    assert cat.initialize() is None
