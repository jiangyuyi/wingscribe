import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.storage.catalogue import AssetCatalogue
from src.storage.culling import CullingStore
from src.storage import culling as module


@pytest.fixture
def setup(tmp_path):
    catalogue = AssetCatalogue(tmp_path/'db.sqlite')
    catalogue.initialize()
    with catalogue.transaction() as tx:
        source = tx.register_source('D:/photos')
        version = tx.register_asset(source, 'bird.JPG', size_bytes=100, mtime_ns=1,
                                    fingerprint='sha256:'+'a'*64)['version_id']
    store = CullingStore(catalogue.db_path)
    backup = store.initialize(backup_dir=tmp_path/'backups')
    report = {'report_id':'report1','items':{'a':{'sha256':'a'*64}},
              'groups':[{'group_id':'g','version_ids':['a']}]}
    return catalogue, store, source, version, report, backup


def test_backup_and_repeated_migration_preserve_existing_catalogue(setup, tmp_path):
    catalogue, store, _, version, _, backup = setup
    with sqlite3.connect(backup) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('SELECT id FROM asset_versions').fetchone()[0] == version
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='culling_snapshots'").fetchone()
    assert store.initialize(backup_dir=tmp_path/'backups') is None
    assert catalogue.initialize() is None


def test_snapshot_idempotence_conflict_and_restart(setup):
    _, store, _, version, report, _ = setup
    sid = store.save_snapshot('run1', report, {'a':version})
    assert store.save_snapshot('run1', report, {'a':version}) == sid
    restored = CullingStore(store.db_path).get_snapshot(sid)
    assert restored['report'] == report and restored['version_map'] == {'a':version}
    changed = copy.deepcopy(report); changed['report_id'] = 'different'
    with pytest.raises(ValueError, match='different'):
        store.save_snapshot('run1', changed, {'a':version})


def test_reanalysis_preserves_human_decision_but_new_file_does_not_inherit(setup):
    catalogue, store, source, version, report, _ = setup
    store.save_snapshot('run1', report, {'a':version})
    store.set_decision(version, 'keep', note='眼部清晰')
    store.save_snapshot('run2', report, {'a':version})
    assert CullingStore(store.db_path).get_decision(version)['note'] == '眼部清晰'
    with catalogue.transaction() as tx:
        changed = tx.register_asset(source,'bird.JPG',size_bytes=101,mtime_ns=2,
                                    fingerprint='sha256:'+'b'*64)['version_id']
    assert store.get_decision(changed) is None
    assert store.get_decision(version)['decision'] == 'keep'
    store.set_decision(version,'reject')
    assert store.get_decision(version)['decision'] == 'reject'


def test_global_override_inherit_persists_and_does_not_touch_choices(setup):
    _, store, _, version, report, _ = setup
    sid = store.save_snapshot('r',report,{'a':version})
    store.set_decision(version,'keep')
    assert store.get_mode(sid,'g')['effective'] == 'safe'
    store.set_default_mode('relaxed');store.set_group_mode(sid,'g','assist')
    reopened = CullingStore(store.db_path)
    assert reopened.get_mode(sid,'g') == {'default':'relaxed','override':'assist','effective':'assist'}
    reopened.set_group_mode(sid,'g',None)
    assert reopened.get_mode(sid,'g')['effective'] == 'relaxed'
    assert store.get_decision(version)['decision'] == 'keep'
    with pytest.raises(ValueError):store.set_group_mode(sid,'unknown','safe')
    with pytest.raises(ValueError):store.set_default_mode('unknown')


@pytest.mark.parametrize('case',['unknown','hash','ungrouped','duplicate'])
def test_bad_mapping_and_grouping_leave_no_snapshot(setup,case):
    _, store, _, version, report, _ = setup
    mapping = {'a':version}
    if case=='unknown':mapping['a']='unknown'
    if case=='hash':report['items']['a']['sha256']='b'*64
    if case=='ungrouped':report['groups']=[]
    if case=='duplicate':report['groups'][0]['version_ids'].append('a')
    with pytest.raises(ValueError):store.save_snapshot('bad',report,mapping)
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM culling_snapshots').fetchone()[0]==0


def test_sql_failure_rolls_back_entire_snapshot(setup):
    _, store, _, version, report, _ = setup
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("CREATE TRIGGER reject_member BEFORE INSERT ON culling_members BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):store.save_snapshot('bad',report,{'a':version})
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM culling_snapshots').fetchone()[0]==0
    with pytest.raises(sqlite3.IntegrityError):store.set_decision('unknown','keep')


def test_migration_failure_rolls_back_new_tables(tmp_path,monkeypatch):
    catalogue=AssetCatalogue(tmp_path/'db.sqlite');catalogue.initialize()
    monkeypatch.setattr(module,'DDL',(*module.DDL,'invalid SQL'))
    with pytest.raises(sqlite3.OperationalError):
        CullingStore(catalogue.db_path).initialize(backup_dir=tmp_path/'backups')
    with sqlite3.connect(catalogue.db_path) as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'culling_%'").fetchall()


def test_two_writers_share_one_idempotent_snapshot(setup):
    _, store, _, version, report, _ = setup
    def save(_):return CullingStore(store.db_path).save_snapshot('same',report,{'a':version})
    with ThreadPoolExecutor(max_workers=2) as executor:
        ids=list(executor.map(save,range(2)))
    assert ids[0]==ids[1]
