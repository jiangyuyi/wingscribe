"""Local culling snapshots and human choices; never performs photo operations."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from src.storage.catalogue import _json, _now
from src.core.culling import FOCUS_MODES as MODES

TABLES = {'culling_snapshots', 'culling_members', 'culling_decisions', 'culling_preferences', 'culling_group_modes'}
CACHE_DDL = '''CREATE TABLE culling_result_cache (
    version_id TEXT NOT NULL REFERENCES asset_versions(id), cache_key TEXT NOT NULL,
    payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(version_id,cache_key))'''
DDL = (
    '''CREATE TABLE culling_snapshots (
       id TEXT PRIMARY KEY, run_key TEXT NOT NULL UNIQUE, payload_hash TEXT NOT NULL,
       report_json TEXT NOT NULL, created_at TEXT NOT NULL)''',
    '''CREATE TABLE culling_members (
       snapshot_id TEXT NOT NULL REFERENCES culling_snapshots(id), group_id TEXT NOT NULL,
       item_key TEXT NOT NULL, version_id TEXT NOT NULL REFERENCES asset_versions(id),
       PRIMARY KEY(snapshot_id,item_key), UNIQUE(snapshot_id,version_id))''',
    '''CREATE TABLE culling_decisions (
       version_id TEXT PRIMARY KEY REFERENCES asset_versions(id),
       decision TEXT NOT NULL CHECK(decision IN ('keep','undecided','reject')),
       note TEXT NOT NULL, updated_at TEXT NOT NULL)''',
    '''CREATE TABLE culling_preferences (
       id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL CHECK(mode IN ('safe','assist','relaxed')))''',
    '''CREATE TABLE culling_group_modes (
       snapshot_id TEXT NOT NULL REFERENCES culling_snapshots(id), group_id TEXT NOT NULL,
       mode TEXT NOT NULL CHECK(mode IN ('safe','assist','relaxed')),
       PRIMARY KEY(snapshot_id,group_id))''',
    "INSERT INTO culling_preferences VALUES (1,'safe')",
)


class CullingStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).absolute()

    @contextmanager
    def _connection(self, *, write=False):
        conn = sqlite3.connect(self.db_path.as_uri() + '?mode=rw', uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                conn.execute('BEGIN IMMEDIATE')
            yield conn
            if write:
                conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self, *, backup_dir: str | Path) -> Path | None:
        """Explicit additive migration after AssetCatalogue initialization."""
        with self._connection(write=True) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'asset_versions' not in tables:
                raise ValueError('Initialize the asset catalogue first')
            versions = []
            if 'culling_schema_migrations' in tables:
                versions = [r[0] for r in conn.execute('SELECT version FROM culling_schema_migrations ORDER BY version')]
                if versions not in ([1], [1, 2]) or not TABLES.issubset(tables):
                    raise ValueError('Unsupported or incomplete culling schema')
                if versions == [1, 2]:
                    if 'culling_result_cache' not in tables:
                        raise ValueError('Incomplete cache schema')
                    return None
            if not versions and TABLES & tables:
                raise ValueError('Unversioned culling tables; restore a verified backup')
            directory = Path(backup_dir)
            directory.mkdir(parents=True, exist_ok=True)
            backup = directory / f'before-culling-{uuid4().hex}.db'
            source = sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True)
            destination = sqlite3.connect(backup)
            try:
                source.backup(destination)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Backup integrity check failed')
            finally:
                source.close()
                destination.close()
            if not versions:
                for statement in DDL:
                    conn.execute(statement)
                conn.execute('CREATE TABLE culling_schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
                conn.execute('INSERT INTO culling_schema_migrations VALUES (1,?)', (_now(),))
            conn.execute(CACHE_DDL)
            conn.execute('INSERT INTO culling_schema_migrations VALUES (2,?)', (_now(),))
            return backup

    def get_cached_result(self, version_id: str, cache_key: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute('SELECT payload_json,payload_hash FROM culling_result_cache '
                               'WHERE version_id=? AND cache_key=?', (version_id, cache_key)).fetchone()
            if not row or hashlib.sha256(row['payload_json'].encode()).hexdigest() != row['payload_hash']:
                return None
            try:
                return json.loads(row['payload_json'])
            except (ValueError, TypeError):
                return None

    def save_cached_result(self, version_id: str, cache_key: str, payload: dict) -> None:
        if not cache_key:
            raise ValueError('Cache key required')
        encoded = _json(payload)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self._connection(write=True) as conn:
            conn.execute('''INSERT INTO culling_result_cache VALUES (?,?,?,?,?)
                ON CONFLICT(version_id,cache_key) DO UPDATE SET payload_json=excluded.payload_json,
                payload_hash=excluded.payload_hash,created_at=excluded.created_at''',
                (version_id, cache_key, encoded, digest, _now()))

    def save_snapshot(self, run_key: str, report: dict, version_map: dict[str, str]) -> str:
        """Freeze a complete report, mapping its local item IDs to registered versions."""
        with self._connection(write=True) as conn:
            return self._save_snapshot(conn, run_key, report, version_map)

    def _save_snapshot(self, conn, run_key, report, version_map):
        if not run_key or not report.get('report_id'):
            raise ValueError('Run key and report identity are required')
        items = report['items']
        if not items or set(version_map) != set(items) or len(set(version_map.values())) != len(items):
            raise ValueError('Expected a unique version mapping for every input')
        members, groups = {}, set()
        for group in report['groups']:
            gid = group['group_id']
            if not gid or gid in groups or not group['version_ids']:
                raise ValueError('Invalid or duplicate group')
            groups.add(gid)
            for key in group['version_ids']:
                if key not in items or key in members:
                    raise ValueError('Each input must belong to exactly one group')
                members[key] = gid
        if set(members) != set(items):
            raise ValueError('Ungrouped input')
        payload = _json({'report': report, 'version_map': version_map})
        digest = hashlib.sha256(payload.encode()).hexdigest()
        for key, version in version_map.items():
            row = conn.execute('SELECT fingerprint FROM asset_versions WHERE id=?', (version,)).fetchone()
            sha = items[key].get('sha256', '')
            if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
                raise ValueError('Expected a complete SHA-256 for each input')
            if not row or row['fingerprint'] != 'sha256:' + sha:
                raise ValueError('Unknown version or input fingerprint mismatch')
        old = conn.execute('SELECT id,payload_hash FROM culling_snapshots WHERE run_key=?', (run_key,)).fetchone()
        if old:
            if old['payload_hash'] != digest:
                raise ValueError('Run key already has different results')
            return old['id']
        sid = uuid4().hex
        conn.execute('INSERT INTO culling_snapshots VALUES (?,?,?,?,?)', (sid, run_key, digest, _json(report), _now()))
        conn.executemany('INSERT INTO culling_members VALUES (?,?,?,?)',
                         [(sid, members[k], k, v) for k, v in version_map.items()])
        return sid

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute('SELECT * FROM culling_snapshots WHERE id=?', (snapshot_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result['report'] = json.loads(result.pop('report_json'))
            result['version_map'] = {r['item_key']: r['version_id'] for r in conn.execute(
                'SELECT item_key,version_id FROM culling_members WHERE snapshot_id=?', (snapshot_id,))}
            return result

    def revise_groups(self, parent_id: str, request_key: str, action: str,
                      group_ids: list[str], item_keys: list[str]) -> str:
        """Atomically publish regrouped evidence and inherit explicit modes."""
        from src.core.culling_revision import regroup

        if not request_key:
            raise ValueError('请求键不能为空')
        with self._connection(write=True) as conn:
            parent = conn.execute('SELECT report_json FROM culling_snapshots WHERE id=?',
                                  (parent_id,)).fetchone()
            if not parent:
                raise LookupError('分析结果不存在')
            report, parents = regroup(json.loads(parent[0]), parent_id, action, group_ids, item_keys)
            mapping = {r['item_key']: r['version_id'] for r in conn.execute(
                'SELECT item_key,version_id FROM culling_members WHERE snapshot_id=?', (parent_id,))}
            run_key = 'regroup:' + request_key
            existed = conn.execute('SELECT id FROM culling_snapshots WHERE run_key=?', (run_key,)).fetchone()
            sid = self._save_snapshot(conn, run_key, report, mapping)
            if existed:
                return sid  # Retry must not overwrite later human mode changes.
            overrides = dict(conn.execute('SELECT group_id,mode FROM culling_group_modes WHERE snapshot_id=?',
                                          (parent_id,)).fetchall())
            for gid, sources in parents.items():
                values = {overrides.get(source) for source in sources}
                if len(values) == 1 and None not in values:
                    conn.execute('INSERT INTO culling_group_modes VALUES (?,?,?)', (sid, gid, values.pop()))
            return sid

    def revision_history(self, snapshot_id: str) -> list[dict]:
        """Return the original analysis and all its immutable revision branches."""
        with self._connection() as conn:
            rows = conn.execute('SELECT id,created_at,report_json FROM culling_snapshots ORDER BY created_at,id').fetchall()
            reports = {r['id']: json.loads(r['report_json']) for r in rows}
            if snapshot_id not in reports:
                raise LookupError('分析结果不存在')
            root = reports[snapshot_id].get('revision', {}).get('root_snapshot_id', snapshot_id)
            result = []
            for row in rows:
                revision = reports[row['id']].get('revision', {})
                if row['id'] == root or revision.get('root_snapshot_id') == root:
                    result.append({'id': row['id'], 'created_at': row['created_at'],
                                   'parent_snapshot_id': revision.get('parent_snapshot_id'),
                                   'action': revision.get('action', 'analysis')})
            return result

    def subject_retry(self, request_key: str, operation: dict) -> str | None:
        with self._connection() as conn:
            return self._subject_retry(conn, request_key, operation)

    @staticmethod
    def _subject_retry(conn, request_key, operation):
        row = conn.execute('SELECT id,report_json FROM culling_snapshots WHERE run_key=?',
                           ('subject:' + request_key,)).fetchone()
        if row:
            if json.loads(row['report_json']).get('revision', {}).get('operation') != operation:
                raise ValueError('请求键已用于不同的主体操作')
            return row['id']
        return None

    def save_subject_revision(self, parent_id: str, request_key: str, operation: dict,
                              evidence: dict) -> str:
        """Internal publication boundary for server-validated focus evidence."""
        from src.core.focus_modes import report_modes

        with self._connection(write=True) as conn:
            existing = self._subject_retry(conn, request_key, operation)
            if existing:
                return existing
            row = conn.execute('SELECT report_json FROM culling_snapshots WHERE id=?', (parent_id,)).fetchone()
            if not row:
                raise LookupError('分析结果不存在')
            report = json.loads(row[0])
            mapping = {r['item_key']: r['version_id'] for r in conn.execute(
                'SELECT item_key,version_id FROM culling_members WHERE snapshot_id=?', (parent_id,))}
            version = operation['version_id']
            key = next((k for k, v in mapping.items() if v == version), None)
            if key is None or evidence['version_id'] != key or evidence['input_sha256'] != report['items'][key]['sha256']:
                raise ValueError('主体证据与照片版本不匹配')
            report['items'][key]['evidence'] = evidence
            report['items'][key]['subject_override'] = operation['detection_index']
            for group in report['groups']:
                if key in group['version_ids']:
                    group['ranking_modes'] = report_modes(group, report['items'])
                    group['ranking'] = group['ranking_modes']['safe']
            report['revision'] = {
                'parent_snapshot_id': parent_id,
                'root_snapshot_id': report.get('revision', {}).get('root_snapshot_id', parent_id),
                'action': 'subject', 'operation': operation,
            }
            report.pop('report_id', None)
            report['report_id'] = hashlib.sha256(_json(report).encode()).hexdigest()
            sid = self._save_snapshot(conn, 'subject:' + request_key, report, mapping)
            conn.execute('INSERT INTO culling_group_modes SELECT ?,group_id,mode '
                         'FROM culling_group_modes WHERE snapshot_id=?', (sid, parent_id))
            return sid

    def set_decision(self, version_id: str, decision: str, *, note: str = '') -> None:
        if decision not in {'keep', 'undecided', 'reject'} or not isinstance(note, str):
            raise ValueError('Invalid human decision')
        with self._connection(write=True) as conn:
            conn.execute('''INSERT INTO culling_decisions VALUES (?,?,?,?)
                ON CONFLICT(version_id) DO UPDATE SET decision=excluded.decision,
                note=excluded.note, updated_at=excluded.updated_at''', (version_id, decision, note, _now()))

    def get_decision(self, version_id: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute('SELECT * FROM culling_decisions WHERE version_id=?', (version_id,)).fetchone()
            return dict(row) if row else None

    def set_default_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError('Unknown mode')
        with self._connection(write=True) as conn:
            conn.execute('UPDATE culling_preferences SET mode=? WHERE id=1', (mode,))

    @staticmethod
    def _require_group(conn, snapshot_id, group_id):
        if not conn.execute('SELECT 1 FROM culling_members WHERE snapshot_id=? AND group_id=?',
                            (snapshot_id, group_id)).fetchone():
            raise ValueError('Unknown analysis group')

    def set_group_mode(self, snapshot_id: str, group_id: str, mode: str | None) -> None:
        if mode is not None and mode not in MODES:
            raise ValueError('Unknown mode')
        with self._connection(write=True) as conn:
            self._require_group(conn, snapshot_id, group_id)
            if mode is None:
                conn.execute('DELETE FROM culling_group_modes WHERE snapshot_id=? AND group_id=?', (snapshot_id, group_id))
            else:
                conn.execute('''INSERT INTO culling_group_modes VALUES (?,?,?)
                    ON CONFLICT(snapshot_id,group_id) DO UPDATE SET mode=excluded.mode''', (snapshot_id, group_id, mode))

    def get_mode(self, snapshot_id: str, group_id: str) -> dict:
        with self._connection() as conn:
            conn.execute('BEGIN')  # Default and override belong to one read snapshot.
            self._require_group(conn, snapshot_id, group_id)
            default = conn.execute('SELECT mode FROM culling_preferences WHERE id=1').fetchone()[0]
            override = conn.execute('SELECT mode FROM culling_group_modes WHERE snapshot_id=? AND group_id=?',
                                    (snapshot_id, group_id)).fetchone()
            return {'default': default, 'override': override[0] if override else None,
                    'effective': override[0] if override else default}
