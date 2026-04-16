"""
Nazar — Outbound Messaging Module

Handles campaign CRUD, personalization, and execution logic.
Storage: SQLite via core/database.py
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable, List

from database import get_db, row_to_dict, rows_to_list

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Campaign CRUD
# ---------------------------------------------------------------------------

def create_campaign(
    name: str,
    template_id: str,
    template_name: str,
    target_count: int,
    sent: int = 0,
    failed: int = 0,
    delivered: int = 0,
    read: int = 0,
    replied: int = 0,
    filter_stage: Optional[str] = None,
    filter_tag: Optional[str] = None,
    contact_ids: Optional[list] = None,
    scheduled_at: Optional[str] = None,
    reply_mode: str = "auto_ai",
    campaign_kb: str = "",
) -> dict:
    """Create a campaign record with full analytics tracking."""
    now = datetime.now(IST).isoformat()
    campaign_id = f"cmp_{uuid.uuid4().hex[:8]}"

    record = {
        "id": campaign_id,
        "name": name,
        "template_id": template_id,
        "template_name": template_name,
        "target_count": target_count,
        "sent": sent,
        "failed": failed,
        "delivered": delivered,
        "read": read,
        "replied": replied,
        "not_on_whatsapp": 0,
        "filter_stage": filter_stage or "",
        "filter_tag": filter_tag or "",
        "contact_ids": contact_ids or [],
        "reply_mode": reply_mode,
        "campaign_kb": bool(campaign_kb),
        "status": "completed" if not scheduled_at else "scheduled",
        "scheduled_at": scheduled_at or "",
        "created_at": now,
        "completed_at": now if not scheduled_at else "",
    }

    with get_db() as conn:
        conn.execute(
            """INSERT INTO campaigns
               (id, name, template_id, template_name, target_count,
                sent, failed, delivered, read_count, replied, not_on_whatsapp,
                filter_stage, filter_tag, contact_ids, reply_mode, campaign_kb,
                status, scheduled_at, created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                campaign_id, name, template_id, template_name, target_count,
                sent, failed, delivered, read, replied, 0,
                filter_stage or "", filter_tag or "",
                json.dumps(contact_ids or []), reply_mode,
                1 if campaign_kb else 0,
                "completed" if not scheduled_at else "scheduled",
                scheduled_at or "", now, now if not scheduled_at else "",
            ),
        )

    logger.info(
        "Campaign created: %s — %d/%d sent, template=%s",
        name, sent, target_count, template_name,
    )
    return record


def get_campaign(campaign_id: str) -> Optional[dict]:
    """Get a campaign by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
    if not row:
        return None
    return _row_to_campaign(row)


def update_campaign(campaign_id: str, updates=None, **fields) -> Optional[dict]:
    """Update a campaign record. Accepts a dict or kwargs."""
    if updates and isinstance(updates, dict):
        fields.update(updates)

    col_map = {
        "name": "name", "status": "status", "sent": "sent",
        "failed": "failed", "delivered": "delivered",
        "read": "read_count", "replied": "replied",
        "scheduled_at": "scheduled_at", "completed_at": "completed_at",
    }

    sets = []
    vals = []
    for k, v in fields.items():
        col = col_map.get(k, k)
        # Only update known columns
        if col in ("name", "status", "sent", "failed", "delivered",
                    "read_count", "replied", "scheduled_at", "completed_at"):
            sets.append(f"{col} = ?")
            vals.append(v)

    if not sets:
        return get_campaign(campaign_id)

    vals.append(campaign_id)

    with get_db() as conn:
        conn.execute(
            f"UPDATE campaigns SET {', '.join(sets)} WHERE id = ?",
            vals,
        )

    return get_campaign(campaign_id)


def get_campaign_history(limit: int = 50) -> list:
    """Get campaign history, newest first."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM campaigns ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_campaign(r) for r in rows]


def get_campaign_stats() -> dict:
    """Get aggregate campaign statistics."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT
                 COUNT(*) as total_campaigns,
                 COALESCE(SUM(target_count), 0) as total_recipients,
                 COALESCE(SUM(sent), 0) as total_sent,
                 COALESCE(SUM(delivered), 0) as total_delivered,
                 COALESCE(SUM(read_count), 0) as total_read,
                 COALESCE(SUM(replied), 0) as total_replied,
                 COALESCE(SUM(failed), 0) as total_failed
               FROM campaigns"""
        ).fetchone()

    d = dict(row)
    total_sent = d["total_sent"] or 1
    total_delivered = d["total_delivered"] or 1

    return {
        "total_campaigns": d["total_campaigns"],
        "total_recipients": d["total_recipients"],
        "total_sent": d["total_sent"],
        "total_delivered": d["total_delivered"],
        "total_read": d["total_read"],
        "total_replied": d["total_replied"],
        "total_failed": d["total_failed"],
        "delivery_rate": round((d["total_delivered"] or 0) / max(total_sent, 1) * 100, 1),
        "read_rate": round((d["total_read"] or 0) / max(total_delivered, 1) * 100, 1),
        "reply_rate": round((d["total_replied"] or 0) / max(total_delivered, 1) * 100, 1),
    }


