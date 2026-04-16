"""
Nazar - 24h Customer Service Window Tracker

WhatsApp Business API enforces a strict 24-hour messaging window:
  - When a customer messages you, a 24h Customer Service Window opens
  - During this window, you can send free-form text messages
  - After the window closes, only pre-approved template messages can be sent
  - Each new inbound message from the customer resets the 24h timer
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
WINDOW_HOURS = 24


def compute_window(contact: dict, now: datetime = None) -> dict:
    if now is None:
        now = datetime.now(IST)

    last_inbound = contact.get("last_replied_at") or ""
    if not last_inbound:
        return {
            "window_open": False,
            "expires_at": None,
            "hours_remaining": 0,
            "last_inbound_at": None,
            "requires_template": True,
            "can_send_freeform": False,
            "warning": "No inbound messages from this contact. Only template messages can be sent.",
        }

    try:
        last_dt = datetime.fromisoformat(last_inbound)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=IST)
        window_end = last_dt + timedelta(hours=WINDOW_HOURS)
        now_tz = now if now.tzinfo else now.replace(tzinfo=IST)
        remaining_seconds = (window_end - now_tz).total_seconds()
        window_open = remaining_seconds > 0
        hours_remaining = round(max(0, remaining_seconds / 3600), 2)
    except Exception:
        return {
            "window_open": False,
            "expires_at": None,
            "hours_remaining": 0,
            "last_inbound_at": last_inbound,
            "requires_template": True,
            "can_send_freeform": False,
            "warning": "Could not parse last inbound timestamp.",
        }

    warning = None
    if not window_open:
        warning = (
            "24h customer service window is closed. "
            "Free-form messages will be rejected by WhatsApp. "
            "Use an approved template to re-initiate conversation."
        )
    elif hours_remaining <= 2:
        warning = (
            f"Window closing soon ({hours_remaining}h remaining). "
            "Consider sending a template if you need to follow up later."
        )

    return {
        "window_open": window_open,
        "expires_at": window_end.isoformat() if window_open else None,
        "hours_remaining": hours_remaining,
        "last_inbound_at": last_inbound,
        "requires_template": not window_open,
        "can_send_freeform": window_open,
        "warning": warning,
    }


def batch_window_status(contacts: List[dict], now: datetime = None) -> Dict[str, dict]:
    if now is None:
        now = datetime.now(IST)
    results = {}
    for c in contacts:
        cid = c.get("contact_id") or c.get("id", "")
        results[cid] = compute_window(c, now)
    return results


def classify_campaign_targets(contacts: List[dict], now: datetime = None) -> dict:
    if now is None:
        now = datetime.now(IST)
    window_open = []
    window_closed = []
    for c in contacts:
        status = compute_window(c, now)
        if status["window_open"]:
            window_open.append({**c, "_window": status})
        else:
            window_closed.append({**c, "_window": status})
    return {
        "window_open": window_open,
        "window_closed": window_closed,
        "summary": {
            "open_count": len(window_open),
            "closed_count": len(window_closed),
            "total": len(contacts),
        },
    }
