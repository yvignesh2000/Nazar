"""
Nazar — Async Background Job Queue

In-process asyncio job queue with progress tracking and cancellation support.
Decouples long-running operations (campaign sends, bulk imports) from HTTP
request handlers so responses are immediate.

Design:
- Jobs are enqueued and executed as asyncio.Tasks
- A semaphore caps concurrent running jobs (default: 3)
- Progress updates are pushed via callback (WebSocket-friendly)
- Job state is kept in-memory; active jobs survive within process lifetime

For production scale (horizontal scaling): replace with Celery + Redis.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobQueue:
    """
    Async job queue with bounded concurrency.

    Usage::

        async def my_worker(job_id, params, update_progress):
            for i in range(params["total"]):
                await do_work(i)
                update_progress(job_id, i + 1, params["total"])

        job_id = await job_queue.enqueue("my_job", {"total": 100}, my_worker)
        # Returns immediately; work happens in background
    """

    def __init__(self, max_concurrent=3):
        # type: (int) -> None
        self._max_concurrent = max_concurrent
        self._semaphore = None  # type: Optional[asyncio.Semaphore]  # created lazily (needs running loop)
        self.jobs = {}  # type: Dict[str, dict]
        self._tasks = {}  # type: Dict[str, asyncio.Task]

    def _get_semaphore(self):
        # type: () -> asyncio.Semaphore
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
        return self._semaphore

    async def enqueue(
        self,
        job_type,   # type: str
        params,     # type: dict
        callback,   # type: Callable[..., Awaitable[Any]]
    ):
        # type: (...) -> str
        """
        Add a job to the queue and start executing it.

        Args:
            job_type:  Short string label (e.g. "campaign_send", "bulk_import")
            params:    Dict of parameters forwarded to callback
            callback:  Async function ``async def cb(job_id, params, update_progress)``

        Returns:
            job_id string
        """
        job_id = "job_%s" % uuid.uuid4().hex[:10]
        now = datetime.now(IST).isoformat()
        self.jobs[job_id] = {
            "id": job_id,
            "type": job_type,
            "status": JobStatus.PENDING,
            "params": params,
            "progress": {"current": 0, "total": 0, "failed": 0},
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "error": None,
        }
        task = asyncio.create_task(self._run(job_id, callback, params))
        task.add_done_callback(lambda t: self._on_task_done(job_id, t))
        self._tasks[job_id] = task
        logger.info("Job %s (%s) enqueued", job_id, job_type)
        return job_id

    def _on_task_done(self, job_id, task):
        # type: (str, asyncio.Task) -> None
        if task.cancelled():
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = JobStatus.CANCELLED
        self._tasks.pop(job_id, None)

    async def _run(self, job_id, callback, params):
        # type: (str, Callable, dict) -> None
        async with self._get_semaphore():
            job = self.jobs[job_id]
            job["status"] = JobStatus.RUNNING
            job["started_at"] = datetime.now(IST).isoformat()
            logger.info("Job %s started", job_id)
            try:
                await callback(job_id, params, self._update_progress)
                job["status"] = JobStatus.COMPLETED
                logger.info("Job %s completed", job_id)
            except asyncio.CancelledError:
                job["status"] = JobStatus.CANCELLED
                logger.info("Job %s cancelled", job_id)
                raise
            except Exception as exc:
                job["status"] = JobStatus.FAILED
                job["error"] = str(exc)
                logger.error("Job %s failed: %s", job_id, exc, exc_info=True)
            finally:
                job["completed_at"] = datetime.now(IST).isoformat()

    def _update_progress(self, job_id, current, total, failed=0):
        # type: (str, int, int, int) -> None
        """Update job progress counters. Called from within callback."""
        if job_id in self.jobs:
            self.jobs[job_id]["progress"] = {
                "current": current,
                "total": total,
                "failed": failed,
            }

    def get_job(self, job_id):
        # type: (str) -> Optional[dict]
        """Return job record or None if not found."""
        return self.jobs.get(job_id)

    def list_jobs(self, job_type=None, status=None):
        # type: (Optional[str], Optional[JobStatus]) -> List[dict]
        """List jobs, optionally filtered by type and/or status."""
        jobs = list(self.jobs.values())
        if job_type:
            jobs = [j for j in jobs if j["type"] == job_type]
        if status:
            jobs = [j for j in jobs if j["status"] == status]
        return sorted(jobs, key=lambda j: j["created_at"], reverse=True)

    def cancel(self, job_id):
        # type: (str) -> bool
        """Cancel a running or pending job. Returns True if cancelled."""
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            if job_id in self.jobs:
                self.jobs[job_id]["status"] = JobStatus.CANCELLED
            logger.info("Job %s cancellation requested", job_id)
            return True
        return False

    def prune_completed(self, keep_last=100):
        # type: (int) -> None
        """Remove old completed/failed jobs, keeping the most recent ``keep_last``."""
        done_statuses = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
        done = [j for j in self.jobs.values() if j["status"] in done_statuses]
        done.sort(key=lambda j: j.get("completed_at") or "", reverse=True)
        for old_job in done[keep_last:]:
            self.jobs.pop(old_job["id"], None)


# Singleton used across server.py
job_queue = JobQueue(max_concurrent=3)
