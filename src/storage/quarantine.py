"""Additive, backed-up operation journal for recoverable photo moves."""
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

from src.storage.catalogue import _json, _now


class QuarantineJournal:
    def __init__(self, store):
        self.store = store

    def initialize(self):
        with self.store._connection(write=True) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            expected = {'quarantine_schema', 'quarantine_operations', 'quarantine_items'}
            if expected & tables:
                if not expected <= tables or [r[0] for r in conn.execute('SELECT version FROM quarantine_schema')] != [1]:
                    raise ValueError('Unsupported or incomplete quarantine journal')
                return
            directory = self.store.db_path.parent/'backups'
            directory.mkdir(parents=True, exist_ok=True)
            backup = directory/f'before-quarantine-{uuid4().hex}.db'
            with closing(sqlite3.connect(self.store.db_path.as_uri()+'?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(backup)) as target:
                    source.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('Quarantine backup integrity check failed')
            conn.execute('CREATE TABLE quarantine_schema (version INTEGER PRIMARY KEY CHECK(version=1))')
            conn.execute('INSERT INTO quarantine_schema VALUES (1)')
            conn.execute('''CREATE TABLE quarantine_operations (
                id TEXT PRIMARY KEY, preview_json TEXT NOT NULL, created_at TEXT NOT NULL,
                restore_hash TEXT)''')
            conn.execute('''CREATE TABLE quarantine_items (
                operation_id TEXT NOT NULL REFERENCES quarantine_operations(id),
                version_id TEXT NOT NULL REFERENCES asset_versions(id),
                state TEXT NOT NULL CHECK(state IN ('pending','moving','quarantined','restoring','restored','failed')),
                error TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(operation_id,version_id))''')

    def get(self, operation_id):
        with self.store._connection() as conn:
            row = conn.execute('SELECT * FROM quarantine_operations WHERE id=?', (operation_id,)).fetchone()
            if row is None:
                return None
            return dict(plan=json.loads(row['preview_json']), created_at=row['created_at'],
                        restore_hash=row['restore_hash'],
                        states={r['version_id']: dict(r) for r in conn.execute(
                            'SELECT * FROM quarantine_items WHERE operation_id=?', (operation_id,))})

    def save(self, plan):
        with self.store._connection(write=True) as conn:
            conn.execute('INSERT INTO quarantine_operations VALUES (?,?,?,NULL)',
                         (plan['operation_id'], _json(plan), _now()))
            conn.executemany('INSERT INTO quarantine_items VALUES (?,?,?,NULL,?)',
                             [(plan['operation_id'], i['version_id'], 'pending', _now()) for i in plan['items']])

    @staticmethod
    def update(conn, oid, vid, state, error=None):
        conn.execute('UPDATE quarantine_items SET state=?,error=?,updated_at=? '
                     'WHERE operation_id=? AND version_id=?', (state,error,_now(),oid,vid))
