"""Windows same-source moves with durable intent and explicit recovery.

No unlink/copy fallback: rename fails if a destination already exists. External
applications must not edit these files concurrently; this is not an OS sandbox.
"""
import hashlib
import os
from pathlib import Path

from src.application.quarantine import QuarantinePreview
from src.core.quarantine_paths import QUARANTINE_DIR, checked_path
from src.storage.catalogue import _json
from src.storage.job_session import JobSession
from src.storage.quarantine import QuarantineJournal


def fingerprint(path):
    with path.open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def rename_no_replace(source, destination):
    if os.name != 'nt':
        raise RuntimeError('首版隔离移动仅支持 Windows；未进行文件操作')
    # Windows os.rename fails if dst exists, unlike POSIX rename.
    os.rename(source, destination)


class QuarantineExecutor:
    def __init__(self, catalogue, store, sources):
        if catalogue.db_path != store.db_path:
            raise ValueError('Quarantine and workers must share one database')
        self.catalogue, self.store = catalogue, store
        self.sources = [Path(p).absolute() for p in sources]
        self.journal = QuarantineJournal(store)

    def _paths(self, plan, item):
        root = Path(item['source_root'])
        if root not in self.sources:
            raise ValueError('照片来源已禁用，请先恢复来源配置')
        relative = Path(item['relative_path'])
        source = checked_path(root, relative)
        target = checked_path(root, Path(QUARANTINE_DIR)/plan['operation_id']/relative)
        if str(source) != item['original_path'] or str(target) != item['destination_path']:
            raise ValueError('隔离记录路径不一致')
        return source, target

    def execute(self, snapshot_id, operation_id, preview_hash):
        with JobSession(self.catalogue):
            self.journal.initialize()
            existing = self.journal.get(operation_id)
            if existing:
                plan = existing['plan']
                if plan['snapshot_id'] != snapshot_id or plan['preview_hash'] != preview_hash:
                    raise ValueError('操作标识已用于其他预览')
            else:
                plan = QuarantinePreview(self.catalogue, self.store, self.sources).build(
                    snapshot_id, operation_id=operation_id)
                if not plan['ready'] or plan['preview_hash'] != preview_hash:
                    raise ValueError('预览已过期或包含冲突，请重新预览')
                self.journal.save(plan)
            for item in plan['items']:
                self._move_item(plan, item, restore=False)
            return self.journal.get(operation_id)

    def _move_item(self, plan, item, *, restore):
        oid, vid = plan['operation_id'], item['version_id']
        active, done = ('restoring','restored') if restore else ('moving','quarantined')
        initial = 'quarantined' if restore else 'pending'
        with self.store._connection(write=True) as conn:
            state = conn.execute('SELECT state FROM quarantine_items WHERE operation_id=? AND version_id=?',
                                 (oid,vid)).fetchone()[0]
            if state not in (initial, active):
                return
            self.journal.update(conn, oid, vid, active)
        try:
            # Serialize human decision writes through the move. Durable intent is
            # already committed, so process death leaves a recoverable record.
            with self.store._connection(write=True) as conn:
                source, target = self._paths(plan, item)
                if restore:
                    source, target = target, source
                source_exists, target_exists = source.exists(), target.exists()
                if source_exists and not target_exists:
                    if fingerprint(source) != item['fingerprint']:
                        raise ValueError('文件内容与预览不符')
                    if not restore:
                        decision = conn.execute('SELECT * FROM culling_decisions WHERE version_id=?', (vid,)).fetchone()
                        if (not decision or decision['decision'] != 'reject'
                                or decision['updated_at'] != item['decision_updated_at']
                                or decision['note'] != item['note']):
                            raise ValueError('人工标记已变化，请重新预览')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._paths(plan, item)
                    rename_no_replace(source, target)
                elif not source_exists and target_exists:
                    if state != active:
                        raise ValueError('目标已存在且没有移动中记录，拒绝推断完成')
                else:
                    raise ValueError('原位置与目标同时存在或同时缺失，需要核对文件')
                if fingerprint(target) != item['fingerprint']:
                    raise ValueError('目标内容校验失败，保留文件和操作记录')
                self.journal.update(conn, oid, vid, done)
        except (OSError, ValueError, RuntimeError) as exc:
            # Keep active state: a failed response can mean a NAS rename happened.
            # An explicit retry inspects both paths and never removes conflicts.
            with self.store._connection(write=True) as conn:
                self.journal.update(conn, oid, vid, active, str(exc))

    def restore_preview(self, operation_id):
        operation = self.journal.get(operation_id)
        if not operation:
            raise LookupError('隔离操作不存在')
        items = []
        for item in operation['plan']['items']:
            state = operation['states'][item['version_id']]['state']
            if state not in ('quarantined', 'restoring'):
                continue
            result = dict(version_id=item['version_id'], original_path=item['original_path'],
                          quarantine_path=item['destination_path'], state=state, error=None)
            try:
                original, quarantined = self._paths(operation['plan'], item)
                if state == 'restoring' and original.is_file() and not quarantined.exists():
                    if fingerprint(original) != item['fingerprint']:
                        raise ValueError('恢复目标内容不匹配')
                elif original.exists() or not quarantined.is_file():
                    raise ValueError('原路径已存在或隔离文件不可用')
                elif fingerprint(quarantined) != item['fingerprint']:
                    raise ValueError('隔离文件内容已变化')
            except (OSError, ValueError) as exc:
                result['error'] = str(exc)
            items.append(result)
        report = dict(operation_id=operation_id, items=items,
                      ready=bool(items) and all(i['error'] is None for i in items))
        report['preview_hash'] = hashlib.sha256(_json(report).encode()).hexdigest()
        return report

    def restore(self, operation_id, preview_hash):
        with JobSession(self.catalogue):
            operation = self.journal.get(operation_id)
            if not operation:
                raise LookupError('隔离操作不存在')
            if operation['restore_hash'] != preview_hash:
                preview = self.restore_preview(operation_id)
                if not preview['ready'] or preview['preview_hash'] != preview_hash:
                    raise ValueError('恢复预览已过期或存在冲突，请重新预览')
                with self.store._connection(write=True) as conn:
                    conn.execute('UPDATE quarantine_operations SET restore_hash=? WHERE id=?',
                                 (preview_hash,operation_id))
            for item in operation['plan']['items']:
                self._move_item(operation['plan'], item, restore=True)
            return self.journal.get(operation_id)
