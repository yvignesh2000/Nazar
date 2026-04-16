# -*- coding: utf-8 -*-
"""
Nazar — Opt-Out / STOP Manager

Handles WhatsApp opt-out compliance.
Storage: SQLite via core/database.py (optouts table)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from database import get_db

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

# -----------------------------------------------------------------------
# Keyword detection
# -----------------------------------------------------------------------

OPT_OUT_REPLY = (
    "You've been unsubscribed. You won't receive any more messages from us. "
    "Reply START at any time to re-subscribe."
)

OPT_IN_REPLY = (
    "Welcome back! You've been re-subscribed. "
    "You'll start receiving messages from us again."
)


def is_stop_message(message: str) -> bool:
    """Check if a message is an opt-out request."""
    lower = message.lower().strip()

    if lower in ("stop", "unsubscribe", "quit", "cancel", "end"):
        return True

    explicit_phrases = [
        "please stop", "stop messaging", "stop texting", "stop sending",
        "no more messages", "unsubscribe", "opt out", "opt-out", "optout",
        "do not contact", "don't contact me", "dont contact me",
        "remove me from", "remove me", "block",
    ]
    for phrase in explicit_phrases:
        if phrase in lower:
            return True

    return False


def is_start_message(message: str) -> bool:
    """Check if a message is an opt-in request."""
    lower = message.lower().strip()

    if lower in ("start", "yes", "subscribe"):
        return True

    start_keywords = [
        "start", "subscribe", "opt in", "opt-in", "optin",
        "yes please", "restart", "resume", "resubscribe",
    ]
    for keyword in start_keywords:
        if keyword in lower:
            return True

    return False


# -----------------------------------------------------------------------
# Opt-out storage
# -----------------------------------------------------------------------

def record_optout(phone: str, reason: str = "STOP message", message: str = "") -> dict:
    """Record that a contact has opted out."""
    now = datetime.now(IST).isoformat()
    record = {
        "phone": phone,
        "opted_out": True,
        "date": now,
        "reason": reason,
        "original_message": message[:200],
    }

    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO optouts
               (phone, opted_out, date, reason, original_message)
               VALUES (?, 1, ?, ?, ?)""",
            (phone, now, reason, message[:200]),
        )

    logger.info("Opt-out recorded: %s (%s)", phone, reason)

    # Update contact profile if it exists
    try:
        from contact_manager import get_contact_by_phone, update_contact
        contact = get_contact_by_phone(phone)
        if contact:
            update_contact(
                contact["contact_id"],
                opt_in=False,
                tags=list(set(contact.get("tags", []) + ["opted-out"])),
            )
    except Exception as e:
        logger.warning("Could not update contact opt-out status: %s", e)

    return record


def record_optin(phone: str) -> dict:
    """Record that a contact has opted back in."""
    now = datetime.now(IST).isoformat()

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM optouts WHERE phone = ?", (phone,)
        ).fetchone()

        conn.execute(
            """INSERT OR REPLACE INTO optouts
               (phone, opted_out, date, reason, original_message, opted_in_again_at)
               VALUES (?, 0,
                       COALESCE((SELECT date FROM optouts WHERE phone = ?), ?),
                       COALESCE((SELECT reason FROM optouts WHERE phone = ?), ''),
                       COALESCE((SELECT original_message FROM optouts WHERE phone = ?), ''),
                       ?)""",
            (phone, phone, now, phone, phone, now),
        )

    logger.info("Opt-in recorded: %s", phone)

    # Update contact profile
    try:
        from contact_manager import get_contact_by_phone, update_contact, remove_tag
        contact = get_contact_by_phone(phone)
        if contact:
            update_contact(contact["contact_id"], opt_in=True)
            remove_tag(contact["contact_id"], "opted-out")
    except Exception as e:
        logger.warning("Could not update contact opt-in status: %s", e)

    record = dict(row) if row else {}
    record["phone"] = phone
    record["opted_out"] = False
    record["opted_in_again_at"] = now
    return record


def is_opted_out(phone: str) -> bool:
    """Check if a phone number has opted out."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT opted_out FROM optouts WHERE phone = ?", (phone,)
        ).fetchone()
    if row is None:
        return False
    return bool(row["opted_out"])


def get_optout_record(phone: str) -> Optional[dict]:
    """Get the opt-out record for a phone number."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM optouts WHERE phone = ?", (phone,)
        ).fetchone()
    return dict(row) if row else None


def list_optouts() -> list:
    """List all opted-out phone numbers."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM optouts WHERE opted_out = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def get_optout_count() -> int:
    """Count of currently opted-out contacts."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM optouts WHERE opted_out = 1"
        ).fetchone()
    return row["cnt"]


# -----------------------------------------------------------------------
# Guard: check before sending
# -----------------------------------------------------------------------

def can_message(phone: str) -> bool:
    """Returns True if it is safe to send a message to this phone number."""
    return not is_opted_out(phone)
