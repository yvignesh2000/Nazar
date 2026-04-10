"""
Persistent background job queue with optional Redis notifications.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from db import BackgroundJob, Workspace, default_workspace_slug, init_db, session_scope

try:
    import redis
except Exception:
    redis = None

UTC = timezone.utc
JOB_STATUSES = {"queued", "processing", "completed", "failed"}
REDIS_CHANNEL = "nazar_jobs"


def _now() -> datetime:
    return datetime.now(UTC)


def _workspace(session) -> Workspace:
    workspace = session.execute(
        select(Workspace).where(Workspace.slug == default_workspace_slug())
    ).scalar_one_or_none()
    if workspace is None:
        workspace = session.execute(select(Workspace)).scalar_one()
    return workspace


def _json_load(raw: str, fallback):
    try:
        return json.loads(raw or "")
    except Exception:
        return fallback


def _serialize_job(job: BackgroundJob) -> dict:
    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "requested_by_user_id": job.requested_by_user_id,
        "kind": job.kind,
        "status": job.status,
        "payload": _json_load(job.payload_json, {}),
        "result": _json_load(job.result_json, {}),
        "error": job.error_text,
        "attempts": int(job.attempts or 0),
        "max_attempts": int(job.max_attempts or 0),
        "available_at": job.available_at.isoformat() if job.available_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "failed_at": job.failed_at.isoformat() if job.failed_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _redis_client():
    if redis is None:
        return None
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if not redis_url:
        return None
    try:
        return redis.from_url(redis_url, decode_responses=True)
    except Exception:
        return None


def _publish_job_available(job: BackgroundJob) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        client.publish(REDIS_CHANNEL, job.id)
    except Exception:
        return


def enqueue_job(
    kind: str,
    payload: dict,
    requested_by_user_id: Optional[str] = None,
    max_attempts: int = 5,
    available_at: Optional[datetime] = None,
) -> dict:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session)
        job = BackgroundJob(
            workspace_id=workspace.id,
            requested_by_user_id=requested_by_user_id,
            kind=kind,
            status="queued",
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
            result_json="{}",
            max_attempts=max(1, int(max_attempts or 1)),
            available_at=available_at or _now(),
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(job)
        session.flush()
        serialized = _serialize_job(job)
        _publish_job_available(job)
        return serialized


def get_job(job_id: str) -> Optional[dict]:
    init_db()
    with session_scope() as session:
        job = session.execute(select(BackgroundJob).where(BackgroundJob.id == job_id)).scalar_one_or_none()
        return _serialize_job(job) if job else None


def list_jobs(kind: Optional[str] = None, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session)
        query = select(BackgroundJob).where(BackgroundJob.workspace_id == workspace.id)
        if kind:
            query = query.where(BackgroundJob.kind == kind)
        if status:
            query = query.where(BackgroundJob.status == status)
        jobs = session.execute(
            query.order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc()).limit(max(1, min(limit, 200)))
        ).scalars().all()
        return [_serialize_job(job) for job in jobs]


def claim_due_jobs(kinds: Optional[list[str]] = None, limit: int = 10) -> list[dict]:
    init_db()
    now = _now()
    with session_scope() as session:
        workspace = _workspace(session)
        query = (
            select(BackgroundJob)
            .where(
                BackgroundJob.workspace_id == workspace.id,
                BackgroundJob.status == "queued",
                BackgroundJob.available_at <= now,
            )
            .order_by(BackgroundJob.available_at.asc(), BackgroundJob.created_at.asc(), BackgroundJob.id.asc())
            .limit(max(1, min(limit, 100)))
        )
        if kinds:
            query = query.where(BackgroundJob.kind.in_(kinds))
        jobs = session.execute(query).scalars().all()
        for job in jobs:
            job.status = "processing"
            job.attempts = int(job.attempts or 0) + 1
            job.started_at = now
            job.updated_at = now
        session.flush()
        return [_serialize_job(job) for job in jobs]


def complete_job(job_id: str, result: Optional[dict] = None) -> Optional[dict]:
    init_db()
    now = _now()
    with session_scope() as session:
        job = session.execute(select(BackgroundJob).where(BackgroundJob.id == job_id)).scalar_one_or_none()
        if job is None:
            return None
        job.status = "completed"
        job.result_json = json.dumps(result or {}, ensure_ascii=False)
        job.completed_at = now
        job.updated_at = now
        session.flush()
        return _serialize_job(job)


def fail_job(job_id: str, error: str, retry_delay_seconds: Optional[int] = None) -> Optional[dict]:
    init_db()
    now = _now()
    with session_scope() as session:
        job = session.execute(select(BackgroundJob).where(BackgroundJob.id == job_id)).scalar_one_or_none()
        if job is None:
            return None
        should_retry = retry_delay_seconds is not None and int(job.attempts or 0) < int(job.max_attempts or 1)
        job.error_text = error[:4000]
        job.updated_at = now
        if should_retry:
            job.status = "queued"
            job.available_at = now + timedelta(seconds=max(1, int(retry_delay_seconds)))
        else:
            job.status = "failed"
            job.failed_at = now
        session.flush()
        return _serialize_job(job)
