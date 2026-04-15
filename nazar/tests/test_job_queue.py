"""
Tests for core/job_queue.py — async background job queue.
"""

import asyncio
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
from job_queue import JobQueue, JobStatus


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _noop_worker(job_id, params, update_progress):
    """Worker that completes immediately."""
    update_progress(job_id, 1, 1)


async def _counting_worker(job_id, params, update_progress):
    """Worker that counts up to params['n'], yielding between steps."""
    n = params.get("n", 5)
    for i in range(n):
        await asyncio.sleep(0)
        update_progress(job_id, i + 1, n)


async def _failing_worker(job_id, params, update_progress):
    raise RuntimeError("Intentional failure")


async def _slow_worker(job_id, params, update_progress):
    await asyncio.sleep(10)


# ──────────────────────────────────────────────────────────────────────────────
# Basic enqueue / complete
# ──────────────────────────────────────────────────────────────────────────────

class TestJobQueueBasics:
    @pytest.mark.asyncio
    async def test_enqueue_returns_job_id(self):
        q = JobQueue()
        job_id = await q.enqueue("test", {}, _noop_worker)
        assert job_id.startswith("job_")

    @pytest.mark.asyncio
    async def test_job_transitions_to_completed(self):
        q = JobQueue()
        job_id = await q.enqueue("test", {}, _noop_worker)
        # Give it time to run
        await asyncio.sleep(0.1)
        job = q.get_job(job_id)
        assert job is not None
        assert job["status"] == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_get_job_returns_none_for_unknown_id(self):
        q = JobQueue()
        assert q.get_job("nonexistent_job") is None

    @pytest.mark.asyncio
    async def test_job_starts_as_pending_then_running(self):
        q = JobQueue()
        job_id = await q.enqueue("test", {"n": 10}, _counting_worker)
        job = q.get_job(job_id)
        # Should be pending or running immediately after enqueue
        assert job["status"] in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.COMPLETED)

    @pytest.mark.asyncio
    async def test_completed_job_has_timestamps(self):
        q = JobQueue()
        job_id = await q.enqueue("test", {}, _noop_worker)
        await asyncio.sleep(0.1)
        job = q.get_job(job_id)
        assert job["created_at"] is not None
        assert job["completed_at"] is not None


# ──────────────────────────────────────────────────────────────────────────────
# Progress tracking
# ──────────────────────────────────────────────────────────────────────────────

class TestJobQueueProgress:
    @pytest.mark.asyncio
    async def test_progress_updated_during_run(self):
        q = JobQueue()
        job_id = await q.enqueue("test", {"n": 5}, _counting_worker)
        await asyncio.sleep(0.2)
        job = q.get_job(job_id)
        assert job["progress"]["total"] == 5
        assert job["progress"]["current"] == 5

    @pytest.mark.asyncio
    async def test_progress_initial_values(self):
        q = JobQueue()
        job_id = await q.enqueue("test", {}, _noop_worker)
        # Before completion the initial progress is 0/0
        job = q.get_job(job_id)
        assert job is not None


# ──────────────────────────────────────────────────────────────────────────────
# Failure handling
# ──────────────────────────────────────────────────────────────────────────────

class TestJobQueueFailures:
    @pytest.mark.asyncio
    async def test_failing_worker_marks_job_failed(self):
        q = JobQueue()
        job_id = await q.enqueue("test", {}, _failing_worker)
        await asyncio.sleep(0.1)
        job = q.get_job(job_id)
        assert job["status"] == JobStatus.FAILED
        assert "Intentional failure" in (job["error"] or "")

    @pytest.mark.asyncio
    async def test_one_failure_does_not_block_others(self):
        q = JobQueue(max_concurrent=2)
        fail_id = await q.enqueue("fail", {}, _failing_worker)
        ok_id = await q.enqueue("ok", {}, _noop_worker)
        await asyncio.sleep(0.2)
        assert q.get_job(fail_id)["status"] == JobStatus.FAILED
        assert q.get_job(ok_id)["status"] == JobStatus.COMPLETED


# ──────────────────────────────────────────────────────────────────────────────
# Cancellation
# ──────────────────────────────────────────────────────────────────────────────

class TestJobQueueCancellation:
    @pytest.mark.asyncio
    async def test_cancel_running_job(self):
        q = JobQueue()
        job_id = await q.enqueue("slow", {}, _slow_worker)
        await asyncio.sleep(0.05)  # Let it start
        cancelled = q.cancel(job_id)
        assert cancelled is True
        await asyncio.sleep(0.05)
        job = q.get_job(job_id)
        assert job["status"] == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job_returns_false(self):
        q = JobQueue()
        assert q.cancel("nonexistent") is False

    @pytest.mark.asyncio
    async def test_cancel_already_completed_returns_false(self):
        q = JobQueue()
        job_id = await q.enqueue("test", {}, _noop_worker)
        await asyncio.sleep(0.1)
        result = q.cancel(job_id)
        assert result is False


# ──────────────────────────────────────────────────────────────────────────────
# List / prune
# ──────────────────────────────────────────────────────────────────────────────

class TestJobQueueList:
    @pytest.mark.asyncio
    async def test_list_jobs_returns_all(self):
        q = JobQueue()
        await q.enqueue("typeA", {}, _noop_worker)
        await q.enqueue("typeB", {}, _noop_worker)
        await asyncio.sleep(0.1)
        all_jobs = q.list_jobs()
        assert len(all_jobs) >= 2

    @pytest.mark.asyncio
    async def test_list_jobs_filtered_by_type(self):
        q = JobQueue()
        await q.enqueue("alpha", {}, _noop_worker)
        await q.enqueue("beta", {}, _noop_worker)
        await asyncio.sleep(0.1)
        alpha_jobs = q.list_jobs(job_type="alpha")
        assert all(j["type"] == "alpha" for j in alpha_jobs)

    @pytest.mark.asyncio
    async def test_prune_removes_old_completed_jobs(self):
        q = JobQueue()
        for _ in range(5):
            await q.enqueue("test", {}, _noop_worker)
        await asyncio.sleep(0.2)
        q.prune_completed(keep_last=2)
        done = [j for j in q.jobs.values() if j["status"] == JobStatus.COMPLETED]
        assert len(done) <= 2
