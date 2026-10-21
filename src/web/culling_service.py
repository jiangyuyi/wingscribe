"""Web-owned worker and constrained reads for the local culling workflow."""
import hashlib
import io
import json
from pathlib import Path, PureWindowsPath
import sqlite3
import threading
from uuid import uuid4

from src.storage.catalogue import AssetCatalogue
from src.storage.culling import CullingStore


class CullingWeb:
    def __init__(self, runtime, detector_factory=None):
        self.runtime = runtime
        self.catalogue = AssetCatalogue(runtime.db_path)
        self.store = CullingStore(runtime.db_path)
        self.detector_factory = detector_factory or self._detector
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.current = {'running':False, 'error':None, 'request_key':None}

    def sources(self):
        return [(p if p.is_absolute() else self.runtime.BASE_DIR/p).resolve()
                for p in self.runtime.source_dirs]

    def directory(self, source: int, relative: str):
        roots = self.sources()
        if not 0 <= source < len(roots):
            raise ValueError('无效的照片来源')
        text = relative.replace('\\','/')
        if PureWindowsPath(text).drive or text.startswith('/') or '..' in text.split('/'):
            raise ValueError('只能选择来源内的相对目录')
        root = roots[source]
        target = (root/text).resolve()
        if not target.is_relative_to(root) or not target.is_dir():
            raise ValueError('目录不可用或超出照片来源')
        return target

    def initialize(self):
        backups = self.runtime.db_path.parent/'backups'
        self.catalogue.initialize(backup_dir=backups)
        self.store.initialize(backup_dir=backups)

    def _detector(self):
        processing = self.runtime.config['processing']
        path = Path(processing['yolo_model'])
        if not path.is_absolute():
            path = self.runtime.BASE_DIR/path
        if not path.is_file():
            raise ValueError('本地检测模型不存在，请检查设置中的模型路径')
        import torch
        device = processing.get('device','auto')
        if device == 'auto':
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        with path.open('rb') as stream:
            sha = hashlib.file_digest(stream,'sha256').hexdigest()
        model = None
        def detect(frame):
            nonlocal model
            import numpy as np
            from ultralytics import YOLO
            if model is None:
                model = YOLO(str(path))
            predictions = model.predict(source=np.ascontiguousarray(frame.pixels[:,:,::-1]),
                conf=0.5, classes=[14], imgsz=640, device=device, verbose=False)
            return [box.xyxy[0].tolist() for r in predictions for box in r.boxes]
        return detect, dict(sha256=sha,imgsz=640,confidence=0.5,classes=[14],device=device)

    def start(self, source, relative, gap, span):
        root = self.directory(source,relative)
        with self.lock:
            if self.current['running']:
                raise RuntimeError('选片任务正在运行')
            key = uuid4().hex
            self.stop_event.clear()
            self.current = dict(running=True,error=None,request_key=key)
            self.thread = threading.Thread(target=self._work,args=(root,key,gap,span),daemon=False)
            self.thread.start()
        return key

    def _work(self, root, key, gap, span):
        try:
            self.initialize()
            detect, identity = self.detector_factory()
            from src.application.culling import CullingService
            result = CullingService(self.catalogue,self.store,detect,detector_identity=identity).run(
                root,request_key=key,gap=gap,span=span,cancelled=self.stop_event.is_set)
            with self.lock:
                self.current['result'] = result
        except Exception as exc:
            with self.lock:
                self.current['error'] = str(exc) or type(exc).__name__
        finally:
            with self.lock:
                self.current['running'] = False

    def stop(self):
        self.stop_event.set()

    def close(self):
        self.stop()
        if self.thread:
            self.thread.join()

    def _read(self, sql, parameters=()):
        if not self.runtime.db_path.exists():
            return []
        try:
            return self.catalogue._read(sql,parameters)
        except sqlite3.OperationalError as exc:
            if 'no such table' in str(exc):
                return []
            raise

    def status(self):
        with self.lock:
            current = dict(self.current)
        jobs = []
        for row in self._read('SELECT * FROM processing_jobs ORDER BY created_at DESC,id DESC'):
            if json.loads(row['parameters_json']).get('kind') != 'culling':
                continue
            states = self._read('SELECT status,count(*) AS count FROM job_items WHERE job_id=? GROUP BY status',(row['id'],))
            snapshots = self._read('SELECT id FROM culling_snapshots WHERE run_key=?',('culling:'+row['id'],))
            jobs.append(dict(id=row['id'],status=row['status'],error=row['error'],created_at=row['created_at'],
                             counts={s['status']:s['count'] for s in states},
                             snapshot_id=snapshots[0]['id'] if snapshots else None))
            if len(jobs)==30:
                break
        return dict(current=current,jobs=jobs)

    def snapshot(self, sid):
        if not self._read('SELECT id FROM culling_snapshots WHERE id=?',(sid,)):
            raise LookupError('分析结果不存在')
        result = self.store.get_snapshot(sid)
        result['decisions'] = {v:self.store.get_decision(v) for v in result['version_map'].values()}
        result['modes'] = {g['group_id']:self.store.get_mode(sid,g['group_id']) for g in result['report']['groups']}
        return result

    def media(self, sid, version_id, crop):
        snapshot = self.snapshot(sid)
        if version_id not in snapshot['version_map'].values():
            raise LookupError('照片不属于此次分析')
        rows = self._read('''SELECT a.relative_path,s.root_path,v.fingerprint FROM asset_versions v
            JOIN assets a ON a.id=v.asset_id JOIN asset_sources s ON s.id=a.source_id WHERE v.id=?''',(version_id,))
        row = rows[0]
        root = Path(row['root_path']).resolve()
        path = (root/row['relative_path']).resolve()
        if not path.is_relative_to(root) or not any(path.is_relative_to(r) for r in self.sources()):
            raise ValueError('照片已不在启用的来源范围内')
        from src.core.culling_input import read_jpeg
        from PIL import Image
        frame = read_jpeg(path)
        if 'sha256:'+frame.sha256 != row['fingerprint']:
            raise RuntimeError('照片内容已变化，请重新分析')
        key = next(k for k,v in snapshot['version_map'].items() if v==version_id)
        bounds = snapshot['report']['items'][key]['evidence']['bounds']
        if crop and not bounds:
            raise LookupError('没有有效主体区域')
        pixels = frame.crop(bounds)[0] if crop else frame.pixels
        image = Image.fromarray(pixels)
        if not crop:
            image.thumbnail((900,600))
        output = io.BytesIO()
        image.save(output,format='PNG' if crop else 'JPEG')
        return output.getvalue(), 'image/png' if crop else 'image/jpeg'
