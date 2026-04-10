"""
Nazar — Outbound Messaging Module

Handles sending messages from the dashboard:
1. Single message send (human agent → customer via WhatsApp)
2. Broadcast send (to segments with personalization)
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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable, List

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Broadcast history storage
# ---------------------------------------------------------------------------

def _broadcasts_path() -> Path:
    """Path to the broadcasts log file."""
    return DATA_DIR / "broadcasts.json"


def _load_broadcasts() -> list:
    """Load broadcast history."""
    path = _broadcasts_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_broadcasts(broadcasts: list):
    """Save broadcast history."""
    path = _broadcasts_path()
    path.write_text(json.dumps(broadcasts, ensure_ascii=False, indent=2), encoding="utf-8")


def log_broadcast(
    message: str,
    template_name: str,
    target_count: int,
    sent: int,
    failed: int,
    filter_stage: Optional[str] = None,
    filter_tag: Optional[str] = None,
    campaign_key: Optional[str] = None,
) -> dict:
    """
    Log a broadcast send for history and analytics.

    Returns the broadcast record.
    """
    now = datetime.now(IST).isoformat()
    record = {
        "id": f"bc_{int(datetime.now(IST).timestamp())}",
        "message": message[:500] if message else "",
        "template": template_name or "",
        "target_count": target_count,
        "sent": sent,
        "failed": failed,
        "filter_stage": filter_stage,
        "filter_tag": filter_tag,
        "campaign_key": campaign_key,
        "delivery_rate": round(sent / max(target_count, 1) * 100, 1),
        "created_at": now,
        "status": "completed",
    }

    broadcasts = _load_broadcasts()
    broadcasts.insert(0, record)  # newest first
    # Keep last 100 broadcasts
    broadcasts = broadcasts[:100]
    _save_broadcasts(broadcasts)

    logger.info(
        f"Broadcast logged: {sent}/{target_count} sent, "
        f"{failed} failed, template={template_name or 'custom'}"
    )
    return record


def get_broadcast_history(limit: int = 50) -> list:
    """Get broadcast history, newest first."""
    broadcasts = _load_broadcasts()
    return broadcasts[:limit]


def get_broadcast_stats() -> dict:
    """Get aggregate broadcast statistics."""
    broadcasts = _load_broadcasts()
    total_sent = sum(b.get("sent", 0) for b in broadcasts)
    total_failed = sum(b.get("failed", 0) for b in broadcasts)
    total_targeted = sum(b.get("target_count", 0) for b in broadcasts)

    return {
        "total_broadcasts": len(broadcasts),
        "total_messages_sent": total_sent,
        "total_failed": total_failed,
        "avg_delivery_rate": round(
            total_sent / max(total_targeted, 1) * 100, 1
        ),
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
    Personalize a broadcast message template with contact data.

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
# Broadcast execution
# ---------------------------------------------------------------------------

async def execute_broadcast(
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
    Execute a broadcast to a list of contacts.

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

    # Log the broadcast
    log_broadcast(
        message=message,
        template_name=template_name,
        target_count=len(contacts),
        sent=results["sent"],
        failed=results["failed"],
        filter_stage=filter_stage,
        filter_tag=filter_tag,
    )

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
