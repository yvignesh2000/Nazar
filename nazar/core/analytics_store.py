"""
Operational analytics for team inbox and CRM health.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from contact_manager import get_conversation_metrics
from db import (
    AuditEvent,
    Conversation,
    ConversationMessage,
    Workspace,
    default_workspace_slug,
    init_db,
    session_scope,
)

UTC = timezone.utc


def _workspace(session) -> Workspace:
    workspace = session.execute(
        select(Workspace).where(Workspace.slug == default_workspace_slug())
    ).scalar_one_or_none()
    if workspace is None:
        workspace = session.execute(select(Workspace)).scalar_one()
    return workspace


def _parse_details(raw: str) -> dict:
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def get_operational_metrics(days: int = 30) -> dict:
    init_db()
    since = datetime.now(UTC) - timedelta(days=max(1, int(days)))
    conversation_metrics = get_conversation_metrics()

    with session_scope() as session:
        workspace = _workspace(session)
        inbound_conversations = session.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == workspace.id,
                Conversation.last_inbound_at.is_not(None),
                Conversation.last_inbound_at >= since,
            )
            .order_by(Conversation.last_inbound_at.desc())
        ).scalars().all()
        audit_events = session.execute(
            select(AuditEvent)
            .where(
                AuditEvent.workspace_id == workspace.id,
                AuditEvent.created_at >= since,
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        ).scalars().all()
        queue_rows = session.execute(
            select(Conversation.human_queue, func.count())
            .where(Conversation.workspace_id == workspace.id)
            .group_by(Conversation.human_queue)
        ).all()
        source_rows = session.execute(
            select(Conversation.source_type, func.count())
            .where(Conversation.workspace_id == workspace.id)
            .group_by(Conversation.source_type)
        ).all()
        ai_assist_available = session.execute(
            select(func.count()).select_from(Conversation).where(
                Conversation.workspace_id == workspace.id,
                Conversation.ai_assist_status == "available",
            )
        ).scalar_one()
        campaign_reply_conversations = session.execute(
            select(func.count()).select_from(Conversation).where(
                Conversation.workspace_id == workspace.id,
                Conversation.source_type == "campaign",
                Conversation.last_inbound_at.is_not(None),
                Conversation.last_inbound_at >= since,
            )
        ).scalar_one()
        bot_outbound_count = session.execute(
            select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.workspace_id == workspace.id,
                ConversationMessage.direction == "outbound",
                ConversationMessage.sent_by.in_(["bot", "broadcast"]),
                ConversationMessage.timestamp >= since,
            )
        ).scalar_one()
        human_outbound_count = session.execute(
            select(func.count()).select_from(ConversationMessage).where(
                ConversationMessage.workspace_id == workspace.id,
                ConversationMessage.direction == "outbound",
                ConversationMessage.sent_by.in_(["human", "human_ai_assist"]),
                ConversationMessage.timestamp >= since,
            )
        ).scalar_one()

    handoff_count = 0
    stage_movement_count = 0
    assignment_count = 0
    for event in audit_events:
        details = _parse_details(event.details_json)
        if event.action == "stage_changed":
            stage_movement_count += 1
        elif event.action == "assigned":
            assignment_count += 1
        elif event.action == "bot_mode_changed" and details.get("bot_mode") is False:
            handoff_count += 1

    queue_counts = {
        (queue or "unrouted"): int(count or 0)
        for queue, count in queue_rows
    }
    source_counts = {
        (source or "unknown"): int(count or 0)
        for source, count in source_rows
    }

    return {
        "window_days": max(1, int(days)),
        "inbound_conversations": len(inbound_conversations),
        "unassigned_conversations": conversation_metrics["unassigned_conversations"],
        "needs_reply": conversation_metrics["needs_reply"],
        "handoff_count": handoff_count,
        "assignment_count": assignment_count,
        "stage_movement_count": stage_movement_count,
        "campaign_reply_conversations": int(campaign_reply_conversations or 0),
        "ai_assist_available": int(ai_assist_available or 0),
        "bot_outbound_count": int(bot_outbound_count or 0),
        "human_outbound_count": int(human_outbound_count or 0),
        "queue_counts": queue_counts,
        "source_counts": source_counts,
        "avg_response_seconds": conversation_metrics["avg_response_seconds"],
        "sent_messages": conversation_metrics["sent_messages"],
        "delivered_messages": conversation_metrics["delivered_messages"],
        "read_messages": conversation_metrics["read_messages"],
        "status_counts": conversation_metrics["status_counts"],
        "total_conversations": conversation_metrics["total_conversations"],
    }
