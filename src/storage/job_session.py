"""Single-owner local job state transitions and explicit crash recovery.

The OS lock is held for the entire session, not merely a SQLite transaction.
Keep the lock file: unlinking it could let another process lock a different file.
"""
import json
import os
from pathlib import Path

from src.storage.catalogue import _now


class JobBusyError(RuntimeError):
    pass


class JobSession:
    def __init__(self, catalogue):
        self.catalogue = catalogue
        self._lock_file = None
        self._has_started = False

    def __enter__(self):
        if self._lock_file is not None:
            raise RuntimeError('Job session is already open')
        path = Path(str(self.catalogue.db_path) + '.worker.lock')
        stream = path.open('a+b')
        try:
            if path.stat().st_size == 0:
                stream.write(b'\0')
                stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise JobBusyError('Another worker owns this catalogue') from exc
        self._lock_file = stream
        self._has_started = False
        return self

    def __exit__(self, *args):
        if self._lock_file is not None:
            self._lock_file.close()  # OS also releases it when the process dies.
            self._lock_file = None

    def _require_open(self):
        if self._lock_file is None:
            raise RuntimeError('An open worker session is required')

    def recover(self) -> int:
        """Call before starting work, after exclusively acquiring the OS lock.

        Does not execute any photo work or automatically retry failed output.
        """
        self._require_open()
        if self._has_started:
            raise RuntimeError('Recovery must precede work in this session')
        with self.catalogue.transaction() as tx:
            active = tx.conn.execute("SELECT id FROM processing_jobs WHERE status='running'").fetchall()
            for row in active:
                self._interrupt(tx.conn, row['id'], 'Worker ended before task completion')
            return len(active)

    @staticmethod
    def _interrupt(conn, job_id, error):
        now = _now()
        conn.execute("UPDATE job_items SET status='interrupted', error=?, updated_at=? "
                     "WHERE job_id=? AND status IN ('pending','running')", (error, now, job_id))
        conn.execute("UPDATE processing_jobs SET status='interrupted', error=?, updated_at=? WHERE id=?",
                     (error, now, job_id))

    def start(self, request_key: str, parameters: dict) -> str:
        self._require_open()
        with self.catalogue.transaction() as tx:
            if tx.conn.execute("SELECT 1 FROM processing_jobs WHERE status='running'").fetchone():
                raise RuntimeError('Recover or finish the active job before starting another')
            job = tx.create_job(request_key, parameters)
            status = tx.conn.execute('SELECT status FROM processing_jobs WHERE id=?', (job,)).fetchone()[0]
            if status != 'pending':
                raise ValueError('Request already finished; use a new retry request key')
            tx.conn.execute("UPDATE processing_jobs SET status='running', updated_at=? WHERE id=?", (_now(), job))
            self._has_started = True
            return job

    @staticmethod
    def _require_running(conn, job_id):
        row = conn.execute('SELECT status FROM processing_jobs WHERE id=?', (job_id,)).fetchone()
        if not row or row[0] != 'running':
            raise ValueError('Job is not running')

    def enqueue(self, job_id: str, version_id: str) -> str:
        self._require_open()
        with self.catalogue.transaction() as tx:
            self._require_running(tx.conn, job_id)
            return tx.enqueue(job_id, version_id)

    def claim(self, job_id: str) -> dict | None:
        self._require_open()
        with self.catalogue.transaction() as tx:
            self._require_running(tx.conn, job_id)
            row = tx.conn.execute("SELECT * FROM job_items WHERE job_id=? AND status='pending' "
                                  'ORDER BY created_at,id LIMIT 1', (job_id,)).fetchone()
            if row is None:
                return None
            tx.conn.execute("UPDATE job_items SET status='running', attempts=attempts+1, updated_at=? WHERE id=?",
                            (_now(), row['id']))
            return dict(tx.conn.execute('SELECT * FROM job_items WHERE id=?', (row['id'],)).fetchone())

    def finish_item(self, item_id: str, outcome: str, *, reason=None, error=None):
        self._require_open()
        if outcome not in {'completed', 'failed', 'skipped'}:
            raise ValueError('Invalid item outcome')
        if outcome == 'failed' and not error:
            raise ValueError('Failed item requires error')
        if outcome == 'skipped' and not reason:
            raise ValueError('Skipped item requires reason')
        with self.catalogue.transaction() as tx:
            row = tx.conn.execute('SELECT * FROM job_items WHERE id=?', (item_id,)).fetchone()
            if not row or row['status'] != 'running':
                raise ValueError('Item must be claimed before completion')
            self._require_running(tx.conn, row['job_id'])
            tx.conn.execute('UPDATE job_items SET status=?,reason=?,error=?,updated_at=? WHERE id=?',
                            (outcome, reason, error, _now(), item_id))

    def finish(self, job_id: str, outcome: str, *, error=None):
        self._require_open()
        if outcome not in {'completed', 'failed', 'stopped'}:
            raise ValueError('Invalid job outcome')
        if outcome == 'failed' and not error:
            raise ValueError('Failed job requires error')
        with self.catalogue.transaction() as tx:
            self._require_running(tx.conn, job_id)
            states = [r[0] for r in tx.conn.execute('SELECT status FROM job_items WHERE job_id=?', (job_id,))]
            if 'running' in states:
                raise ValueError('Drain running items before finishing the job')
            if outcome == 'completed' and any(s not in {'completed', 'skipped'} for s in states):
                raise ValueError('Cannot complete a job with unfinished or failed items')
            now = _now()
            tx.conn.execute("UPDATE job_items SET status='interrupted',error=?,updated_at=? "
                            "WHERE job_id=? AND status='pending'", (error or 'Stopped before execution', now, job_id))
            tx.conn.execute('UPDATE processing_jobs SET status=?,error=?,updated_at=? WHERE id=?',
                            (outcome, error, now, job_id))

    def retry(self, old_job_id: str, request_key: str) -> str:
        """New job for failed/interrupted versions only; old history stays immutable."""
        self._require_open()
        with self.catalogue.transaction() as tx:
            if tx.conn.execute("SELECT 1 FROM processing_jobs WHERE status='running'").fetchone():
                raise RuntimeError('Recover or finish the active job before retrying')
            old = tx.conn.execute('SELECT * FROM processing_jobs WHERE id=?', (old_job_id,)).fetchone()
            if not old or old['status'] not in {'failed', 'stopped', 'interrupted'}:
                raise ValueError('Job is not retryable')
            items = tx.conn.execute("SELECT version_id FROM job_items WHERE job_id=? "
                                    "AND status IN ('failed','interrupted')", (old_job_id,)).fetchall()
            if not items:
                raise ValueError('No retryable version items; rescan unreadable sources separately')
            params = {'retry_of': old_job_id, 'original_parameters': json.loads(old['parameters_json'])}
            job = tx.create_job(request_key, params)
            if tx.conn.execute('SELECT status FROM processing_jobs WHERE id=?', (job,)).fetchone()[0] != 'pending':
                raise ValueError('Retry request key already used')
            for item in items:
                tx.enqueue(job, item['version_id'])
            tx.conn.execute("UPDATE processing_jobs SET status='running',updated_at=? WHERE id=?", (_now(), job))
            self._has_started = True
            return job
