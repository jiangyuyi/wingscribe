import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from src.web.app import create_app


@pytest.fixture
def web(tmp_path):
    root=tmp_path/'source';root.mkdir()
    Image.new('RGB',(100,100),'gray').save(root/'bird.jpg')
    app=create_app(tmp_path,config_override={'paths':{'sources':[{'path':str(root)}],
        'output':{'root_dir':str(tmp_path/'output')},'db_path':str(tmp_path/'db.sqlite')}})
    app.state.culling.detector_factory=lambda:(lambda f:[(10,10,90,90)],{'test':'web-v1'})
    with TestClient(app) as client:
        yield app,client,root


def analyze(web):
    app,client,_=web
    assert client.post('/api/culling/start',json={'source':0}).status_code==202
    app.state.culling.thread.join(timeout=15)
    assert not app.state.culling.thread.is_alive()
    result=client.get('/api/culling/status').json()
    assert result['current']['error'] is None
    assert result['jobs'][0]['status']=='completed'
    return result['jobs'][0]['snapshot_id']


def test_web_task_review_modes_decisions_and_preview(web):
    app,client,root=web
    assert client.get('/culling').status_code==200
    assert '选片' in client.get('/culling').text
    sid=analyze(web)
    data=client.get('/api/culling/snapshots/'+sid).json()
    version=next(iter(data['version_map'].values()));gid=data['report']['groups'][0]['group_id']
    assert client.get(f'/api/culling/snapshots/{sid}/media/{version}').headers['content-type']=='image/jpeg'
    assert client.get(f'/api/culling/snapshots/{sid}/media/{version}?crop=true').headers['content-type']=='image/png'
    assert client.post('/api/culling/default-mode',json={'mode':'relaxed'}).status_code==200
    assert client.post(f'/api/culling/snapshots/{sid}/groups/{gid}/mode',json={'mode':'assist'}).json()['effective']=='assist'
    assert client.post(f'/api/culling/snapshots/{sid}/decisions/{version}',json={'decision':'keep','note':'确认'}).status_code==200
    data=client.get('/api/culling/snapshots/'+sid).json()
    assert data['decisions'][version]['note']=='确认'
    assert data['modes'][gid]['override']=='assist'
    assert client.post(f'/api/culling/snapshots/{sid}/groups/{gid}/mode',json={'mode':None}).json()['effective']=='relaxed'
    Image.new('RGB',(101,101),'white').save(root/'bird.jpg')
    assert client.get(f'/api/culling/snapshots/{sid}/media/{version}').status_code==409


@pytest.mark.parametrize('relative',['../','/absolute','C:/other','..\\other'])
def test_unconfigured_paths_rejected(web,relative):
    _,client,_=web
    assert client.post('/api/culling/start',json={'source':0,'relative':relative}).status_code==400


