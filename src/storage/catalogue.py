"""Versioned asset catalogue, independent of the legacy photos/label tables.

Construction performs no IO. Call initialize explicitly, then group related writes
in transaction(). Each transaction owns a connection; SQLite arbitrates writers
across instances. No scanner, model or filesystem mutation is triggered here.
"""
import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import uuid4


SCHEMA_VERSION = 2
TABLES = {'asset_sources', 'assets', 'asset_versions', 'analysis_runs', 'detections',
          'processing_jobs', 'job_items'}
DDL = (
    """CREATE TABLE asset_sources (
        id TEXT PRIMARY KEY, root_path TEXT NOT NULL, root_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE assets (
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES asset_sources(id),
        relative_path TEXT NOT NULL, path_key TEXT NOT NULL,
        availability TEXT NOT NULL DEFAULT 'available'
            CHECK(availability IN ('available','unavailable','unknown')),
        created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
        UNIQUE(source_id, path_key))""",
    """CREATE TABLE asset_versions (
        id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id),
        revision INTEGER NOT NULL CHECK(revision > 0),
        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
        mtime_ns INTEGER NOT NULL CHECK(mtime_ns >= 0), fingerprint TEXT NOT NULL,
        width INTEGER CHECK(width > 0), height INTEGER CHECK(height > 0),
        captured_at TEXT, created_at TEXT NOT NULL, UNIQUE(asset_id, revision))""",
    """CREATE TABLE analysis_runs (
        id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES asset_versions(id),
        run_key TEXT NOT NULL, model TEXT NOT NULL, parameters_json TEXT NOT NULL,
        taxonomy_version TEXT NOT NULL, outcome TEXT NOT NULL
            CHECK(outcome IN ('succeeded','no_detection','quality_filtered','failed')),
        error TEXT, payload_hash TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(version_id, run_key))""",
    """CREATE TABLE detections (
        id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL REFERENCES analysis_runs(id),
        ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
        x1 REAL NOT NULL, y1 REAL NOT NULL, x2 REAL NOT NULL, y2 REAL NOT NULL,
        confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
        result_json TEXT NOT NULL, output_path TEXT,
        CHECK(x1 >= 0 AND y1 >= 0 AND x2 > x1 AND y2 > y1),
        UNIQUE(analysis_id, ordinal))""",
    """CREATE TABLE processing_jobs (
        id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
        parameters_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','running','completed','failed','stopped','interrupted')),
        error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE job_items (
        id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES processing_jobs(id),
        version_id TEXT NOT NULL REFERENCES asset_versions(id),
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','running','completed','failed','skipped','interrupted')),
        reason TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(job_id, version_id))""",
    "CREATE INDEX job_items_status ON job_items(job_id, status)",
    "CREATE INDEX analysis_runs_version ON analysis_runs(version_id, created_at)",
)

