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
