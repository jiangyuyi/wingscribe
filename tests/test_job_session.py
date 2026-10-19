import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.storage.catalogue import AssetCatalogue
from src.storage.job_session import JobBusyError, JobSession


@pytest.fixture
def catalogue(tmp_path):
    db = AssetCatalogue(tmp_path / 'jobs.db')
    db.initialize()
    with db.transaction() as tx:
        source = tx.register_source(str(tmp_path))
        for n in range(3):
            tx.register_asset(source, f'{n}.jpg', size_bytes=n, mtime_ns=1, fingerprint=f'sha256:{n}')
    return db


def versions(db):
    return [r['id'] for r in db._read('SELECT id FROM asset_versions ORDER BY size_bytes', ())]


def test_lifecycle_and_unique_claims(catalogue):
    with JobSession(catalogue) as session:
        assert session.recover() == 0
        job = session.start('one', {'range': 'all'})
        for version in versions(catalogue):
            item = session.enqueue(job, version)
            assert session.enqueue(job, version) == item
        with ThreadPoolExecutor(max_workers=3) as pool:
            claimed = list(pool.map(lambda _: session.claim(job), range(3)))
        assert len({i['id'] for i in claimed}) == 3
        assert all(i['attempts'] == 1 for i in claimed)
        assert session.claim(job) is None
        for item in claimed:
            session.finish_item(item['id'], 'completed')
        session.finish(job, 'completed')
    assert catalogue.get_job(job)['status'] == 'completed'
    with pytest.raises(RuntimeError, match='open worker'):
        session.claim(job)


def test_second_owner_rejected_and_released(catalogue):
    with JobSession(catalogue):
        with pytest.raises(JobBusyError):
            with JobSession(AssetCatalogue(catalogue.db_path)):
                pytest.fail('Second owner acquired lock')
    with JobSession(catalogue):
        pass


def test_live_other_process_cannot_recover_owner_job(catalogue):
    script = '''
import sys
from src.storage.catalogue import AssetCatalogue
from src.storage.job_session import JobBusyError, JobSession
try:
    with JobSession(AssetCatalogue(sys.argv[1])) as session:
        session.recover()
except JobBusyError:
    sys.exit(23)
'''
    with JobSession(catalogue) as session:
        job = session.start('live', {})
        result = subprocess.run([sys.executable, '-c', script, str(catalogue.db_path)], timeout=30)
        assert result.returncode == 23
        assert catalogue.get_job(job)['status'] == 'running'


def test_recovery_does_not_interrupt_current_owner(catalogue):
    with JobSession(catalogue) as session:
        job = session.start('one', {})
        with pytest.raises(RuntimeError, match='precede'):
            session.recover()
        assert catalogue.get_job(job)['status'] == 'running'


def test_stop_and_retry_preserve_history(catalogue):
    with JobSession(catalogue) as session:
        job = session.start('one', {})
        for version in versions(catalogue):
            session.enqueue(job, version)
        item = session.claim(job)
        with pytest.raises(ValueError, match='Drain'):
            session.finish(job, 'stopped')
        session.finish_item(item['id'], 'skipped', reason='already analyzed')
        session.finish(job, 'stopped')
        original = catalogue.list_job_items(job)
        retry = session.retry(job, 'retry-one')
        assert len(catalogue.list_job_items(retry)) == 2
        assert catalogue.list_job_items(job) == original
        assert catalogue.get_job(job)['status'] == 'stopped'
        with pytest.raises(RuntimeError):
            session.start('parallel', {})


@pytest.mark.parametrize('outcome,kwargs', [('skipped', {}), ('failed', {}), ('pending', {})])
def test_invalid_item_outcome_keeps_running(catalogue, outcome, kwargs):
    with JobSession(catalogue) as session:
        job = session.start('one', {})
        session.enqueue(job, versions(catalogue)[0])
        item = session.claim(job)
        with pytest.raises(ValueError):
            session.finish_item(item['id'], outcome, **kwargs)
        assert catalogue.list_job_items(job)[0]['status'] == 'running'


def test_failed_job_cannot_be_reported_completed(catalogue):
    with JobSession(catalogue) as session:
        job = session.start('one', {})
        session.enqueue(job, versions(catalogue)[0])
        item = session.claim(job)
        session.finish_item(item['id'], 'failed', error='disk full')
        with pytest.raises(ValueError):
            session.finish(job, 'completed')
        session.finish(job, 'failed', error='disk full')
        with pytest.raises(ValueError):
            session.finish_item(item['id'], 'completed')
        with pytest.raises(ValueError):
            session.start('one', {})


def test_process_death_releases_lock_and_retains_completed_items(catalogue):
    script = '''
import os,sys
from src.storage.catalogue import AssetCatalogue
from src.storage.job_session import JobSession
db=AssetCatalogue(sys.argv[1])
with JobSession(db) as session:
    job=session.start('crash', {})
    for row in db._read('SELECT id FROM asset_versions ORDER BY size_bytes', ()):
        session.enqueue(job,row['id'])
    item=session.claim(job)
    session.finish_item(item['id'],'completed')
    session.claim(job)
    os._exit(17)
'''
    result = subprocess.run([sys.executable, '-c', script, str(catalogue.db_path)], timeout=30)
    assert result.returncode == 17
    with JobSession(catalogue) as session:
        assert session.recover() == 1
        assert session.recover() == 0
        job = catalogue._read("SELECT id FROM processing_jobs WHERE request_key='crash'", ())[0]['id']
        assert sorted(i['status'] for i in catalogue.list_job_items(job)) == ['completed', 'interrupted', 'interrupted']
        retry = session.retry(job, 'retry')
        assert len(catalogue.list_job_items(retry)) == 2
        assert json.loads(catalogue.get_job(retry)['parameters_json'])['retry_of'] == job
