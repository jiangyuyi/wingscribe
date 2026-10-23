import hashlib
import os

import pytest

from test_quarantine_preview import setup, preview
from src.application.quarantine_execution import QuarantineExecutor
from src.storage.job_session import JobSession, JobBusyError

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows no-replace rename contract')


def executor(setup):
    root, catalogue, store, _, _ = setup
    return QuarantineExecutor(catalogue, store, [root])


def execute(service, plan):
    return service.execute(plan['snapshot_id'], plan['operation_id'], plan['preview_hash'])


def state(result):
    return next(iter(result['states'].values()))['state']


def test_move_restore_retries_hashes_backup_and_labels(setup):
    root, catalogue, store, sid, versions = setup
    original = root/'album/reject.jpg'
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    plan = preview(setup)
    service = executor(setup)
    result = execute(service, plan)
    assert state(result) == 'quarantined' and not original.exists()
    assert state(execute(service, plan)) == 'quarantined'
    assert list((catalogue.db_path.parent/'backups').glob('before-quarantine-*.db'))
    restore_plan = service.restore_preview(plan['operation_id'])
    assert restore_plan['ready']
    restored = service.restore(plan['operation_id'], restore_plan['preview_hash'])
    assert state(restored) == 'restored'
    assert state(service.restore(plan['operation_id'], restore_plan['preview_hash'])) == 'restored'
    assert state(execute(service, plan)) == 'restored'  # never move twice
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    assert store.get_decision(versions['reject.jpg'])['decision'] == 'reject'
    with store._connection() as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()


def test_stale_plan_and_worker_lock_do_not_move(setup):
    root, catalogue, store, _, versions = setup
    plan = preview(setup)
    service = executor(setup)
    with JobSession(catalogue):
        with pytest.raises(JobBusyError):
            execute(service, plan)
    store.set_decision(versions['reject.jpg'], 'keep')
    with pytest.raises(ValueError, match='预览'):
        execute(service, plan)
    assert (root/'album/reject.jpg').is_file()


@pytest.mark.parametrize('restore', [False, True])
def test_crash_after_rename_before_database_commit_recovers(setup, monkeypatch, restore):
    import src.application.quarantine_execution as module
    plan = preview(setup)
    service = executor(setup)
    if restore:
        execute(service, plan)
        restore_plan = service.restore_preview(plan['operation_id'])
    real_rename = module.rename_no_replace
    def interrupted(source, target):
        real_rename(source, target)
        raise KeyboardInterrupt('simulated process death')
    monkeypatch.setattr(module, 'rename_no_replace', interrupted)
    def run():
        return service.restore(plan['operation_id'], restore_plan['preview_hash']) if restore else execute(service, plan)
    with pytest.raises(KeyboardInterrupt):
        run()
    assert state(service.journal.get(plan['operation_id'])) == ('restoring' if restore else 'moving')
    monkeypatch.setattr(module, 'rename_no_replace', real_rename)
    assert state(run()) == ('restored' if restore else 'quarantined')


def test_restore_collision_never_overwrites(setup):
    root = setup[0]
    plan = preview(setup)
    service = executor(setup)
    execute(service, plan)
    restore_plan = service.restore_preview(plan['operation_id'])
    original = root/'album/reject.jpg'
    original.write_bytes(b'new photo at old pathname')
    assert not service.restore_preview(plan['operation_id'])['ready']
    with pytest.raises(ValueError):
        service.restore(plan['operation_id'], restore_plan['preview_hash'])
    assert original.read_bytes() == b'new photo at old pathname'


def test_rename_failure_records_error_and_explicit_retry_succeeds(setup, monkeypatch):
    import src.application.quarantine_execution as module
    plan = preview(setup)
    service = executor(setup)
    real_rename = module.rename_no_replace
    def failed(source, target):
        raise PermissionError('test file locked')
    monkeypatch.setattr(module, 'rename_no_replace', failed)
    result = execute(service, plan)
    assert state(result) == 'moving'
    assert next(iter(result['states'].values()))['error'] == 'test file locked'
    monkeypatch.setattr(module, 'rename_no_replace', real_rename)
    assert state(execute(service, plan)) == 'quarantined'


