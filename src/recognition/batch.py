"""
批量识别服务

提供异步批量识别功能，支持进度跟踪和 webhook 回调。
"""
import asyncio
import uuid
import time
from typing import Dict, List, Optional, Callable
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from .protocol import (
    RecognizeRequest,
    RecognizeResponse,
    BatchRecognizeRequest,
    BatchRecognizeResponse,
    BatchResultResponse,
    BatchResultItem,
    BatchJobStatus,
    RecognitionPlatform,
)
from .cloud.factory import RecognizerFactory
from .cloud import RecognizerFactory as CloudFactory
import logging

logger = logging.getLogger(__name__)


class BatchJob:
    """批量任务"""

    def __init__(
        self,
        batch_id: str,
        images: List[RecognizeRequest],
        webhook_url: Optional[str] = None,
        notify_email: Optional[str] = None
    ):
        self.id = batch_id
        self.images = images
        self.webhook_url = webhook_url
        self.notify_email = notify_email
        self.status = BatchJobStatus.pending
        self.results: List[RecognizeResponse] = []
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self._index = 0

    @property
    def total(self) -> int:
        return len(self.images)

    @property
    def completed(self) -> int:
        return len([r for r in self.results if r.success])

    @property
    def failed(self) -> int:
        return len(self.results) - self.completed

    @property
    def progress_percent(self) -> float:
        if not self.results:
            return 0.0
        return len(self.results) / self.total * 100.0


