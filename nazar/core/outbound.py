"""
Nazar — Outbound Messaging Module

Handles sending messages from the dashboard:
1. Single message send (human agent → customer via WhatsApp)
2. Campaign send (to segments with personalization via templates)
3. Template-based sends (pre-approved WhatsApp templates)
4. Rate limiting & delivery tracking

This module is called by server.py's API endpoints.
The actual WhatsApp API calls are in server.py — this module
handles the business logic layer: personalization, batching,
rate limiting, logging.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable, List

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"



def _campaigns_path() -> Path:
    """Path to the campaigns log file."""
    return DATA_DIR / "campaigns.json"


def _load_campaigns() -> list:
    """Load campaign history."""
    path = _campaigns_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_campaigns(campaigns: list):
    """Save campaign history."""
    path = _campaigns_path()
    path.write_text(json.dumps(campaigns, ensure_ascii=False, indent=2), encoding="utf-8")



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
    """
    Create a campaign record with full analytics tracking.

    Args:
        reply_mode: How replies to this campaign are handled.
            "auto_ai"    - AI replies automatically
            "human_only" - Only human agents reply
            "ai_draft"   - AI drafts reply, human approves
        campaign_kb: Campaign-specific knowledge base text.

    Returns the campaign record.
    """
    now = datetime.now(IST).isoformat()
    record = {
        "id": f"cmp_{uuid.uuid4().hex[:8]}",
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

    campaigns = _load_campaigns()
    campaigns.insert(0, record)
    campaigns = campaigns[:200]
    _save_campaigns(campaigns)

    logger.info(
        f"Campaign created: {name} — {sent}/{target_count} sent, "
        f"template={template_name}"
    )
    return record


def get_campaign(campaign_id: str) -> Optional[dict]:
    """Get a campaign by ID."""
    campaigns = _load_campaigns()
    for c in campaigns:
        if c["id"] == campaign_id:
            return c
    return None


def update_campaign(campaign_id: str, **fields) -> Optional[dict]:
    """Update a campaign record."""
    campaigns = _load_campaigns()
    for i, c in enumerate(campaigns):
        if c["id"] == campaign_id:
            c.update(fields)
            campaigns[i] = c
            _save_campaigns(campaigns)
            return c
    return None


def get_campaign_history(limit: int = 50) -> list:
    """Get campaign history, newest first."""
    campaigns = _load_campaigns()
    return campaigns[:limit]


def get_campaign_stats() -> dict:
    """Get aggregate campaign statistics."""
    campaigns = _load_campaigns()
    total_sent = sum(c.get("sent", 0) for c in campaigns)
    total_delivered = sum(c.get("delivered", 0) for c in campaigns)
    total_read = sum(c.get("read", 0) for c in campaigns)
    total_replied = sum(c.get("replied", 0) for c in campaigns)
    total_failed = sum(c.get("failed", 0) for c in campaigns)
    total_targeted = sum(c.get("target_count", 0) for c in campaigns)

    return {
        "total_campaigns": len(campaigns),
        "total_recipients": total_targeted,
        "total_sent": total_sent,
        "total_delivered": total_delivered,
        "total_read": total_read,
        "total_replied": total_replied,
        "total_failed": total_failed,
        "delivery_rate": round(total_delivered / max(total_sent, 1) * 100, 1),
        "read_rate": round(total_read / max(total_delivered, 1) * 100, 1),
        "reply_rate": round(total_replied / max(total_delivered, 1) * 100, 1),
    }



# ---------------------------------------------------------------------------
# Message personalization
# ---------------------------------------------------------------------------

def personalize_message(
    template: str,
    contact: dict,
    memory_summary: Optional[dict] = None,
) -> str:
    """
    Personalize a campaign message template with contact data.

    Supported variables:
      {name}     — contact name
      {company}  — company name
      {stage}    — pipeline stage
      {phone}    — phone number

    Args:
        template: Message template with {variables}.
        contact: Contact profile dict.
        memory_summary: Optional memory summary for AI personalization.

    Returns:
        Personalized message string.
    """
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
    """
    Execute a campaign send to a list of contacts.

    Args:
        contacts: List of contact profile dicts to send to.
        message: Message text (may contain {variables}).
        send_fn: Async callable(phone, text) that sends a WhatsApp message.
        template_name: Optional template name (for logging).
        filter_stage: Stage filter used (for logging).
        filter_tag: Tag filter used (for logging).
        personalize: Whether to apply personalization.
        rate_limit_ms: Delay between sends in milliseconds.

    Returns:
        Result dict with sent/failed counts and per-contact details.
    """
    results = {
        "sent": 0,
        "failed": 0,
        "details": [],
    }

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

        # Personalize message
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

        # Rate limiting
        if rate_limit_ms > 0:
            await asyncio.sleep(rate_limit_ms / 1000)

    return results


# ---------------------------------------------------------------------------
# Follow-up message generation
# ---------------------------------------------------------------------------

def generate_followup_context(contact: dict, memory_summary: Optional[dict] = None) -> str:
    """
    Generate context for an AI-powered follow-up message.

    Returns a prompt string that can be sent to the LLM to generate
    a personalized follow-up.
    """
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