def test_disabled_source_blocks_restore_and_reused_id_rejected(setup):
    service = executor(setup)
    plan = preview(setup)
    execute(service, plan)
    with pytest.raises(ValueError, match='其他预览'):
        service.execute(plan['snapshot_id'], plan['operation_id'], 'different')
    service.sources = []
    assert not service.restore_preview(plan['operation_id'])['ready']


def test_partial_failure_retains_successful_files_and_retry_only_remaining(setup, monkeypatch):
    import src.application.quarantine_execution as module
    root, _, store, _, versions = setup
    store.set_decision(versions['keep.jpg'], 'reject')
    plan = preview(setup)
    service = executor(setup)
    real_rename = module.rename_no_replace
    calls = []
    def partial(source, target):
        calls.append(source.name)
        if source.name == 'reject.jpg':
            raise PermissionError('locked')
        real_rename(source, target)
    monkeypatch.setattr(module, 'rename_no_replace', partial)
    result = execute(service, plan)
    assert sorted(r['state'] for r in result['states'].values()) == ['moving', 'quarantined']
    assert not (root/'album/keep.jpg').exists()
    assert (root/'album/reject.jpg').exists()
    calls.clear()
    def successful(source, target):
        calls.append(source.name)
        real_rename(source, target)
    monkeypatch.setattr(module, 'rename_no_replace', successful)
    result = execute(service, plan)
    assert calls == ['reject.jpg']
    assert all(r['state'] == 'quarantined' for r in result['states'].values())


def test_changed_decision_after_journal_is_saved_prevents_move(setup, monkeypatch):
    root, _, store, _, versions = setup
    service = executor(setup)
    plan = preview(setup)
    save = service.journal.save
    def changed(plan):
        save(plan)
        store.set_decision(versions['reject.jpg'], 'keep')
    monkeypatch.setattr(service.journal, 'save', changed)
    result = execute(service, plan)
    assert state(result) == 'moving'
    assert '人工标记' in next(iter(result['states'].values()))['error']
    assert (root/'album/reject.jpg').is_file()


@pytest.mark.parametrize('conflict', ['both', 'neither', 'changed'])
def test_ambiguous_crash_recovery_never_deletes_or_claims_success(setup, monkeypatch, conflict):
    import src.application.quarantine_execution as module
    from pathlib import Path
    root = setup[0]
    service = executor(setup)
    plan = preview(setup)
    real_rename = module.rename_no_replace
    def interrupted(source, target):
        real_rename(source, target)
        raise KeyboardInterrupt()
    monkeypatch.setattr(module, 'rename_no_replace', interrupted)
    with pytest.raises(KeyboardInterrupt):
        execute(service, plan)
    target = Path(plan['items'][0]['destination_path'])
    if conflict == 'both':
        (root/'album/reject.jpg').write_bytes(b'another file')
    elif conflict == 'neither':
        target.unlink()  # disposable fixture only
    else:
        target.write_bytes(b'modified')
    monkeypatch.setattr(module, 'rename_no_replace', real_rename)
    result = execute(service, plan)
    assert state(result) == 'moving'
    assert next(iter(result['states'].values()))['error']
    if conflict == 'both':
        assert target.is_file() and (root/'album/reject.jpg').read_bytes() == b'another file'


def test_windows_rename_never_replaces_destination(tmp_path):
    from src.application.quarantine_execution import rename_no_replace
    a, b = tmp_path/'a.jpg', tmp_path/'b.jpg'
    a.write_bytes(b'original')
    b.write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        rename_no_replace(a, b)
    assert a.read_bytes() == b'original' and b.read_bytes() == b'existing'


def test_history_never_hides_older_unrestored_operation(setup):
    import json
    service = executor(setup)
    plan = preview(setup)
    execute(service, plan)
    with service.store._connection(write=True) as conn:
        for index in range(51):
            oid = f'archived-{index}'
            conn.execute('INSERT INTO quarantine_operations VALUES (?,?,?,NULL)',
                         (oid,json.dumps({**plan,'operation_id':oid}),f'2099-{index:02}'))
    operations = service.journal.list_operations()
    assert len(operations) == 51
    assert any(o['plan']['operation_id'] == plan['operation_id'] for o in operations)
