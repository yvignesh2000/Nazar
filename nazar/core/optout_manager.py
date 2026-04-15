# -*- coding: utf-8 -*-
"""
Nazar — Opt-Out / STOP Manager

Handles WhatsApp opt-out compliance:
- Detects STOP, UNSUBSCRIBE, OPT OUT, and similar keywords
- Blocks all outbound messages to opted-out contacts
- Records opt-out timestamp, reason, and channel
- Provides opt-in re-subscription flow

Legal requirement: WhatsApp Business Policy requires honouring
opt-out requests immediately. Sending to opted-out contacts
violates Meta's policies and can get the number banned.

Storage: data/optouts.json (phone -> {opted_out, date, reason})
"""

import json
import fcntl
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"

# -----------------------------------------------------------------------
# Keyword detection
# -----------------------------------------------------------------------

STOP_KEYWORDS = [
    "stop",
    "unsubscribe",
    "opt out",
    "opt-out",
    "optout",
    "do not contact",
    "remove me",
    "don't contact me",
    "dont contact me",
    "please stop",
    "stop messaging",
    "stop texting",
    "stop sending",
    "no more messages",
    "block",
    "spam",
]

START_KEYWORDS = [
    "start",
    "subscribe",
    "opt in",
    "opt-in",
    "optin",
    "yes please",
    "restart",
    "resume",
    "resubscribe",
]

OPT_OUT_REPLY = (
    "You've been unsubscribed. You won't receive any more messages from us. "
    "Reply START at any time to re-subscribe."
)

OPT_IN_REPLY = (
    "Welcome back! You've been re-subscribed. "
    "You'll start receiving messages from us again."
)


def is_stop_message(message: str) -> bool:
    """
    Check if a message is an opt-out request.

    Detection logic:
    1. Exact match for single-word commands (STOP, QUIT, END, etc.)
    2. Phrase match for longer messages that explicitly request opt-out.
       "stop" alone is matched, but "stop being helpful" is NOT —
       the word must be followed by space/punctuation or be at end of string.
    """
    lower = message.lower().strip()

    # Exact single-word match (most common WhatsApp opt-out flow)
    if lower in ("stop", "unsubscribe", "quit", "cancel", "end"):
        return True

    # Phrase match for explicit opt-out requests (not "stop" as part of a sentence)
    explicit_phrases = [
        "please stop",
        "stop messaging",
        "stop texting",
        "stop sending",
        "no more messages",
        "unsubscribe",
        "opt out",
        "opt-out",
        "optout",
        "do not contact",
        "don't contact me",
        "dont contact me",
        "remove me from",
        "remove me",
        "block",
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

    for keyword in START_KEYWORDS:
        if keyword in lower:
            return True

    return False


# -----------------------------------------------------------------------
# Opt-out storage
# -----------------------------------------------------------------------

def _optouts_path() -> Path:
    return DATA_DIR / "optouts.json"


def _load_optouts() -> dict:
    """Load the opt-out registry. Returns {phone: {opted_out, date, reason}}."""
    path = _optouts_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_optouts(optouts: dict):
    path = _optouts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        path.write_text(json.dumps(optouts, indent=2, ensure_ascii=False), encoding="utf-8")


def record_optout(phone: str, reason: str = "STOP message", message: str = "") -> dict:
    """
    Record that a contact has opted out.

    Args:
        phone: E.164 phone number.
        reason: Why they opted out.
        message: The original message that triggered the opt-out.

    Returns:
        The opt-out record.
    """
    optouts = _load_optouts()
    now = datetime.now(IST).isoformat()
    record = {
        "phone": phone,
        "opted_out": True,
        "date": now,
        "reason": reason,
        "original_message": message[:200],
    }
    optouts[phone] = record
    _save_optouts(optouts)
    logger.info(f"Opt-out recorded: {phone} ({reason})")

    # Also update the contact profile if it exists
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
        logger.warning(f"Could not update contact opt-out status: {e}")

    return record


def record_optin(phone: str) -> dict:
    """
    Record that a contact has opted back in.

    Returns:
        Updated opt-out record with opted_out=False.
    """
    optouts = _load_optouts()
    now = datetime.now(IST).isoformat()

    existing = optouts.get(phone, {})
    record = {
        **existing,
        "phone": phone,
        "opted_out": False,
        "opted_in_again_at": now,
    }
    optouts[phone] = record
    _save_optouts(optouts)
    logger.info(f"Opt-in recorded: {phone}")

    # Update contact profile
    try:
        from contact_manager import get_contact_by_phone, update_contact, remove_tag
        contact = get_contact_by_phone(phone)
        if contact:
            update_contact(contact["contact_id"], opt_in=True)
            remove_tag(contact["contact_id"], "opted-out")
    except Exception as e:
        logger.warning(f"Could not update contact opt-in status: {e}")

    return record


def is_opted_out(phone: str) -> bool:
    """
    Check if a phone number has opted out.

    Returns True if the contact is opted out, False otherwise.
    Always returns False for unknown numbers (default is opted-in).
    """
    optouts = _load_optouts()
    record = optouts.get(phone, {})
    return bool(record.get("opted_out", False))


def get_optout_record(phone: str) -> Optional[dict]:
    """Get the opt-out record for a phone number."""
    optouts = _load_optouts()
    return optouts.get(phone)


def list_optouts() -> list:
    """List all opted-out phone numbers."""
    optouts = _load_optouts()
    return [
        record for record in optouts.values()
        if record.get("opted_out", False)
    ]


def get_optout_count() -> int:
    """Count of currently opted-out contacts."""
    return len(list_optouts())


# -----------------------------------------------------------------------
# Guard: check before sending
# -----------------------------------------------------------------------

def can_message(phone: str) -> bool:
    """
    Returns True if it is safe to send a message to this phone number.

    Call this before ANY outbound send. If False, skip the send.
    """
    return not is_opted_out(phone)


# -----------------------------------------------------------------------
# Test
# -----------------------------------------------------------------------

if __name__ == "__main__":
    import shutil

    test_dir = Path(__file__).parent.parent / "data"

    # 1. Stop keyword detection
    assert is_stop_message("STOP") is True
    assert is_stop_message("stop") is True
    assert is_stop_message("please stop messaging me") is True
    assert is_stop_message("unsubscribe") is True
    assert is_stop_message("Hello how are you") is False
    assert is_stop_message("what is your price?") is False
    print("✅ Stop keyword detection OK")

    # 2. Start keyword detection
    assert is_start_message("START") is True
    assert is_start_message("start") is True
    assert is_start_message("subscribe") is True
    assert is_start_message("hello") is False
    print("✅ Start keyword detection OK")

    # 3. Opt-out flow
    record = record_optout("+919876543210", reason="STOP message", message="STOP")
    assert record["opted_out"] is True
    assert is_opted_out("+919876543210") is True
    assert can_message("+919876543210") is False
    print("✅ Opt-out flow OK")

    # 4. Opt-in re-subscription
    record = record_optin("+919876543210")
    assert record["opted_out"] is False
    assert is_opted_out("+919876543210") is False
    assert can_message("+919876543210") is True
    print("✅ Opt-in flow OK")

    # 5. Unknown phone defaults to can-message
    assert can_message("+910000000000") is True
    print("✅ Unknown phone defaults to can-message OK")

    # Cleanup test record
    optouts = _load_optouts()
    optouts.pop("+919876543210", None)
    _save_optouts(optouts)

    print("\n✅ All optout_manager tests passed!")
