import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from src.application.culling import CullingService
from src.storage.catalogue import AssetCatalogue
from src.storage.culling import CullingStore
from src.storage.job_session import JobSession, JobBusyError


@pytest.fixture
def env(tmp_path):
    root=tmp_path/'photos';root.mkdir()
    for name in ['a.jpg','b.jpg']:
        Image.new('RGB',(80,80),'gray').save(root/name)
    catalogue=AssetCatalogue(tmp_path/'db.sqlite');catalogue.initialize()
    store=CullingStore(catalogue.db_path);store.initialize(backup_dir=tmp_path/'backups')
    return root,catalogue,store


def service(env, detector=lambda frame:[]):
    return CullingService(env[1],env[2],detector,detector_identity={'test':'fixed-v1'})


def run(env,detector=lambda frame:[],**kw):
    return service(env,detector).run(env[0],request_key=kw.pop('request_key','run'),gap=5,span=30,**kw)


def test_no_detection_persists_all_inputs_and_is_not_failure(env):
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in env[0].iterdir()}
    result=run(env)
    assert result['status']=='completed' and result['analyzed']==2
    report=env[2].get_snapshot(result['snapshot_id'])['report']
    assert all(i['evidence']['reasons']==['no_valid_subject'] for i in report['items'].values())
    assert all(i['status']=='completed' for i in env[1].list_job_items(result['job_id']))
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in env[0].iterdir()}
    assert report['input_set_complete']


def test_one_inference_failure_keeps_other_result_and_job_failed(env):
    def detector(frame):
        if frame.path.name=='a.jpg':raise RuntimeError('inference failed')
        return []
    result=run(env,detector)
    assert result['status']=='failed' and result['analyzed']==1
    report=env[2].get_snapshot(result['snapshot_id'])['report']
    assert not report['input_set_complete'] and len(report['errors'])==1
    assert sorted(i['status'] for i in env[1].list_job_items(result['job_id']))==['completed','failed']


def test_unreadable_jpeg_is_an_observation_not_no_bird(env):
    (env[0]/'bad.jpg').write_text('not a JPEG')
    result=run(env)
    assert result['status']=='failed' and len(result['failures'])==1
    with env[1]._connect() as conn:
        assert conn.execute("SELECT count(*) FROM asset_observations WHERE outcome='failed'").fetchone()[0]==1


def test_cancel_after_current_image_saves_partial_snapshot(env):
    stop=False
    def detector(frame):
        nonlocal stop
        stop=True
        return []
    result=run(env,detector,cancelled=lambda:stop)
    assert result['status']=='stopped' and result['analyzed']==1
    assert not env[2].get_snapshot(result['snapshot_id'])['report']['input_set_complete']


def test_repeat_key_refused_new_request_preserves_decision(env):
    first=run(env)
    version=next(iter(env[2].get_snapshot(first['snapshot_id'])['version_map'].values()))
    env[2].set_decision(version,'keep')
    with pytest.raises(ValueError):run(env)
    second=run(env,request_key='retry')
    assert second['status']=='completed'
    assert env[2].get_decision(version)['decision']=='keep'


def test_same_database_lock_and_orphan_recovery(env):
    with JobSession(env[1]) as session:
        session.start('orphan',{'kind':'culling'})
        with pytest.raises(JobBusyError):run(env)
    result=run(env)
    assert result['recovered_jobs']==1


def test_changed_source_during_inference_cannot_publish_stale_result(env):
    def detector(frame):
        if frame.path.name=='a.jpg':frame.path.write_bytes(b'changed test fixture')
        return []
    result=run(env,detector)
    report=env[2].get_snapshot(result['snapshot_id'])['report']
    assert result['status']=='failed'
    assert [i['filename'] for i in report['items'].values()]==['b.jpg']


def test_snapshot_failure_is_persistent_job_failure(env,monkeypatch):
    def fail(*args):raise RuntimeError('storage unavailable')
    monkeypatch.setattr(env[2],'save_snapshot',fail)
    with pytest.raises(RuntimeError):run(env)
    with env[1]._connect() as conn:
        row=conn.execute('SELECT status,error FROM processing_jobs').fetchone()
        assert row['status']=='failed' and row['error']=='storage unavailable'


def test_missing_root_records_failed_job(env):
    env[0].rename(env[0].with_name('moved'))
    with pytest.raises(OSError):run(env)
    with env[1]._connect() as conn:
        assert conn.execute('SELECT status FROM processing_jobs').fetchone()[0]=='failed'


def test_cancel_before_first_image_creates_no_snapshot(env):
    result=run(env,cancelled=lambda:True)
    assert result['status']=='stopped' and result['snapshot_id'] is None
    assert env[1].list_job_items(result['job_id'])==[]


