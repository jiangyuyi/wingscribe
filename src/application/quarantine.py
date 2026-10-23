"""Read-only preview of explicitly rejected JPEG originals.

Preview is not an execution authorization. A future executor must persist it and
revalidate decisions, paths and full fingerprints under the shared worker lock.
"""
import hashlib
import re
from pathlib import Path
from uuid import uuid4

from src.core.quarantine_paths import QUARANTINE_DIR, checked_path, is_quarantine
from src.storage.catalogue import _json


class QuarantinePreview:
    def __init__(self, catalogue, store, sources):
        self.catalogue = catalogue
        self.store = store
        self.sources = [Path(p).absolute() for p in sources]

    def build(self, snapshot_id: str, *, operation_id: str | None = None) -> dict:
        operation_id = operation_id or uuid4().hex
        if not re.fullmatch(r'[0-9a-f]{32}', operation_id):
            raise ValueError('无效的隔离操作标识')
        snapshot = self.store.get_snapshot(snapshot_id)
        if snapshot is None:
            raise LookupError('分析结果不存在')
        items = []
        # Read membership, current decisions and version identity consistently.
        with self.store._connection() as conn:
            rows = conn.execute('''SELECT m.version_id, d.updated_at, d.note,
                a.relative_path, s.root_path, v.fingerprint, v.size_bytes
                FROM culling_members m
                JOIN culling_decisions d ON d.version_id=m.version_id
                JOIN asset_versions v ON v.id=m.version_id
                JOIN assets a ON a.id=v.asset_id
                JOIN asset_sources s ON s.id=a.source_id
                WHERE m.snapshot_id=? AND d.decision='reject'
                ORDER BY s.root_path,a.relative_path,m.version_id''', (snapshot['id'],)).fetchall()
        for row in rows:
            item = dict(version_id=row['version_id'], decision_updated_at=row['updated_at'],
                        note=row['note'], fingerprint=row['fingerprint'], size_bytes=row['size_bytes'],
                        source_root=None, relative_path=None, original_path=None,
                        destination_path=None, eligible=False, error=None)
            try:
                registered_root = Path(row['root_path'])
                path = checked_path(registered_root, Path(row['relative_path']))
                item['original_path'] = str(path)
                if is_quarantine(path) or path.suffix.lower() not in {'.jpg', '.jpeg'}:
                    raise ValueError('仅支持隔离区之外的 JPEG 原片')
                matching = [root for root in self.sources if path.is_relative_to(root)]
                if not matching:
                    raise ValueError('照片已不在启用的来源范围内')
                root = max(matching, key=lambda p: len(p.parts))
                relative = path.relative_to(root)
                path = checked_path(root, relative)
                target = checked_path(root, Path(QUARANTINE_DIR)/operation_id/relative)
                item.update(source_root=str(root), relative_path=relative.as_posix(),
                            destination_path=str(target))
                if target.exists():
                    raise ValueError('隔离目标已存在，不允许覆盖')
                if not path.is_file():
                    raise ValueError('原片不存在或不可读取')
                before = path.stat()
                with path.open('rb') as stream:
                    fingerprint = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
                after = path.stat()
                if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                        after.st_size, after.st_mtime_ns, after.st_ino):
                    raise ValueError('读取期间原片变化，请重新预览')
                if fingerprint != row['fingerprint'] or after.st_size != row['size_bytes']:
                    raise ValueError('原片内容已变化，请重新分析')
                item['eligible'] = True
            except (OSError, ValueError) as exc:
                item['error'] = str(exc)
            items.append(item)
        # Multiple catalogue identities must never move one pathname twice.
        seen = set()
        for item in items:
            key = (item['original_path'] or '').casefold()
            if key and key in seen:
                item.update(eligible=False, error='清单中存在重复原片路径，请先核对登记来源')
            seen.add(key)
        report = dict(schema=1, operation_id=operation_id, snapshot_id=snapshot_id,
                      action='quarantine', items=items, count=len(items),
                      total_bytes=sum(i['size_bytes'] for i in items),
                      ready=bool(items) and all(i['eligible'] for i in items))
        report['preview_hash'] = hashlib.sha256(_json(report).encode()).hexdigest()
        return report
