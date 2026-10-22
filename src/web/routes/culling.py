from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field


def same_origin(request: Request):
    origin=request.headers.get('origin')
    if request.method != 'GET' and origin:
        if urlsplit(origin).netloc != request.url.netloc or urlsplit(origin).scheme != request.url.scheme:
            raise HTTPException(403,'不接受跨站写入请求')


router=APIRouter(dependencies=[Depends(same_origin)])
Mode=Literal['safe','assist','relaxed']


class Start(BaseModel):
    source:int=Field(ge=0)
    relative:str=Field(default='',max_length=2048)
    gap:float=Field(default=5,gt=0,le=3600,allow_inf_nan=False)
    span:float=Field(default=30,gt=0,le=86400,allow_inf_nan=False)


class Preference(BaseModel):
    mode:Mode


class Override(BaseModel):
    mode:Mode | None=None


class Decision(BaseModel):
    decision:Literal['keep','undecided','reject']
    note:str=Field(default='',max_length=4000)


class Regroup(BaseModel):
    request_key: str = Field(min_length=1, max_length=128)
    action: Literal['split', 'merge']
    group_ids: list[str] = Field(min_length=1, max_length=1000)
    item_keys: list[str] = Field(default_factory=list, max_length=10000)


class Subject(BaseModel):
    request_key: str = Field(min_length=1, max_length=128)
    version_id: str = Field(min_length=1, max_length=128)
    detection_index: int | None = Field(default=None, ge=0, strict=True)


def invoke(fn,*args,**kwargs):
    try:
        return fn(*args,**kwargs)
    except LookupError as exc:
        raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    except (RuntimeError,OSError) as exc:
        raise HTTPException(409,str(exc)) from exc


@router.get('/culling')
def page(request:Request):
    runtime=request.app.state.runtime
    return runtime.templates.TemplateResponse(request=request,name='culling.html',context={})


@router.get('/api/culling/status')
def status(request:Request):
    manager=request.app.state.culling
    result=invoke(manager.status)
    result['sources']=[dict(id=i,path=str(p)) for i,p in enumerate(manager.sources())]
    defaults=manager._read('SELECT mode FROM culling_preferences WHERE id=1')
    result['default_mode']=defaults[0]['mode'] if defaults else 'safe'
    return result


@router.post('/api/culling/start',status_code=202)
def start(body:Start,request:Request):
    if request.app.state.runtime.task_manager.is_running:
        raise HTTPException(409,'归档任务正在运行，请完成或停止后再选片')
    return {'request_key':invoke(request.app.state.culling.start,body.source,body.relative,body.gap,body.span)}


@router.post('/api/culling/stop')
def stop(request:Request):
    request.app.state.culling.stop()
    return {'requested':True}


@router.get('/api/culling/snapshots/{sid}')
def snapshot(sid:str,request:Request):
    return invoke(request.app.state.culling.snapshot,sid)


@router.get('/api/culling/snapshots/{sid}/media/{version_id}')
def media(sid:str,version_id:str,request:Request,crop:bool=False):
    data,mime=invoke(request.app.state.culling.media,sid,version_id,crop)
    return Response(data,media_type=mime,headers={'Cache-Control':'no-store'})


@router.post('/api/culling/default-mode')
def default_mode(body:Preference,request:Request):
    manager=request.app.state.culling
    invoke(manager.initialize)
    invoke(manager.store.set_default_mode,body.mode)
    return {'mode':body.mode}


@router.post('/api/culling/snapshots/{sid}/groups/{gid}/mode')
def group_mode(sid:str,gid:str,body:Override,request:Request):
    manager=request.app.state.culling
    invoke(manager.store.set_group_mode,sid,gid,body.mode)
    return invoke(manager.store.get_mode,sid,gid)


@router.post('/api/culling/snapshots/{sid}/decisions/{version_id}')
def decision(sid:str,version_id:str,body:Decision,request:Request):
    manager=request.app.state.culling
    snapshot=invoke(manager.snapshot,sid)
    if version_id not in snapshot['version_map'].values():
        raise HTTPException(404,'照片不属于此次分析')
    invoke(manager.store.set_decision,version_id,body.decision,note=body.note)
    return manager.store.get_decision(version_id)


@router.post('/api/culling/snapshots/{sid}/regroup')
def regroup(sid: str, body: Regroup, request: Request):
    store = request.app.state.culling.store
    # Validate existence before opening the write transaction (also handles a fresh database).
    invoke(request.app.state.culling.snapshot, sid)
    result = invoke(store.revise_groups, sid, body.request_key, body.action, body.group_ids, body.item_keys)
    return {'snapshot_id': result}


@router.get('/api/culling/snapshots/{sid}/history')
def history(sid: str, request: Request):
    invoke(request.app.state.culling.snapshot, sid)
    return invoke(request.app.state.culling.store.revision_history, sid)


@router.post('/api/culling/snapshots/{sid}/subject')
def subject(sid: str, body: Subject, request: Request):
    result = invoke(request.app.state.culling.change_subject, sid, body.request_key,
                    body.version_id, body.detection_index)
    return {'snapshot_id': result}


@router.get('/api/culling/snapshots/{sid}/subjects/{version_id}')
def subject_preview(sid: str, version_id: str, request: Request, index: int | None = Query(default=None, ge=0)):
    data = invoke(request.app.state.culling.subject_preview, sid, version_id, index)
    return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})