def test_equal_times_in_different_directories_do_not_merge(env):
    root=env[0]
    for p in root.iterdir():
        p.unlink()  # Test-created files only.
    tags=Image.Exif();tags[271]='test';tags[272]='camera';tags[36867]='2026:10:21 12:00:00'
    for name in ['one','two']:
        (root/name).mkdir()
        Image.new('RGB',(80,80),'gray').save(root/name/'same.jpg',exif=tags)
    result=run(env)
    report=env[2].get_snapshot(result['snapshot_id'])['report']
    assert len(report['groups'])==2
    assert {i['relative_path'] for i in report['items'].values()}=={'one/same.jpg','two/same.jpg'}


def test_scan_failure_does_not_report_success(env,monkeypatch):
    import src.application.culling as module
    def failed(root):raise OSError('NAS enumeration failed')
    monkeypatch.setattr(module,'jpeg_paths',failed)
    with pytest.raises(OSError):run(env)
    with env[1]._connect() as conn:
        row=conn.execute('SELECT status,error FROM processing_jobs').fetchone()
        assert row['status']=='failed' and 'NAS' in row['error']


def test_directory_reparse_point_is_not_traversed(env,monkeypatch):
    import src.application.culling as module
    linked=env[0]/'junction';linked.mkdir()
    Image.new('RGB',(80,80)).save(linked/'outside.jpg')
    original=module._linked
    monkeypatch.setattr(module,'_linked',lambda path: path==linked or original(path))
    result=run(env)
    assert result['analyzed']==2


def test_cache_hit_skips_detector_but_regroups_and_preserves_decisions(env):
    calls=[]
    detector=lambda frame: calls.append(frame.path.name) or []
    first=run(env,detector)
    version=env[1].list_job_items(first['job_id'])[0]['version_id']
    env[2].set_decision(version,'keep')
    second=service(env,detector).run(env[0],request_key='second',gap=10,span=60)
    assert len(calls)==2 and second['cache_hits']==2 and second['computed']==0
    assert env[2].get_decision(version)['decision']=='keep'
    assert env[2].get_snapshot(second['snapshot_id'])['report']['experiment']['gap']==10


@pytest.mark.parametrize('change',['file','detector','algorithm','protocol','runtime','policy'])
def test_cache_invalidation(env,monkeypatch,change):
    import src.application.culling as module
    calls=[]
    detector=lambda frame: calls.append(frame.path.name) or []
    run(env,detector)
    next_service=service(env,detector)
    if change=='file':Image.new('RGB',(81,81),'white').save(env[0]/'a.jpg')
    elif change=='detector':next_service.detector_identity={'test':'new-v2'}
    elif change=='algorithm':monkeypatch.setattr(module,'ALGORITHM_VERSION','new-v2')
    elif change=='protocol':monkeypatch.setattr(module,'CACHE_PROTOCOL','new-v2')
    elif change=='runtime':next_service.runtime={'test':'new-v2'}
    else:
        original=module.FocusPolicy
        monkeypatch.setattr(module,'FocusPolicy',lambda **kw:original(**({'min_side':40}|kw)))
    result=next_service.run(env[0],request_key='new',gap=5,span=30)
    assert result['computed']==(1 if change=='file' else 2)
    assert len(calls)==(3 if change=='file' else 4)


def test_cache_survives_cancel_and_report_publication_failure(env,monkeypatch):
    calls=[]
    detector=lambda frame:calls.append(frame.path.name) or []
    stopped=run(env,detector,cancelled=lambda:len(calls)==1)
    assert stopped['status']=='stopped' and stopped['computed']==1
    original=env[2].save_snapshot
    monkeypatch.setattr(env[2],'save_snapshot',lambda *args:(_ for _ in ()).throw(RuntimeError('publish failed')))
    with pytest.raises(RuntimeError):run(env,detector,request_key='second')
    monkeypatch.setattr(env[2],'save_snapshot',original)
    third=run(env,detector,request_key='third')
    assert len(calls)==2 and third['cache_hits']==2


def test_corrupt_cache_is_recomputed_and_repaired(env):
    calls=[]
    detector=lambda frame:calls.append(frame.path.name) or []
    run(env,detector)
    with env[1]._connect() as conn:
        conn.execute("UPDATE culling_result_cache SET payload_json='broken'")
    second=run(env,detector,request_key='second')
    assert second['computed']==2 and second['cache_hits']==0
    third=run(env,detector,request_key='third')
    assert third['cache_hits']==2 and len(calls)==4


def test_failed_inference_not_cached(env):
    def bad(frame):raise RuntimeError('inference')
    first=run(env,bad)
    assert first['status']=='failed'
    second=run(env,request_key='second')
    assert second['computed']==2 and second['cache_hits']==0


def test_cache_commit_survives_failure_before_item_completion(env,monkeypatch):
    original=JobSession.finish_item
    calls=[]
    detector=lambda frame:calls.append(frame.path.name) or []
    def interrupted(*args,**kwargs):raise RuntimeError('after cache commit')
    monkeypatch.setattr(JobSession,'finish_item',interrupted)
    with pytest.raises(RuntimeError,match='cache commit'):run(env,detector)
    monkeypatch.setattr(JobSession,'finish_item',original)
    result=run(env,detector,request_key='recover')
    assert result['cache_hits']==1 and result['computed']==1 and len(calls)==2
