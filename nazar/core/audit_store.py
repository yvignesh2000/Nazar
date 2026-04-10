"""
Audit log storage for workspace actions.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select

from db import AuditEvent, Workspace, default_workspace_slug, init_db, session_scope


def _workspace(session) -> Workspace:
    workspace = session.execute(
        select(Workspace).where(Workspace.slug == default_workspace_slug())
    ).scalar_one_or_none()
    if workspace is None:
        workspace = session.execute(select(Workspace)).scalar_one()
    return workspace


def record_audit_event(
    entity_type: str,
    entity_id: str,
    action: str,
    details: Optional[dict] = None,
    actor_user_id: Optional[str] = None,
) -> dict:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session)
        event = AuditEvent(
            workspace_id=workspace.id,
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            details_json=json.dumps(details or {}, ensure_ascii=False),
        )
        session.add(event)
        session.flush()
        return {
            "id": event.id,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "action": event.action,
            "details": json.loads(event.details_json),
            "created_at": event.created_at.isoformat(),
        }


def list_audit_events(entity_type: Optional[str] = None, entity_id: Optional[str] = None, limit: int = 100) -> list:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session)
        query = select(AuditEvent).where(AuditEvent.workspace_id == workspace.id)
        if entity_type:
            query = query.where(AuditEvent.entity_type == entity_type)
        if entity_id:
            query = query.where(AuditEvent.entity_id == entity_id)
        events = session.execute(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(max(1, min(limit, 500)))
        ).scalars().all()
        return [
            {
                "id": event.id,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "action": event.action,
                "details": json.loads(event.details_json or "{}"),
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ]
