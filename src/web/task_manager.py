import logging
import os
import threading
from pathlib import Path

from src.pipeline_runner import WingScribePipeline


BASE_DIR = Path(__file__).parent.parent.parent.absolute()
logger = logging.getLogger(__name__)


class ListLogHandler(logging.Handler):
    def __init__(self, log_list):
        super().__init__()
        self.log_list = log_list

    def emit(self, record):
        msg = self.format(record)
        self.log_list.append(msg)


class TaskManager:
    _instance = None

    def __init__(self):
        self.is_running = False
        self.should_stop = False
        self.logs = []
        self.websocket_clients = []

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = TaskManager()
        return cls._instance

    def stop(self):
        self.should_stop = True

    def broadcast_log(self, message: str):
        self.logs.append(message)
        if len(self.logs) > 1000:
            self.logs.pop(0)

    def start_pipeline(self, start_date=None, end_date=None):
        logger.info(
            f"[TaskManager] start_pipeline called with start_date={start_date}, end_date={end_date}"
        )
        if self.is_running:
            logger.warning("[TaskManager] Pipeline already running, rejecting request")
            return False

        self.is_running = True
        self.should_stop = False
        self.logs = ["Starting pipeline..."]
        logger.info("[TaskManager] Pipeline flag set, starting thread...")

        thread = threading.Thread(
            target=self._run_pipeline_thread,
            args=(start_date, end_date),
            daemon=True,
        )
        thread.start()
        logger.info("[TaskManager] Thread started, returning success")
        return True

    def start_pipeline_by_folders(self, folder_paths: list, recursive: bool = True):
        logger.info(
            f"[TaskManager] start_pipeline_by_folders called with paths={folder_paths}, recursive={recursive}"
        )
        if self.is_running:
            logger.warning("[TaskManager] Pipeline already running, rejecting request")
            return False

        self.is_running = True
        self.should_stop = False
        self.logs = ["Starting pipeline for selected folders..."]
        logger.info("[TaskManager] Pipeline flag set, starting thread...")

        thread = threading.Thread(
            target=self._run_pipeline_thread_by_folders,
            args=(folder_paths, recursive),
            daemon=True,
        )
        thread.start()
        logger.info("[TaskManager] Thread started, returning success")
        return True

    def _run_pipeline_thread_by_folders(self, folder_paths: list, recursive: bool):
        log_capture = logging.getLogger()
        handler = ListLogHandler(self.logs)
        try:
            os.chdir(str(BASE_DIR))
            log_capture.addHandler(handler)

            self.logs.append("Initializing pipeline (this may take a while on first run)...")
            runner = WingScribePipeline(str(BASE_DIR / "config/settings.yaml"), init_timeout=120)

            def progress_callback(processed, total):
                self.logs.append(f"[PROGRESS] {processed}/{total}")

            runner.set_progress_callback(progress_callback)
            runner.set_stop_checker(lambda: self.should_stop)

            self.logs.append("Pipeline initialized, processing selected folders...")
            runner.run_by_folders(folder_paths, recursive=recursive)
            logger.info("Pipeline (by folders) execution completed.")
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            self.logs.append(f"Error: {str(e)}")
        finally:
            self.is_running = False
            log_capture.removeHandler(handler)

    def _run_pipeline_thread(self, start_date, end_date):
        log_capture = logging.getLogger()
        handler = ListLogHandler(self.logs)
        try:
            os.chdir(str(BASE_DIR))
            log_capture.addHandler(handler)

            self.logs.append("Initializing pipeline (this may take a while on first run)...")
            runner = WingScribePipeline(str(BASE_DIR / "config/settings.yaml"), init_timeout=120)

            def progress_callback(processed, total):
                self.logs.append(f"[PROGRESS] {processed}/{total}")

            runner.set_progress_callback(progress_callback)
            runner.set_stop_checker(lambda: self.should_stop)

            self.logs.append("Pipeline initialized, starting processing...")
            runner.run(start_date=start_date, end_date=end_date)
            logger.info("Pipeline execution completed.")
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            self.logs.append(f"Error: {str(e)}")
        finally:
            self.is_running = False
            log_capture.removeHandler(handler)
