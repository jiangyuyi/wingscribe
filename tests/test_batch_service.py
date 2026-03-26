import asyncio
from datetime import datetime, timedelta

from src.recognition.batch import BatchRecognitionService
from src.recognition.protocol import (
    BatchJobStatus,
    BatchRecognizeRequest,
    RecognizeRequest,
    RecognizeResponse,
    RecognitionPlatform,
)


def _make_request(image_path: str, platform: RecognitionPlatform) -> RecognizeRequest:
    return RecognizeRequest(image_path=image_path, platform=platform)


def _make_response(image_path: str, platform: str, success: bool = True, error: str | None = None) -> RecognizeResponse:
    return RecognizeResponse(
        success=success,
        image_path=image_path,
        results=[],
        platform=platform,
        processing_time_ms=1,
        error=error,
    )


def test_create_batch_registers_pending_job():
    service = BatchRecognitionService()
    request = BatchRecognizeRequest(
        images=[_make_request("a.jpg", RecognitionPlatform.local)],
        webhook_url="https://example.com/hook",
    )

    response = service.create_batch(request)

    assert response.batch_id in service.jobs
    job = service.jobs[response.batch_id]
    assert job.status == BatchJobStatus.pending
    assert job.total == 1
    assert job.webhook_url == "https://example.com/hook"


def test_start_batch_sets_processing_and_tracks_task(monkeypatch):
    service = BatchRecognitionService()
    request = BatchRecognizeRequest(images=[_make_request("a.jpg", RecognitionPlatform.local)])
    batch = service.create_batch(request)

    created_coroutines = []

    class StubTask:
        def cancel(self):
            pass

    def fake_create_task(coro):
        created_coroutines.append(coro)
        return StubTask()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    result = asyncio.run(service.start_batch(batch.batch_id))

    assert result is True
    assert service.jobs[batch.batch_id].status == BatchJobStatus.processing
    assert service.jobs[batch.batch_id].started_at is not None
    assert batch.batch_id in service._running_tasks
    assert len(created_coroutines) == 1
    created_coroutines[0].close()


def test_start_batch_rejects_missing_or_non_pending_jobs():
    service = BatchRecognitionService()

    assert asyncio.run(service.start_batch("missing")) is False

    request = BatchRecognizeRequest(images=[_make_request("a.jpg", RecognitionPlatform.local)])
    batch = service.create_batch(request)
    service.jobs[batch.batch_id].status = BatchJobStatus.processing

    assert asyncio.run(service.start_batch(batch.batch_id)) is False


def test_process_batch_groups_platforms_and_restores_original_order(monkeypatch):
    service = BatchRecognitionService(max_concurrent_per_platform=3)
    request = BatchRecognizeRequest(
        images=[
            _make_request("local-1.jpg", RecognitionPlatform.local),
            _make_request("hf-1.jpg", RecognitionPlatform.huggingface),
            _make_request("local-2.jpg", RecognitionPlatform.local),
        ]
    )
    batch = service.create_batch(request)
    job = service.jobs[batch.batch_id]
    callback_calls = []
    platform_calls = []

    class StubRecognizer:
        def __init__(self, platform_name):
            self.platform_name = platform_name

        async def recognize_batch(self, requests, max_concurrent):
            platform_calls.append(
                (self.platform_name, [req.image_path for req in requests], max_concurrent)
            )
            return [
                _make_response(req.image_path, self.platform_name)
                for req in requests
            ]

    def fake_create(platform):
        return StubRecognizer(platform)

    async def fake_trigger_webhook(_job):
        raise AssertionError("webhook should not be called without webhook_url")

    monkeypatch.setattr("src.recognition.batch.CloudFactory.create", fake_create)
    monkeypatch.setattr(service, "_trigger_webhook", fake_trigger_webhook)

    asyncio.run(service._process_batch(job, callback_calls.append))

    assert job.status == BatchJobStatus.completed
    assert [response.image_path for response in job.results] == [
        "local-1.jpg",
        "hf-1.jpg",
        "local-2.jpg",
    ]
    assert [response.platform for response in job.results] == [
        "local",
        "huggingface",
        "local",
    ]
    assert ("local", ["local-1.jpg", "local-2.jpg"], 3) in platform_calls
    assert ("huggingface", ["hf-1.jpg"], 3) in platform_calls
    assert callback_calls == [job]


def test_cancel_job_cancels_running_task_and_marks_processing_job_failed():
    service = BatchRecognitionService()
    request = BatchRecognizeRequest(images=[_make_request("a.jpg", RecognitionPlatform.local)])
    batch = service.create_batch(request)
    job = service.jobs[batch.batch_id]
    job.status = BatchJobStatus.processing

    class StubTask:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    task = StubTask()
    service._running_tasks[batch.batch_id] = task

    result = service.cancel_job(batch.batch_id)

    assert result is True
    assert task.cancelled is True
    assert batch.batch_id not in service._running_tasks
    assert job.status == BatchJobStatus.failed
    assert job.completed_at is not None


def test_cleanup_completed_removes_only_expired_jobs():
    service = BatchRecognitionService()
    request = BatchRecognizeRequest(images=[_make_request("a.jpg", RecognitionPlatform.local)])
    old_batch = service.create_batch(request)
    fresh_batch = service.create_batch(request)

    service.jobs[old_batch.batch_id].completed_at = datetime.now() - timedelta(hours=48)
    service.jobs[fresh_batch.batch_id].completed_at = datetime.now() - timedelta(hours=1)

    removed = service.cleanup_completed(older_than_hours=24)

    assert removed == 1
    assert old_batch.batch_id not in service.jobs
    assert fresh_batch.batch_id in service.jobs
