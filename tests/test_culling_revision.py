import copy
import sqlite3

import pytest

from src.core.focus import ALGORITHM_VERSION, FocusEvidence, FocusPolicy
from src.core.focus_modes import report_modes
from src.storage.catalogue import AssetCatalogue
from src.storage.culling import CullingStore


@pytest.fixture
def saved(tmp_path):
    catalogue = AssetCatalogue(tmp_path / 'db.sqlite')
    catalogue.initialize()
    store = CullingStore(catalogue.db_path)
    store.initialize(backup_dir=tmp_path / 'backups')
    items, mapping = {}, {}
    with catalogue.transaction() as tx:
        source = tx.register_source(str(tmp_path / 'photos'))
        for i, key in enumerate('abcd'):
            sha = key * 64
            version = tx.register_asset(source, key + '.jpg', size_bytes=10, mtime_ns=1,
                                        fingerprint='sha256:' + sha)['version_id']
            mapping[key] = version
            evidence = FocusEvidence(key, sha, ALGORITHM_VERSION, FocusPolicy(), 'rankable', (),
                                     0, (0, 0, 100, 100), {}, float(i + 1))
            items[key] = {'sha256': sha, 'evidence': evidence.to_dict()}
    groups = []
    for gid, keys in [('g1', ['a', 'b']), ('g2', ['c', 'd'])]:
        group = dict(group_id=gid, version_ids=keys, reason='time_candidate',
                     ranking={'tie_fraction': 0.05, 'max_side_ratio': 2.0})
        group['ranking_modes'] = report_modes(group, items)
        group['ranking'] = group['ranking_modes']['safe']
        groups.append(group)
    sid = store.save_snapshot('original', {'report_id': 'original', 'items': items, 'groups': groups}, mapping)
    return store, sid, mapping


def test_split_merge_preserve_evidence_choices_and_history(saved):
    store, sid, mapping = saved
    original = copy.deepcopy(store.get_snapshot(sid))
    store.set_decision(mapping['a'], 'keep', note='人工')
    store.set_group_mode(sid, 'g1', 'assist')
    child = store.revise_groups(sid, 'split', 'split', ['g1'], ['a'])
    snapshot = store.get_snapshot(child)
    groups = snapshot['report']['groups']
    assert [g['version_ids'] for g in groups] == [['a'], ['b'], ['c', 'd']]
    assert all(store.get_mode(child, g['group_id'])['override'] == 'assist' for g in groups[:2])
    assert store.get_snapshot(sid) == original
    assert snapshot['report']['items'] == original['report']['items']
    assert snapshot['version_map'] == mapping
    merged = store.revise_groups(child, 'merge', 'merge', [g['group_id'] for g in groups[:2]], [])
    assert store.get_snapshot(merged)['report']['groups'][0]['ranking_modes']['safe']['recommended'] == ['b', 'a']
    assert store.get_decision(mapping['a'])['note'] == '人工'
    reopened = CullingStore(store.db_path)
    history = reopened.revision_history(merged)
    assert [r['id'] for r in history] == [sid, child, merged]
    assert history[-1]['parent_snapshot_id'] == child


def test_conflicting_modes_follow_default_and_retry_does_not_overwrite(saved):
    store, sid, _ = saved
    store.set_group_mode(sid, 'g1', 'assist')
    store.set_group_mode(sid, 'g2', 'relaxed')
    child = store.revise_groups(sid, 'merge', 'merge', ['g1', 'g2'], [])
    gid = store.get_snapshot(child)['report']['groups'][0]['group_id']
    assert store.get_mode(child, gid)['override'] is None
    store.set_group_mode(child, gid, 'relaxed')
    assert store.revise_groups(sid, 'merge', 'merge', ['g2', 'g1'], []) == child
    assert store.get_mode(child, gid)['override'] == 'relaxed'
    with pytest.raises(ValueError, match='different'):
        store.revise_groups(sid, 'merge', 'split', ['g1'], ['a'])


@pytest.mark.parametrize('action,groups,keys', [
    ('split', ['g1'], []), ('split', ['g1'], ['a', 'b']),
    ('split', ['g1'], ['c']), ('split', ['g1'], ['a', 'a']),
    ('merge', ['g1'], []), ('merge', ['g1', 'g1'], []),
    ('merge', ['g1', 'absent'], []), ('merge', ['g1', 'g2'], ['a']),
])
def test_invalid_operations_write_nothing(saved, action, groups, keys):
    store, sid, _ = saved
    with pytest.raises(ValueError):
        store.revise_groups(sid, 'invalid', action, groups, keys)
    assert len(store.revision_history(sid)) == 1


def test_mode_failure_rolls_back_snapshot_and_members(saved):
    store, sid, _ = saved
    store.set_group_mode(sid, 'g1', 'assist')
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("CREATE TRIGGER reject_modes BEFORE INSERT ON culling_group_modes "
                     "BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.revise_groups(sid, 'failure', 'split', ['g1'], ['a'])
    assert len(store.revision_history(sid)) == 1
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM culling_members').fetchone()[0] == 4


def test_old_snapshot_can_branch_without_overwriting(saved):
    store, sid, _ = saved
    first = store.revise_groups(sid, 'first', 'split', ['g1'], ['a'])
    second = store.revise_groups(sid, 'second', 'split', ['g2'], ['c'])
    assert first != second
    assert all(r['parent_snapshot_id'] == sid for r in store.revision_history(sid)[1:])
