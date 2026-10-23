"""Bounded synchronous JPEG culling task. No archive or source mutations."""
from dataclasses import asdict
import hashlib
import os
import stat
import sys
from importlib.metadata import version as package_version, PackageNotFoundError
from pathlib import Path
from typing import Callable

from src.core.culling import CaptureGroup, group_captures
from src.core.culling_input import read_jpeg
from src.core.focus import ALGORITHM_VERSION, FocusEvidence, FocusPolicy, analyze_focus, rank_group
from src.core.focus_modes import MODE_VERSION, report_modes
from src.storage.catalogue import _json
from src.storage.job_session import JobSession
from src.core.quarantine_paths import QUARANTINE_DIR, is_quarantine

CACHE_PROTOCOL = 'oriented-jpeg-focus-v1'


def runtime_identity():
    result = {'python': sys.version.split()[0]}
    for name in ('Pillow', 'numpy', 'opencv-python', 'ultralytics', 'torch'):
        try:
            result[name] = package_version(name)
        except PackageNotFoundError:
            result[name] = 'not-installed'
    return result


def restore_cached(payload, *, version_id, sha256):
    """Reject malformed cached evidence; callers recompute on a miss."""
    try:
        data = dict(payload['evidence'])
        data['policy'] = FocusPolicy(**data['policy'])
        data['reasons'] = tuple(data['reasons'])
        if data['bounds'] is not None:
            data['bounds'] = tuple(data['bounds'])
        result = FocusEvidence(**data)
        if (result.version_id != version_id or result.input_sha256 != sha256
                or result.algorithm != ALGORITHM_VERSION or result.policy != FocusPolicy()
                or result.status not in ('rankable', 'review')):
            return None
        boxes = payload['boxes']
        if not isinstance(boxes, list):
            return None
        rank_group(CaptureGroup('cache-validation', (version_id,), 'cache'), [result])
        return boxes, result
    except (ValueError, TypeError, KeyError):
        return None


def _linked(path: Path) -> bool:
    # Python 3.11 lacks Path.is_junction; Windows reparse points include junctions.
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0)
                                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))


def jpeg_paths(root: Path):
    if is_quarantine(root):
        raise ValueError('隔离目录不能作为照片来源')
    def failed(error):
        raise error
    for directory, children, names in os.walk(root, followlinks=False, onerror=failed):
        children[:] = sorted(name for name in children
                             if name.casefold() != QUARANTINE_DIR
                             and not _linked(Path(directory)/name)
                             and (Path(directory)/name).resolve().is_relative_to(root))
        for name in sorted(names):
            path = Path(directory)/name
            if path.suffix.lower() in {'.jpg', '.jpeg'}:
                if _linked(path) or not path.resolve().is_relative_to(root):
                    raise ValueError('Linked JPEG outside the source boundary')
                yield path


