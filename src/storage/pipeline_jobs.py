"""Job ownership for synchronous pipeline entry points."""
from contextlib import contextmanager
from uuid import uuid4

from src.storage.job_session import JobSession


@contextmanager
def pipeline_job(pipeline, selection):
    catalogue = getattr(pipeline, 'catalogue', None)
    if catalogue is None:  # Lightweight legacy test doubles have no persistent store.
        yield
        return
    with JobSession(catalogue) as session:
        recovered = session.recover()
        request_key = getattr(pipeline, 'task_request_key', None) or uuid4().hex
        job = session.start(request_key, selection)
        pipeline.job_id = job
        pipeline._job_session = session
        pipeline.total_files = pipeline.processed_count = 0
        try:
            callback = getattr(pipeline, '_job_callback', None)
            if callback:
                callback(job, recovered)
            publisher = getattr(pipeline, 'archive_publisher', None)
            if publisher is not None:
                pipeline.recovered_archives = publisher.recover()
            yield
            session.finish(job, 'stopped' if pipeline._should_stop() else 'completed')
        except Exception as exc:
            # All executor workers have drained before the entry point unwinds.
            session.abort(job, str(exc) or type(exc).__name__)
            raise
        finally:
            pipeline._job_session = None

