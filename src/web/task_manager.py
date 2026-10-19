import logging
import threading
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from contextlib import closing

from src.pipeline_runner import WingScribePipeline
from src.storage.catalogue import AssetCatalogue
from src.storage.job_session import JobSession, JobBusyError

BASE_DIR = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


class ListLogHandler(logging.Handler):
    def __init__(self, manager, owner):
        super().__init__()
        self.manager = manager
        self.owner = owner
        self.worker_prefix = f"wingscribe-photo-{manager.task_id}_"

    def emit(self, record):
        if record.thread != self.owner and not record.threadName.startswith(self.worker_prefix):
            return
        self.manager.broadcast_log(self.format(record))
        if record.levelno >= logging.ERROR:
            self.manager.record_error(record.getMessage())


class TaskManager:
    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self, config_path=None, config_override=None):
        self._config_snapshot = deepcopy(config_override)
        self.config_path = Path(config_path) if config_path else BASE_DIR / "config/settings.yaml"
        self._lock = threading.RLock()
        self.is_running = False
        self.should_stop = False
        self.logs = []
        self._log_offset = 0
        self.websocket_clients = []
        self.state = "idle"
        self.task_id = None
        self.error = None
        self.started_at = None
        self.finished_at = None
        self.processed = 0
        self.total = 0
        self._thread = None
        self.job_id = None
        self.recovered_jobs = 0
        self.persisted_job = None
        self._restore_job()

    def _restore_job(self):
        """Restore a saved result; never reclaim a database owned by a live worker."""
        if self._config_snapshot is None:
            return
        configured = self._config_snapshot.get('paths', {}).get('db_path') or 'data/db/wingscribe.db'
        path = Path(configured)
        if not path.is_absolute():
            path = BASE_DIR / path
        if not path.is_file():
            return
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='processing_jobs'").fetchone():
                    return
            catalogue = AssetCatalogue(path)
            try:
                with JobSession(catalogue) as session:
                    self.recovered_jobs = session.recover()
            except JobBusyError:
                # The current owner remains authoritative; this manager cannot stop it.
                return
            rows = catalogue._read('SELECT * FROM processing_jobs ORDER BY created_at DESC,id DESC LIMIT 1', ())
            if rows:
                saved = rows[0]
                self.persisted_job = saved
                self.job_id, self.task_id = saved['id'], saved['request_key']
                self.state, self.error = saved['status'], saved['error']
                self.started_at, self.finished_at = saved['created_at'], saved['updated_at']
                items = catalogue.list_job_items(self.job_id)
                self.total = len(items)
                self.processed = sum(i['status'] in {'completed', 'skipped', 'failed'} for i in items)
        except (OSError, sqlite3.Error, ValueError) as exc:
            logger.warning('Could not restore saved pipeline status: %s', exc)

    @classmethod
    def get_instance(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def snapshot(self):
        with self._lock:
            return dict(task_id=self.task_id, state=self.state, is_running=self.is_running,
                        error=self.error, started_at=self.started_at, finished_at=self.finished_at,
                        processed=self.processed, total=self.total, job_id=self.job_id,
                        recovered_jobs=self.recovered_jobs, persisted_job=self.persisted_job)

    def stop(self):
        with self._lock:
            if not self.is_running:
                return False
            self.should_stop = True
            self.state = "stopping"
            return True

    def wait(self):
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def record_error(self, message):
        with self._lock:
            if self.error is None:
                self.error = str(message)

    def broadcast_log(self, message):
        with self._lock:
            self.logs.append(message)
            if len(self.logs) > 1000:
                removed = len(self.logs) - 1000
                del self.logs[:removed]
                self._log_offset += removed

    def logs_since(self, cursor=None):
        with self._lock:
            index = cursor[1] if cursor and cursor[0] == self.task_id else self._log_offset
            start = max(0, index - self._log_offset)
            return (self.task_id, self._log_offset + len(self.logs)), list(self.logs[start:])

    def _start(self, target, args, message):
        with self._lock:
            if self.is_running:
                return False
            self.is_running = True
            self.should_stop = False
            self.state = "starting"
            self.task_id = uuid4().hex
            self.started_at = datetime.now(timezone.utc).isoformat()
            self.finished_at = None
            self.error = None
            self.processed = self.total = 0
            self.job_id = None
            self.persisted_job = None
            self.recovered_jobs = 0
            self.logs = [message]
            self._log_offset = 0
            try:
                self._thread = threading.Thread(target=target, args=args, daemon=True)
                self._thread.start()
            except Exception as exc:
                self.error = str(exc)
                self.state = "failed"
                self.is_running = False
                self.finished_at = datetime.now(timezone.utc).isoformat()
                return False
            return True

    def start_pipeline(self, start_date=None, end_date=None):
        return self._start(self._run_pipeline_thread, (start_date, end_date), "Starting pipeline...")

    def start_pipeline_by_folders(self, folder_paths, recursive=True):
        return self._start(self._run_pipeline_thread_by_folders, (list(folder_paths), recursive),
                           "Starting pipeline for selected folders...")

    def _run_pipeline_thread(self, start_date, end_date):
        self._execute(lambda runner: runner.run(start_date=start_date, end_date=end_date))

    def _run_pipeline_thread_by_folders(self, folder_paths, recursive):
        self._execute(lambda runner: runner.run_by_folders(folder_paths, recursive=recursive))

    def _execute(self, run):
        root_logger = logging.getLogger()
        handler = ListLogHandler(self, threading.get_ident())
        runner = None
        root_logger.addHandler(handler)
        try:
            if not self.should_stop:
                self.broadcast_log("Initializing pipeline (this may take a while on first run)...")
                options = {"config_override": self._config_snapshot} if self._config_snapshot is not None else {}
                runner = WingScribePipeline(str(self.config_path), init_timeout=120, **options)
                def progress(processed, total):
                    with self._lock:
                        self.processed, self.total = processed, total
                    self.broadcast_log(f"[PROGRESS] {processed}/{total}")
                runner.worker_thread_prefix = f"wingscribe-photo-{self.task_id}"
                runner.task_request_key = self.task_id
                def job_started(job_id, recovered):
                    with self._lock:
                        self.job_id, self.recovered_jobs = job_id, recovered
                runner._job_callback = job_started
                runner.set_progress_callback(progress)
                runner.set_stop_checker(lambda: self.should_stop)
                with self._lock:
                    if not self.should_stop:
                        self.state = "running"
                if not self.should_stop:
                    run(runner)
        except Exception as exc:
            self.record_error(exc)
            self.broadcast_log(f"Error: {exc}")
        finally:
            if runner is not None and self.job_id and getattr(runner, 'catalogue', None) is not None:
                try:
                    self.persisted_job = runner.catalogue.get_job(self.job_id)
                except Exception as exc:
                    self.record_error(exc)
            if runner is not None and getattr(runner, "db", None) is not None:
                try:
                    runner.db.close()
                except Exception as exc:
                    self.record_error(exc)
            root_logger.removeHandler(handler)
            with self._lock:
                self.state = "failed" if self.error else ("stopped" if self.should_stop else "completed")
                self.finished_at = datetime.now(timezone.utc).isoformat()
                self.is_running = False