class CullingService:
    def __init__(self, catalogue, store, detector: Callable, *, detector_identity: dict):
        if catalogue.db_path != store.db_path:
            raise ValueError('Culling and jobs must share a local database')
        self.catalogue, self.store, self.detector = catalogue, store, detector
        # Detach caller-owned parameters before they become persisted identity.
        import json
        self.detector_identity = json.loads(_json(detector_identity))
        if not self.detector_identity:
            raise ValueError('Detector identity is required')
        self.runtime = runtime_identity()

    def run(self, root, *, request_key: str, gap: float, span: float,
            cancelled: Callable[[], bool] = lambda: False) -> dict:
        root = Path(root).resolve()
        # Validate before creating a persistent task.
        group_captures([], max_gap_seconds=gap, max_span_seconds=span)
        cache_parameters = dict(protocol=CACHE_PROTOCOL, detector=self.detector_identity,
                                algorithm=ALGORITHM_VERSION, policy=asdict(FocusPolicy()), runtime=self.runtime)
        params = dict(kind='culling', service_version='culling-task-v2', root=str(root), gap=gap, span=span,
                      detector=self.detector_identity, algorithm=ALGORITHM_VERSION,
                      policy=asdict(FocusPolicy()), mode_version=MODE_VERSION, cache_parameters=cache_parameters)
        with JobSession(self.catalogue) as session:
            recovered = session.recover()
            job = session.start(request_key, params)
            items, evidence, captures, errors = {}, {}, [], []
            stopped = False
            cache_hits = computed = 0
            try:
                with self.catalogue.transaction() as tx:
                    source = tx.register_source(str(root))
                if not root.is_dir():
                    raise OSError('Source directory is unavailable')
                for path in jpeg_paths(root):
                    if cancelled():
                        stopped = True
                        break
                    relative = path.relative_to(root).as_posix()
                    with self.catalogue.transaction() as tx:
                        asset = tx.discover_asset(source, relative)
                    item_id = None
                    version = None
                    try:
                        frame = read_jpeg(path)
                        with self.catalogue.transaction() as tx:
                            version = tx.register_asset(source, relative, size_bytes=frame.size_bytes,
                                mtime_ns=frame.mtime_ns, fingerprint='sha256:'+frame.sha256,
                                width=frame.size[0], height=frame.size[1],
                                captured_at=frame.metadata.captured_at.isoformat() if frame.metadata.captured_at else None)['version_id']
                        item_id = session.enqueue(job, version)
                        session.claim(job, item_id)
                        cache_key = hashlib.sha256(_json({'sha256':frame.sha256, **cache_parameters}).encode()).hexdigest()
                        cached = self.store.get_cached_result(version, cache_key)
                        restored = restore_cached(cached, version_id=version, sha256=frame.sha256) if cached else None
                        if restored is None:
                            boxes = [list(map(float, box)) for box in self.detector(frame)]
                            result = analyze_focus(frame, boxes, version_id=version)
                        else:
                            boxes, result = restored
                        with path.open('rb') as stream:
                            if hashlib.file_digest(stream, 'sha256').hexdigest() != frame.sha256:
                                raise RuntimeError('Source changed during analysis; rescan required')
                        capture = frame.capture(version_id=version, source_id=source,
                                                directory_key=path.parent.relative_to(root).as_posix())
                        item = dict(filename=path.name, relative_path=relative, sha256=frame.sha256,
                            captured_at=frame.metadata.captured_at.isoformat() if frame.metadata.captured_at else None,
                            metadata=asdict(frame.metadata), boxes=boxes, evidence=result.to_dict(),
                            cache_key=cache_key, cache_hit=restored is not None)
                        # Metadata contains datetime: use an explicit serialized value.
                        item['metadata']['captured_at'] = item['captured_at']
                    except Exception as exc:
                        error = str(exc) or type(exc).__name__
                        errors.append(dict(relative_path=relative, version_id=version, error=error))
                        if item_id:
                            session.finish_item(item_id, 'failed', error=error)
                        with self.catalogue.transaction() as tx:
                            tx.record_observation(asset, f'culling:{job}:{relative}', outcome='failed',
                                                  version_id=version, error=error)
                        frame = None
                        continue
                    # Cache commits before task completion/report publication, so a later
                    # crash can reuse finished inference without claiming the old job succeeded.
                    if restored is None:
                        self.store.save_cached_result(version, cache_key, {'boxes':boxes,'evidence':result.to_dict()})
                        computed += 1
                    else:
                        cache_hits += 1
                    session.finish_item(item_id, 'completed')
                    items[version] = item
                    captures.append(capture)
                    evidence[version] = result
                    del frame
                stopped = stopped or cancelled()
                groups = []
                for group in group_captures(captures, max_gap_seconds=gap, max_span_seconds=span):
                    data = {**asdict(group), 'ranking':asdict(rank_group(group, [evidence[k] for k in group.version_ids]))}
                    data['ranking_modes'] = report_modes(data, items)
                    groups.append(data)
                outcome = 'stopped' if stopped else 'failed' if errors else 'completed'
                sid = None
                if items:
                    report = dict(job_id=job, items=items, groups=groups, experiment=params,
                                  errors=errors, input_set_complete=not stopped and not errors,
                                  cache_hits=cache_hits, computed=computed)
                    report['report_id'] = hashlib.sha256(_json(report).encode()).hexdigest()
                    sid = self.store.save_snapshot('culling:'+job, report, {key:key for key in items})
                session.finish(job, outcome, error=f'{len(errors)} input(s) failed' if errors else None)
                return dict(job_id=job, snapshot_id=sid, status=outcome, analyzed=len(items),
                            failures=errors, recovered_jobs=recovered, cache_hits=cache_hits, computed=computed)
            except BaseException as exc:
                session.abort(job, str(exc) or type(exc).__name__)
                raise