# ---------------------------------------------------------------------------
# Message personalization
# ---------------------------------------------------------------------------

def personalize_message(
    template: str,
    contact: dict,
    memory_summary: Optional[dict] = None,
) -> str:
    """Personalize a campaign message template with contact data."""
    name = contact.get("name", "there")
    if not name or name.strip() == "":
        name = "there"

    message = template.replace("{name}", name)
    message = message.replace("{company}", contact.get("company") or "your company")
    message = message.replace("{stage}", contact.get("pipeline_stage") or "")
    message = message.replace("{phone}", contact.get("phone") or "")

    return message


# ---------------------------------------------------------------------------
# Campaign execution
# ---------------------------------------------------------------------------

async def execute_campaign_send(
    contacts: List[dict],
    message: str,
    send_fn: Callable,
    template_name: str = "",
    filter_stage: Optional[str] = None,
    filter_tag: Optional[str] = None,
    personalize: bool = True,
    rate_limit_ms: int = 100,
) -> dict:
    """Execute a campaign send to a list of contacts."""
    results = {"sent": 0, "failed": 0, "details": []}

    for contact in contacts:
        phone = contact.get("phone", "")
        if not phone:
            results["failed"] += 1
            results["details"].append({
                "contact_id": contact.get("contact_id"),
                "phone": "",
                "status": "failed",
                "error": "No phone number",
            })
            continue

        text = personalize_message(message, contact) if personalize else message

        try:
            await send_fn(phone, text)
            results["sent"] += 1
            results["details"].append({
                "contact_id": contact.get("contact_id"),
                "phone": phone,
                "status": "sent",
                "message": text[:100],
            })
        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "contact_id": contact.get("contact_id"),
                "phone": phone,
                "status": "failed",
                "error": str(e)[:200],
            })

        if rate_limit_ms > 0:
            await asyncio.sleep(rate_limit_ms / 1000)

    return results


# ---------------------------------------------------------------------------
# Follow-up context
# ---------------------------------------------------------------------------

def generate_followup_context(contact: dict, memory_summary: Optional[dict] = None) -> str:
    """Generate context for an AI-powered follow-up message."""
    name = contact.get("name", "the customer")
    stage = contact.get("pipeline_stage", "New")
    deal_value = contact.get("deal_value", 0)
    last_contact = contact.get("last_contacted_at") or contact.get("last_replied_at") or ""
    notes = contact.get("notes", "")

    context = f"""Generate a brief, warm WhatsApp follow-up message for:
- Customer: {name}
- Pipeline Stage: {stage}
- Deal Value: ₹{deal_value:,.0f}
- Last Contact: {last_contact or 'Unknown'}
- Notes: {notes or 'None'}
"""

    if memory_summary:
        signals = memory_summary.get("signal_counts", {})
        if signals:
            context += f"\nDetected signals: {json.dumps(signals)}"
        total = memory_summary.get("total_embeddings", 0)
        if total:
            context += f"\nTotal conversation memories: {total}"

    context += """
\nRules:
- Keep it under 3 sentences
- Reference something specific from history if possible
- Don't be pushy — be genuinely helpful
- Match the customer's language preference
- End with an open question that invites response"""

    return context


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_campaign(row) -> dict:
    """Convert a sqlite3.Row to a campaign dict."""
    d = dict(row)
    return {
        "id": d["id"],
        "name": d["name"],
        "template_id": d.get("template_id", ""),
        "template_name": d.get("template_name", ""),
        "target_count": d.get("target_count", 0),
        "sent": d.get("sent", 0),
        "failed": d.get("failed", 0),
        "delivered": d.get("delivered", 0),
        "read": d.get("read_count", 0),
        "replied": d.get("replied", 0),
        "not_on_whatsapp": d.get("not_on_whatsapp", 0),
        "filter_stage": d.get("filter_stage", ""),
        "filter_tag": d.get("filter_tag", ""),
        "contact_ids": json.loads(d.get("contact_ids", "[]") or "[]"),
        "reply_mode": d.get("reply_mode", "auto_ai"),
        "campaign_kb": bool(d.get("campaign_kb", 0)),
        "status": d.get("status", "completed"),
        "scheduled_at": d.get("scheduled_at", ""),
        "created_at": d.get("created_at", ""),
        "completed_at": d.get("completed_at", ""),
    }