class BatchRecognitionService:
    """批量识别服务"""

    def __init__(
        self,
        max_concurrent: int = 10,
        max_concurrent_per_platform: int = 5,
        recognizer_factory=None
    ):
        """
        初始化批量识别服务

        Args:
            max_concurrent: 全局最大并发数
            max_concurrent_per_platform: 每个平台的最大并发数
        """
        self.recognizer_factory = recognizer_factory or CloudFactory
        self.max_concurrent = max_concurrent
        self.max_concurrent_per_platform = max_concurrent_per_platform
        self.jobs: Dict[str, BatchJob] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._running_tasks: Dict[str, asyncio.Task] = {}

    async def close(self):
        tasks = list(self._running_tasks.values())
        for batch_id in list(self._running_tasks):
            self.cancel_job(batch_id)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._running_tasks.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def create_batch(
        self,
        request: BatchRecognizeRequest
    ) -> BatchRecognizeResponse:
        """创建批量任务"""
        # 生成 batch_id
        batch_id = request.batch_id or f"batch_{uuid.uuid4().hex[:12]}"

        # 创建任务
        job = BatchJob(
            batch_id=batch_id,
            images=request.images,
            webhook_url=request.webhook_url,
            notify_email=request.notify_email
        )
        self.jobs[batch_id] = job

        logger.info(f"Created batch job {batch_id} with {len(request.images)} images")

        return BatchRecognizeResponse(
            batch_id=batch_id,
            total=job.total,
            status=BatchJobStatus.pending,
            progress_percent=0.0,
            webhook_url=request.webhook_url
        )

    async def start_batch(
        self,
        batch_id: str,
        background_callback: Optional[Callable] = None
    ) -> bool:
        """
        开始处理批量任务

        Args:
            batch_id: 批次 ID
            background_callback: 完成后回调函数

        Returns:
            是否成功启动
        """
        if batch_id not in self.jobs:
            return False

        job = self.jobs[batch_id]
        if job.status != BatchJobStatus.pending:
            return False

        job.status = BatchJobStatus.processing
        job.started_at = datetime.now()

        # 创建异步任务
        task = asyncio.create_task(
            self._process_batch(job, background_callback)
        )
        self._running_tasks[batch_id] = task

        logger.info(f"Started processing batch {batch_id}")

        return True

    async def _process_batch(
        self,
        job: BatchJob,
        callback: Optional[Callable] = None
    ):
        """处理批量任务"""
        try:
            # 按平台分组以优化并发
            platform_groups: Dict[str, List[int]] = {}
            for i, req in enumerate(job.images):
                platform = req.platform.value if hasattr(req.platform, 'value') else req.platform
                if platform not in platform_groups:
                    platform_groups[platform] = []
                platform_groups[platform].append(i)

            # 并发处理各平台
            async def process_platform(
                platform: str,
                indices: List[int]
            ) -> List[RecognizeResponse]:
                """处理单个平台的所有图片"""
                # 创建该平台的识别器
                try:
                    recognizer = self.recognizer_factory.create(platform)
                except Exception as e:
                    logger.error(f"Failed to create recognizer for {platform}: {e}")
                    # 返回错误响应
                    return [
                        RecognizeResponse(
                            success=False,
                            image_path=job.images[i].image_path,
                            results=[],
                            platform=platform,
                            processing_time_ms=0,
                            error=str(e)
                        )
                        for i in indices
                    ]

                # 获取该平台的图片请求
                requests = [job.images[i] for i in indices]

                # 并发识别
                return await recognizer.recognize_batch(
                    requests,
                    max_concurrent=self.max_concurrent_per_platform
                )

            # 执行所有平台的识别
            all_results: List[RecognizeResponse] = [None] * job.total

            async def run_and_assign(platform: str, indices: List[int]):
                results = await process_platform(platform, indices)
                for idx, result in zip(indices, results):
                    all_results[idx] = result

            # 创建所有平台任务
            platform_tasks = [
                run_and_assign(platform, indices)
                for platform, indices in platform_groups.items()
            ]

            await asyncio.gather(*platform_tasks)

            # 更新任务状态
            job.results = all_results
            job.status = BatchJobStatus.completed
            job.completed_at = datetime.now()

            logger.info(
                f"Completed batch {job.id}: "
                f"{job.completed}/{job.total} succeeded"
            )

            # 触发 webhook 回调
            if job.webhook_url:
                await self._trigger_webhook(job)

            # 触发回调函数
            if callback:
                callback(job)

        except Exception as e:
            logger.error(f"Error processing batch {job.id}: {e}")
            job.status = BatchJobStatus.failed
            job.completed_at = datetime.now()

    async def _trigger_webhook(self, job: BatchJob):
        """触发 webhook 回调"""
        if not job.webhook_url:
            return

        try:
            import httpx

            payload = {
                "batch_id": job.id,
                "status": job.status.value,
                "total": job.total,
                "completed": job.completed,
                "failed": job.failed,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None
            }

            async with httpx.AsyncClient(timeout=30) as client:
                await client.post(job.webhook_url, json=payload)

            logger.info(f"Webhook triggered for batch {job.id}")

        except Exception as e:
            logger.error(f"Failed to trigger webhook for batch {job.id}: {e}")

    def get_status(self, batch_id: str) -> Optional[BatchRecognizeResponse]:
        """获取任务状态"""
        if batch_id not in self.jobs:
            return None

        job = self.jobs[batch_id]
        return BatchRecognizeResponse(
            batch_id=batch_id,
            total=job.total,
            completed=len(job.results),
            failed=job.failed,
            status=job.status,
            progress_percent=job.progress_percent,
            webhook_url=job.webhook_url,
            created_at=job.started_at or datetime.now(),
            completed_at=job.completed_at
        )

    def get_result(self, batch_id: str) -> Optional[BatchResultResponse]:
        """获取任务完整结果"""
        if batch_id not in self.jobs:
            return None

        job = self.jobs[batch_id]

        results = []
        for i, response in enumerate(job.results):
            results.append(BatchResultItem(
                index=i,
                image_path=response.image_path,
                success=response.success,
                result=response if response.success else None,
                error=response.error
            ))

        return BatchResultResponse(
            batch_id=batch_id,
            status=job.status,
            total=job.total,
            results=results,
            created_at=job.started_at or datetime.now(),
            completed_at=job.completed_at
        )

    def list_jobs(
        self,
        status: Optional[BatchJobStatus] = None,
        limit: int = 20
    ) -> List[BatchRecognizeResponse]:
        """列出任务"""
        jobs = list(self.jobs.values())

        if status:
            jobs = [j for j in jobs if j.status == status]

        # 按创建时间排序
        jobs.sort(key=lambda j: j.started_at or datetime.min, reverse=True)

        return [
            BatchRecognizeResponse(
                batch_id=j.id,
                total=j.total,
                completed=len(j.results),
                failed=j.failed,
                status=j.status,
                progress_percent=j.progress_percent,
                created_at=j.started_at or datetime.now(),
                completed_at=j.completed_at
            )
            for j in jobs[:limit]
        ]

    def cancel_job(self, batch_id: str) -> bool:
        """取消任务"""
        if batch_id not in self.jobs:
            return False

        job = self.jobs[batch_id]

        # 取消运行中的任务
        if batch_id in self._running_tasks:
            self._running_tasks[batch_id].cancel()
            del self._running_tasks[batch_id]

        if job.status == BatchJobStatus.processing:
            job.status = BatchJobStatus.failed
            job.completed_at = datetime.now()

        return True

    def cleanup_completed(self, older_than_hours: int = 24) -> int:
        """清理已完成的任务"""
        cutoff = datetime.now().timestamp() - older_than_hours * 3600
        to_delete = []

        for batch_id, job in self.jobs.items():
            if job.completed_at:
                if job.completed_at.timestamp() < cutoff:
                    to_delete.append(batch_id)

        for batch_id in to_delete:
            del self.jobs[batch_id]

        return len(to_delete)
