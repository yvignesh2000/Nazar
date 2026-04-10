"""
Nazar — WhatsApp Template Manager

Database-backed template library with legacy file import on first boot.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from db import TemplateRecord, Workspace, default_workspace_slug, init_db, session_scope

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"
LEGACY_TEMPLATES_PATH = DATA_DIR / "templates.json"

TEMPLATE_CATEGORIES = ["marketing", "utility", "authentication"]

DEFAULT_TEMPLATES = [
    {
        "id": "tpl_welcome",
        "name": "welcome_new_lead",
        "category": "utility",
        "body": "Hi {{1}}! Thanks for your interest in our services. I'm here to help you find the right solution. What are you looking for?",
        "variables": ["name"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "description": "Welcome message for new leads",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_followup",
        "name": "gentle_followup",
        "category": "utility",
        "body": "Hi {{1}}, just checking in! We discussed {{2}} recently. Do you have any questions or would you like to proceed?",
        "variables": ["name", "topic"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "description": "Gentle follow-up for warm leads",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_demo_invite",
        "name": "demo_invitation",
        "category": "utility",
        "body": "Hi {{1}}! Based on our conversation, I think a quick demo would help. Would you like to schedule a 15-minute walkthrough? I'm available this week.",
        "variables": ["name"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "description": "Demo invitation for interested leads",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_proposal",
        "name": "proposal_sent",
        "category": "utility",
        "body": "Hi {{1}}, I've prepared a proposal for {{2}} based on your requirements. Would you like me to walk you through it or shall I send it over?",
        "variables": ["name", "company"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "description": "Notify about proposal readiness",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_seasonal",
        "name": "seasonal_greeting",
        "category": "marketing",
        "body": "Hi {{1}}! Wishing you a wonderful season ahead. We have some exciting updates we'd love to share. Can I tell you more?",
        "variables": ["name"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "description": "Seasonal/festive re-engagement",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_feedback",
        "name": "feedback_request",
        "category": "utility",
        "body": "Hi {{1}}! It's been a while since we connected. How's everything going? We'd love to hear your feedback and see if there's anything we can help with.",
        "variables": ["name"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "description": "Feedback request for won customers",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_hindi_welcome",
        "name": "welcome_hindi",
        "category": "utility",
        "body": "नमस्ते {{1}}! हमारी सर्विसेज में आपकी रुचि के लिए धन्यवाद। मैं आपकी सही समाधान खोजने में मदद करने के लिए यहाँ हूँ। आपको क्या चाहिए?",
        "variables": ["name"],
        "language": "hi",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "description": "Hindi welcome message",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
    {
        "id": "tpl_reengagement",
        "name": "win_back",
        "category": "marketing",
        "body": "Hi {{1}}, we haven't heard from you in a while! We've made some improvements since we last spoke. Would you be open to a quick catch-up?",
        "variables": ["name"],
        "language": "en",
        "approval_status": "approved",
        "usage_count": 0,
        "reply_rate": 0.0,
        "description": "Win-back for dormant contacts",
        "created_at": "2026-01-15T10:00:00+05:30",
        "updated_at": "2026-01-15T10:00:00+05:30",
    },
]

_initialized = False


def _workspace(session) -> Workspace:
    workspace = session.execute(
        select(Workspace).where(Workspace.slug == default_workspace_slug())
    ).scalar_one_or_none()
    if workspace is None:
        workspace = session.execute(select(Workspace)).scalar_one()
    return workspace


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)


def _serialize_template(record: TemplateRecord) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "category": record.category,
        "body": record.body,
        "variables": json.loads(record.variables_json or "[]"),
        "language": record.language,
        "approval_status": record.approval_status,
        "usage_count": int(record.usage_count or 0),
        "reply_rate": float(record.reply_rate or 0.0),
        "description": record.description or "",
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def _seed_templates(session, workspace_id: str, templates: list[dict]) -> None:
    for template in templates:
        session.add(
            TemplateRecord(
                id=template["id"],
                workspace_id=workspace_id,
                name=template["name"],
                category=template["category"],
                body=template["body"],
                variables_json=json.dumps(template.get("variables", []), ensure_ascii=False),
                language=template.get("language", "en"),
                approval_status=template.get("approval_status", "pending"),
                usage_count=int(template.get("usage_count", 0)),
                reply_rate=float(template.get("reply_rate", 0.0)),
                description=template.get("description", ""),
                created_at=_parse_ts(template.get("created_at", datetime.now(IST).isoformat())),
                updated_at=_parse_ts(template.get("updated_at", datetime.now(IST).isoformat())),
            )
        )


def initialize_template_store() -> None:
    global _initialized
    if _initialized:
        return
    init_db()
    with session_scope() as session:
        workspace = _workspace(session)
        existing = session.execute(
            select(TemplateRecord).where(TemplateRecord.workspace_id == workspace.id)
        ).scalars().first()
        if existing is None:
            templates = DEFAULT_TEMPLATES
            if LEGACY_TEMPLATES_PATH.exists():
                try:
                    templates = json.loads(LEGACY_TEMPLATES_PATH.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning(f"Failed to import legacy templates: {exc}")
            _seed_templates(session, workspace.id, templates)
    _initialized = True


def list_templates(category: Optional[str] = None, status: Optional[str] = None) -> list:
    initialize_template_store()
    with session_scope() as session:
        workspace = _workspace(session)
        query = select(TemplateRecord).where(TemplateRecord.workspace_id == workspace.id)
        if category:
            query = query.where(TemplateRecord.category == category)
        if status:
            query = query.where(TemplateRecord.approval_status == status)
        records = session.execute(query.order_by(TemplateRecord.created_at.asc())).scalars().all()
        return [_serialize_template(record) for record in records]


def get_template(template_id: str) -> Optional[dict]:
    initialize_template_store()
    with session_scope() as session:
        record = session.execute(select(TemplateRecord).where(TemplateRecord.id == template_id)).scalar_one_or_none()
        return _serialize_template(record) if record else None


def get_template_by_name(name: str) -> Optional[dict]:
    initialize_template_store()
    with session_scope() as session:
        workspace = _workspace(session)
        record = session.execute(
            select(TemplateRecord).where(TemplateRecord.workspace_id == workspace.id, TemplateRecord.name == name)
        ).scalar_one_or_none()
        return _serialize_template(record) if record else None


def create_template(
    name: str,
    body: str,
    category: str = "utility",
    variables: Optional[list] = None,
    language: str = "en",
    description: str = "",
) -> dict:
    initialize_template_store()
    if category not in TEMPLATE_CATEGORIES:
        raise ValueError(f"Invalid category '{category}'. Must be one of: {TEMPLATE_CATEGORIES}")

    with session_scope() as session:
        workspace = _workspace(session)
        existing = session.execute(
            select(TemplateRecord).where(TemplateRecord.workspace_id == workspace.id, TemplateRecord.name == name)
        ).scalar_one_or_none()
        if existing is not None:
            raise ValueError(f"Template with name '{name}' already exists")

        now = datetime.now(IST)
        record = TemplateRecord(
            id=f"tpl_{uuid.uuid4().hex[:8]}",
            workspace_id=workspace.id,
            name=name,
            category=category,
            body=body,
            variables_json=json.dumps(variables or [], ensure_ascii=False),
            language=language,
            approval_status="pending",
            usage_count=0,
            reply_rate=0.0,
            description=description,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        session.flush()
        logger.info(f"Template created: {name} (id={record.id})")
        return _serialize_template(record)


def update_template(template_id: str, **fields) -> dict:
    initialize_template_store()
    with session_scope() as session:
        record = session.execute(select(TemplateRecord).where(TemplateRecord.id == template_id)).scalar_one_or_none()
        if record is None:
            raise ValueError(f"Template '{template_id}' not found")

        if "category" in fields and fields["category"] not in TEMPLATE_CATEGORIES:
            raise ValueError(f"Invalid category. Must be one of: {TEMPLATE_CATEGORIES}")

        for key in ("name", "category", "body", "language", "approval_status", "description"):
            if key in fields:
                setattr(record, key, fields[key])
        if "variables" in fields:
            record.variables_json = json.dumps(fields["variables"] or [], ensure_ascii=False)
        if "usage_count" in fields:
            record.usage_count = int(fields["usage_count"] or 0)
        if "reply_rate" in fields:
            record.reply_rate = float(fields["reply_rate"] or 0.0)
        record.updated_at = datetime.now(IST)
        session.flush()
        logger.info(f"Template updated: {record.name} ({template_id})")
        return _serialize_template(record)


def delete_template(template_id: str):
    initialize_template_store()
    with session_scope() as session:
        record = session.execute(select(TemplateRecord).where(TemplateRecord.id == template_id)).scalar_one_or_none()
        if record is not None:
            session.delete(record)
            logger.info(f"Template deleted: {template_id}")


def increment_usage(template_id: str):
    initialize_template_store()
    with session_scope() as session:
        record = session.execute(select(TemplateRecord).where(TemplateRecord.id == template_id)).scalar_one_or_none()
        if record is not None:
            record.usage_count = int(record.usage_count or 0) + 1
            record.updated_at = datetime.now(IST)


def render_template(template: dict, contact: dict) -> str:
    body = template.get("body", "")
    variables = template.get("variables", [])
    var_map = {
        "name": contact.get("name") or "there",
        "company": contact.get("company") or "your company",
        "phone": contact.get("phone") or "",
        "stage": contact.get("pipeline_stage") or "",
        "deal_value": f"₹{contact.get('deal_value', 0):,.0f}",
        "topic": contact.get("notes") or "our discussion",
    }
    for index, var_name in enumerate(variables, start=1):
        body = body.replace("{{" + str(index) + "}}", var_map.get(var_name, ""))
    return body


def suggest_template(contact: dict, memory_summary: Optional[dict] = None) -> Optional[dict]:
    stage = contact.get("pipeline_stage", "New")
    approved = [template for template in list_templates(status="approved") if template.get("approval_status") == "approved"]
    if not approved:
        return None

    stage_suggestions = {
        "New": ["welcome_new_lead", "welcome_hindi"],
        "Qualified": ["demo_invitation", "gentle_followup"],
        "Proposal": ["proposal_sent", "gentle_followup"],
        "Negotiation": ["gentle_followup", "demo_invitation"],
        "Won": ["feedback_request", "seasonal_greeting"],
        "Lost": ["win_back", "seasonal_greeting"],
    }

    for name in stage_suggestions.get(stage, ["gentle_followup"]):
        for template in approved:
            if template["name"] == name:
                return template
    return approved[0]


def get_template_stats() -> dict:
    templates = list_templates()
    return {
        "total": len(templates),
        "approved": len([template for template in templates if template.get("approval_status") == "approved"]),
        "pending": len([template for template in templates if template.get("approval_status") == "pending"]),
        "rejected": len([template for template in templates if template.get("approval_status") == "rejected"]),
        "total_usage": sum(template.get("usage_count", 0) for template in templates),
        "categories": {
            category: len([template for template in templates if template.get("category") == category])
            for category in TEMPLATE_CATEGORIES
        },
    }