OBSERVATION_DDL = (
    """CREATE TABLE asset_observations (
        id TEXT PRIMARY KEY, observation_key TEXT NOT NULL UNIQUE,
        asset_id TEXT NOT NULL REFERENCES assets(id),
        version_id TEXT REFERENCES asset_versions(id),
        analysis_id TEXT REFERENCES analysis_runs(id),
        outcome TEXT NOT NULL CHECK(outcome IN
            ('succeeded','no_detection','quality_filtered','failed','skipped')),
        reason TEXT, error TEXT, payload_hash TEXT NOT NULL, created_at TEXT NOT NULL)""",
    'CREATE INDEX asset_observations_asset ON asset_observations(asset_id, created_at)',
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _relative(path: str) -> str:
    text = str(path).replace('\\', '/')
    if (not text or PureWindowsPath(text).drive or text.startswith('/')
            or any(part in ('', '.', '..') or ':' in part or '\x00' in part
                   or part.endswith((' ', '.')) for part in text.split('/'))):
        raise ValueError('Expected an unambiguous relative photo path')
    return PurePosixPath(text).as_posix()


def _root(path: str) -> str:
    text = str(path)
    if '\x00' in text:
        raise ValueError('Invalid source root')
    if PureWindowsPath(text).is_absolute():
        parsed = PureWindowsPath(text)
    elif PurePosixPath(text).is_absolute():
        parsed = PurePosixPath(text)
    else:
        raise ValueError('Source root must be absolute')
    if '..' in parsed.parts:
        raise ValueError('Source root cannot contain parent traversal')
    return parsed.as_posix()


class AssetCatalogue:
    def __init__(self, db_path: str | Path):
        if str(db_path) == ':memory:':
            raise ValueError('A persistent database path is required')
        self.db_path = Path(db_path).absolute()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path.as_uri() + '?mode=rw', uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def initialize(self, *, backup_dir: str | Path | None = None) -> Path | None:
        """Install only our additive schema. Existing populated DBs require backup.

        A reserved write transaction protects the migration and backup snapshot.
        No application-wide user_version or legacy table is changed.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(self.db_path).close()
        conn = self._connect()
        backup_path = None
        try:
            conn.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            versions = []
            if 'asset_schema_migrations' in tables:
                versions = [row[0] for row in conn.execute('SELECT version FROM asset_schema_migrations ORDER BY version')]
                if versions not in ([1], [1, SCHEMA_VERSION]):
                    raise ValueError('Unsupported asset catalogue schema version')
                required = TABLES | ({'asset_observations'} if len(versions) == 2 else set())
                if not required.issubset(tables):
                    raise ValueError('Incomplete asset catalogue schema; restore a verified backup')
                if versions == [1, SCHEMA_VERSION]:
                    conn.rollback()
                    return None
            if tables:
                if backup_dir is None:
                    raise ValueError('A backup directory is required before migrating an existing database')
                directory = Path(backup_dir)
                directory.mkdir(parents=True, exist_ok=True)
                backup_path = directory / f'before-assets-{uuid4().hex}.db'
                source = sqlite3.connect(self.db_path.as_uri() + '?mode=ro', uri=True)
                destination = sqlite3.connect(backup_path)
                try:
                    source.backup(destination)
                    if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('Backup integrity check failed')
                finally:
                    destination.close()
                    source.close()
            if not versions:
                conn.execute('CREATE TABLE asset_schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
                for statement in DDL:
                    conn.execute(statement)
                conn.execute('INSERT INTO asset_schema_migrations VALUES (?, ?)', (1, _now()))
            for statement in OBSERVATION_DDL:
                conn.execute(statement)
            conn.execute('INSERT INTO asset_schema_migrations VALUES (?, ?)', (SCHEMA_VERSION, _now()))
            conn.commit()
            return backup_path
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """Commit all related records together, or roll back on any exception."""
        conn = self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield CatalogueTransaction(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_assets(self, source_id: str) -> list[dict]:
        conn = self._connect()
        try:
            return [dict(row) for row in conn.execute(
                'SELECT * FROM assets WHERE source_id=? ORDER BY path_key', (source_id,))]
        finally:
            conn.close()

    def list_job_items(self, job_id: str) -> list[dict]:
        conn = self._connect()
        try:
            return [dict(row) for row in conn.execute(
                'SELECT * FROM job_items WHERE job_id=? ORDER BY created_at, id', (job_id,))]
        finally:
            conn.close()

    def _read(self, sql: str, parameters: tuple) -> list[dict]:
        conn = self._connect()
        try:
            return [dict(row) for row in conn.execute(sql, parameters)]
        finally:
            conn.close()

    def get_source(self, source_id: str) -> dict | None:
        rows = self._read('SELECT * FROM asset_sources WHERE id=?', (source_id,))
        return rows[0] if rows else None

    def get_job(self, job_id: str) -> dict | None:
        rows = self._read('SELECT * FROM processing_jobs WHERE id=?', (job_id,))
        return rows[0] if rows else None

    def list_versions(self, asset_id: str) -> list[dict]:
        return self._read('SELECT * FROM asset_versions WHERE asset_id=? ORDER BY revision', (asset_id,))

    def list_analyses(self, version_id: str) -> list[dict]:
        return self._read('SELECT * FROM analysis_runs WHERE version_id=? ORDER BY created_at, id', (version_id,))

    def list_detections(self, analysis_id: str) -> list[dict]:
        return self._read('SELECT * FROM detections WHERE analysis_id=? ORDER BY ordinal', (analysis_id,))

    def list_observations(self, asset_id: str) -> list[dict]:
        return self._read('SELECT * FROM asset_observations WHERE asset_id=? ORDER BY created_at, id', (asset_id,))


class CatalogueTransaction:
    """Use only within AssetCatalogue.transaction(); never share across threads."""
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def register_source(self, root_path: str) -> str:
        root = _root(root_path)
        key = root.casefold()
        row = self.conn.execute('SELECT id FROM asset_sources WHERE root_key=?', (key,)).fetchone()
        if row:
            return row['id']
        source_id, now = uuid4().hex, _now()
        self.conn.execute('INSERT INTO asset_sources VALUES (?, ?, ?, ?, ?)', (source_id, root, key, now, now))
        return source_id

    def rebind_source(self, source_id: str, root_path: str) -> None:
        """Explicit root change preserves logical assets; does not access the NAS."""
        root = _root(root_path)
        changed = self.conn.execute(
            'UPDATE asset_sources SET root_path=?, root_key=?, updated_at=? WHERE id=?',
            (root, root.casefold(), _now(), source_id))
        if changed.rowcount != 1:
            raise ValueError('Unknown source')

    def discover_asset(self, source_id: str, relative_path: str) -> str:
        """Record a directory entry without pretending its bytes are readable.

        Discovery alone never resets a known availability or creates a version.
        """
        path, now = _relative(relative_path), _now()
        row = self.conn.execute('SELECT id FROM assets WHERE source_id=? AND path_key=?',
                                (source_id, path.casefold())).fetchone()
        if row:
            self.conn.execute('UPDATE assets SET relative_path=?, last_seen_at=? WHERE id=?',
                              (path, now, row['id']))
            return row['id']
        asset_id = uuid4().hex
        self.conn.execute('INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)',
                          (asset_id, source_id, path, path.casefold(), 'unknown', now, now))
        return asset_id

    def record_observation(self, asset_id: str, observation_key: str, *, outcome: str,
                           version_id: str | None = None, analysis_id: str | None = None,
                           reason: str | None = None, error: str | None = None) -> str:
        """Persist a scan attempt even when stat, hashing or image decoding failed."""
        if not observation_key or outcome not in {'succeeded', 'no_detection', 'quality_filtered', 'failed', 'skipped'}:
            raise ValueError('Observation key and valid outcome are required')
        if outcome == 'failed' and not error:
            raise ValueError('Failed observation requires an error')
        if outcome == 'skipped' and not reason:
            raise ValueError('Skipped observation requires a reason')
        if outcome in {'succeeded', 'no_detection', 'quality_filtered'} and not version_id:
            raise ValueError('Analyzed outcomes require a file version')
        if version_id:
            row = self.conn.execute('SELECT asset_id FROM asset_versions WHERE id=?', (version_id,)).fetchone()
            if not row or row['asset_id'] != asset_id:
                raise ValueError('Version does not belong to the observed asset')
        if analysis_id:
            row = self.conn.execute('SELECT version_id FROM analysis_runs WHERE id=?', (analysis_id,)).fetchone()
            if not row or row['version_id'] != version_id:
                raise ValueError('Analysis does not belong to the observed version')
        digest = hashlib.sha256(_json([asset_id, version_id, analysis_id, outcome, reason, error]).encode('utf-8')).hexdigest()
        existing = self.conn.execute('SELECT id, payload_hash FROM asset_observations WHERE observation_key=?',
                                     (observation_key,)).fetchone()
        if existing:
            if existing['payload_hash'] != digest:
                raise ValueError('Observation key already belongs to a different result')
            return existing['id']
        observation_id = uuid4().hex
        self.conn.execute('INSERT INTO asset_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                          (observation_id, observation_key, asset_id, version_id, analysis_id,
                           outcome, reason, error, digest, _now()))
        return observation_id

    def register_asset(self, source_id: str, relative_path: str, *, size_bytes: int,
                       mtime_ns: int, fingerprint: str, width: int | None = None,
                       height: int | None = None, captured_at: str | None = None) -> dict:
        """Keep identity at a logical location; append a version when stat/hash changes.

        fingerprint must include its algorithm (e.g. sha256:...). It is version
        evidence, not global deduplication: separate locations stay separate assets.
        """
        path = _relative(relative_path)
        if not fingerprint or ':' not in fingerprint or not all(fingerprint.split(':', 1)):
            raise ValueError('Fingerprint must include algorithm and value')
        for value in (size_bytes, mtime_ns):
            if type(value) is not int or value < 0:
                raise ValueError('File size and mtime_ns must be nonnegative integers')
        for value in (width, height):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError('Dimensions must be positive integers')
        now = _now()
        asset = self.conn.execute('SELECT id FROM assets WHERE source_id=? AND path_key=?',
                                  (source_id, path.casefold())).fetchone()
        asset_id = asset['id'] if asset else uuid4().hex
        if asset is None:
            self.conn.execute('INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)',
                              (asset_id, source_id, path, path.casefold(), 'available', now, now))
        else:
            self.conn.execute("UPDATE assets SET relative_path=?, availability='available', last_seen_at=? WHERE id=?",
                              (path, now, asset_id))
        previous = self.conn.execute('SELECT * FROM asset_versions WHERE asset_id=? ORDER BY revision DESC LIMIT 1',
                                     (asset_id,)).fetchone()
        identity = (size_bytes, mtime_ns, fingerprint)
        if previous and tuple(previous[key] for key in ('size_bytes', 'mtime_ns', 'fingerprint')) == identity:
            return {'asset_id': asset_id, 'version_id': previous['id'], 'revision': previous['revision'], 'created': False}
        revision = previous['revision'] + 1 if previous else 1
        version_id = uuid4().hex
        self.conn.execute('INSERT INTO asset_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                          (version_id, asset_id, revision, *identity, width, height, captured_at, now))
        return {'asset_id': asset_id, 'version_id': version_id, 'revision': revision, 'created': True}

    def record_analysis(self, version_id: str, run_key: str, *, model: str,
                        parameters: dict, taxonomy_version: str, outcome: str,
                        detections: list[dict] | None = None, error: str | None = None) -> str:
        """Atomically store an immutable result and its per-bird detections."""
        if not run_key or not model or not taxonomy_version:
            raise ValueError('Analysis provenance is required')
        if outcome not in {'succeeded', 'no_detection', 'quality_filtered', 'failed'}:
            raise ValueError('Unknown analysis outcome')
        if outcome == 'failed' and not error:
            raise ValueError('Failed analysis requires an error')
        detections = detections or []
        if outcome == 'no_detection' and detections:
            raise ValueError('No-detection result cannot contain detections')
        # Validate the complete payload before writing any row.
        for detection in detections:
            x1, y1, x2, y2 = detection['bbox']
            confidence = detection['confidence']
            if not all(math.isfinite(v) for v in (x1, y1, x2, y2, confidence)):
                raise ValueError('Detection values must be finite')
            if not (0 <= x1 < x2 and 0 <= y1 < y2 and 0 <= confidence <= 1):
                raise ValueError('Invalid detection coordinates or confidence')
        payload = _json([model, parameters, taxonomy_version, outcome, detections, error])
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        existing = self.conn.execute('SELECT id, payload_hash FROM analysis_runs WHERE version_id=? AND run_key=?',
                                     (version_id, run_key)).fetchone()
        if existing:
            if existing['payload_hash'] != digest:
                raise ValueError('Run key already belongs to a different result')
            return existing['id']
        analysis_id = uuid4().hex
        self.conn.execute('INSERT INTO analysis_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                          (analysis_id, version_id, run_key, model, _json(parameters), taxonomy_version,
                           outcome, error, digest, _now()))
        for ordinal, detection in enumerate(detections):
            self.conn.execute('INSERT INTO detections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                              (uuid4().hex, analysis_id, ordinal, *detection['bbox'], detection['confidence'],
                               _json(detection.get('result', {})), detection.get('output_path')))
        return analysis_id

    def create_job(self, request_key: str, parameters: dict) -> str:
        if not request_key:
            raise ValueError('Request key is required')
        encoded = _json(parameters)
        existing = self.conn.execute('SELECT id, parameters_json FROM processing_jobs WHERE request_key=?',
                                     (request_key,)).fetchone()
        if existing:
            if existing['parameters_json'] != encoded:
                raise ValueError('Request key already belongs to different parameters')
            return existing['id']
        job_id, now = uuid4().hex, _now()
        self.conn.execute('INSERT INTO processing_jobs (id, request_key, parameters_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
                          (job_id, request_key, encoded, now, now))
        return job_id

    def enqueue(self, job_id: str, version_id: str) -> str:
        existing = self.conn.execute('SELECT id FROM job_items WHERE job_id=? AND version_id=?',
                                     (job_id, version_id)).fetchone()
        if existing:
            return existing['id']
        item_id, now = uuid4().hex, _now()
        self.conn.execute('INSERT INTO job_items (id, job_id, version_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
                          (item_id, job_id, version_id, now, now))
        return item_id