def test_cross_origin_and_invalid_mutations_rejected(web):
    _,client,_=web
    assert client.post('/api/culling/start',json={'source':0},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/culling/start',json={'source':0,'gap':0}).status_code==422
    assert client.post('/api/culling/default-mode',json={'mode':'invalid'}).status_code==422
    assert client.get('/api/culling/snapshots/missing').status_code==404
    sid=analyze(web)
    assert client.post(f'/api/culling/snapshots/{sid}/decisions/other',json={'decision':'keep'}).status_code==404


def test_stop_waits_for_active_image_and_rejects_parallel_start(web):
    app,client,_=web
    entered=threading.Event();release=threading.Event()
    def detect(frame):
        entered.set();assert release.wait(10);return []
    app.state.culling.detector_factory=lambda:(detect,{'test':'blocking'})
    assert client.post('/api/culling/start',json={'source':0}).status_code==202
    try:
        assert entered.wait(10)
        assert client.post('/api/culling/start',json={'source':0}).status_code==409
        assert client.post('/api/culling/stop',json={}).status_code==200
    finally:release.set()
    app.state.culling.thread.join(10)
    assert client.get('/api/culling/status').json()['jobs'][0]['status']=='stopped'


def test_pipeline_restore_does_not_mislabel_culling_job(web):
    app,_,_=web
    analyze(web)
    from src.web.task_manager import TaskManager
    manager=TaskManager(config_override=app.state.runtime.config)
    assert manager.job_id is None


def test_regroup_api_and_history(web):
    app, client, root = web
    Image.new('RGB', (100, 100), 'white').save(root/'second.jpg')
    sid = analyze(web)
    original = client.get('/api/culling/snapshots/'+sid).json()
    body = {'request_key': 'web-merge', 'action': 'merge',
            'group_ids': [g['group_id'] for g in original['report']['groups']]}
    url = f'/api/culling/snapshots/{sid}/regroup'
    assert client.post(url, json=body, headers={'Origin': 'https://evil.example'}).status_code == 403
    response = client.post(url, json=body)
    assert response.status_code == 200
    child = response.json()['snapshot_id']
    assert client.post(url, json=body).json()['snapshot_id'] == child
    derived = client.get('/api/culling/snapshots/'+child).json()
    assert len(derived['report']['groups']) == 1
    assert derived['version_map'] == original['version_map']
    history = client.get(f'/api/culling/snapshots/{child}/history').json()
    assert len(history) == 2 and history[1]['parent_snapshot_id'] == sid
    assert client.post(url, json={**body, 'group_ids': ['absent']}).status_code == 400
    assert client.get('/api/culling/snapshots/absent/history').status_code == 404


def test_subject_change_preserves_history_choices_modes_and_cache(web):
    app, client, root = web
    app.state.culling.detector_factory = lambda: (lambda f: [(0, 0, 90, 90), (40, 40, 90, 90)], {'test': 'multi'})
    sid = analyze(web)
    original = client.get('/api/culling/snapshots/'+sid).json()
    version = next(iter(original['version_map'].values()))
    key = next(iter(original['version_map']))
    gid = original['report']['groups'][0]['group_id']
    store = app.state.culling.store
    store.set_decision(version, 'keep', note='manual')
    store.set_group_mode(sid, gid, 'assist')
    cached = store.get_cached_result(version, original['report']['items'][key]['cache_key'])
    body = {'request_key': 'subject-test', 'version_id': version, 'detection_index': 1}
    url = f'/api/culling/snapshots/{sid}/subject'
    assert client.post(url, json=body, headers={'Origin': 'https://evil.example'}).status_code == 403
    response = client.post(url, json=body)
    assert response.status_code == 200
    child = response.json()['snapshot_id']
    new = client.get('/api/culling/snapshots/'+child).json()
    assert new['report']['items'][key]['evidence']['detection_index'] == 1
    assert new['report']['items'][key]['evidence']['bounds'] == [40, 40, 90, 90]
    assert new['decisions'][version]['note'] == 'manual'
    assert new['modes'][gid]['override'] == 'assist'
    assert store.get_snapshot(sid)['report'] == original['report']
    assert store.get_cached_result(version, original['report']['items'][key]['cache_key']) == cached
    restored = client.post(f'/api/culling/snapshots/{child}/subject', json={
        **body, 'request_key': 'restore', 'detection_index': None}).json()['snapshot_id']
    assert store.get_snapshot(restored)['report']['items'][key]['evidence'] == original['report']['items'][key]['evidence']
    store.set_group_mode(child, gid, 'relaxed')
    Image.new('RGB', (101, 101), 'white').save(root/'bird.jpg')
    assert client.post(url, json=body).json()['snapshot_id'] == child
    assert store.get_mode(child, gid)['override'] == 'relaxed'
    assert client.post(url, json={**body, 'detection_index': None}).status_code == 400
    assert client.post(url, json={**body, 'request_key': 'changed'}).status_code == 409
    assert len(store.revision_history(child)) == 3


@pytest.mark.parametrize('index', [-1, True, 0.5, 999])
def test_invalid_subject_index_does_not_publish(web, index):
    app, client, _ = web
    sid = analyze(web)
    version = next(iter(app.state.culling.store.get_snapshot(sid)['version_map'].values()))
    response = client.post(f'/api/culling/snapshots/{sid}/subject', json={
        'request_key': 'invalid', 'version_id': version, 'detection_index': index})
    assert response.status_code in (400, 422)
    assert len(app.state.culling.store.revision_history(sid)) == 1


def test_subject_changed_during_scoring_and_publication_failure(web, monkeypatch):
    import sqlite3
    from src.core import focus
    app, client, root = web
    sid = analyze(web)
    store = app.state.culling.store
    version = next(iter(store.get_snapshot(sid)['version_map'].values()))
    body = {'request_key': 'failure', 'version_id': version, 'detection_index': 0}
    url = f'/api/culling/snapshots/{sid}/subject'
    original_bytes = (root/'bird.jpg').read_bytes()
    original_score = focus.analyze_focus
    def changing(*args, **kwargs):
        result = original_score(*args, **kwargs)
        Image.new('RGB', (102, 102), 'white').save(root/'bird.jpg')
        return result
    monkeypatch.setattr(focus, 'analyze_focus', changing)
    assert client.post(url, json=body).status_code == 409
    assert len(store.revision_history(sid)) == 1

    (root/'bird.jpg').write_bytes(original_bytes)
    monkeypatch.setattr(focus, 'analyze_focus', original_score)
    gid = store.get_snapshot(sid)['report']['groups'][0]['group_id']
    store.set_group_mode(sid, gid, 'assist')
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("CREATE TRIGGER reject_subject_mode BEFORE INSERT ON culling_group_modes "
                     "BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        app.state.culling.change_subject(sid, 'failure', version, 0)
    assert len(store.revision_history(sid)) == 1


def test_subject_requires_current_algorithm_and_enabled_source(web):
    import copy
    app, client, _ = web
    sid = analyze(web)
    manager = app.state.culling
    original = manager.store.get_snapshot(sid)
    version = next(iter(original['version_map'].values()))
    key = next(iter(original['version_map']))
    report = copy.deepcopy(original['report'])
    report['items'][key]['evidence']['algorithm'] = 'old-unsupported'
    old = manager.store.save_snapshot('old-algorithm', report, original['version_map'])
    body = {'request_key': 'version', 'version_id': version, 'detection_index': 0}
    assert client.post(f'/api/culling/snapshots/{old}/subject', json=body).status_code == 400
    assert client.post(f'/api/culling/snapshots/{sid}/subject', json={**body, 'version_id': 'absent'}).status_code == 404
    manager.runtime.source_dirs = []
    assert client.post(f'/api/culling/snapshots/{sid}/subject', json=body).status_code == 400
