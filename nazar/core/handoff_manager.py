# -*- coding: utf-8 -*-
"""
Nazar -- Handoff Manager

Handles human handoff lifecycle:
1. AI-powered intent detection (replaces keyword matching)
2. Persistent handoff state (survives server restarts)
3. Reason logging with full audit trail
4. Team notification via WhatsApp
5. Auto-resume after configurable timeout
6. Handoff queue for the dashboard

Storage: data/handoffs/
  state.json        -- current bot on/off per contact + metadata
  history.jsonl     -- audit log of all handoff events
"""

import json
import logging
import fcntl
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data" / "handoffs"

# Default auto-resume timeout in hours (0 = disabled)
DEFAULT_AUTO_RESUME_HOURS = 0

# -----------------------------------------------------------------------
# Keyword triggers (fast, no LLM cost — first pass filter)
# -----------------------------------------------------------------------

EXPLICIT_HANDOFF_PHRASES = [
    "talk to a person",
    "talk to someone",
    "real person",
    "speak to a human",
    "speak to someone",
    "connect me with someone",
    "connect me to a person",
    "transfer me",
    "let me talk to",
    "i want to speak with",
    "get me a human",
    "get me a manager",
    "i need a manager",
    "i need a supervisor",
    "can i talk to your manager",
]

ESCALATION_KEYWORDS = [
    "escalate",
    "complaint",
    "unsubscribe",
    "cancel my",
    "refund",
    "sue",
    "lawyer",
    "legal action",
    "consumer court",
    "trading standards",
    "file a complaint",
    "report you",
    "worst experience",
    "disgusted",
    "unacceptable",
    "ridiculous",
]


# -----------------------------------------------------------------------
# State persistence
# -----------------------------------------------------------------------

def _state_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "state.json"


def _history_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "history.jsonl"


def _load_state() -> dict:
    """Load the full handoff state. Returns {contact_id: {...}}."""
    path = _state_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load handoff state: {e}")
        return {}


def _save_state(state: dict):
    """Save the full handoff state with file locking."""
    path = _state_path()
    lock_path = path.with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)


def _append_history(event: dict):
    """Append a handoff event to the audit log."""
    path = _history_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to log handoff event: {e}")


# -----------------------------------------------------------------------
# Bot mode queries
# -----------------------------------------------------------------------

def is_bot_active(contact_id: str) -> bool:
    """Check if the bot is active for a given contact (True = bot handles)."""
    state = _load_state()
    entry = state.get(contact_id)
    if entry is None:
        return True  # Default: bot is on
    return entry.get("bot_active", True)


def get_contact_handoff_state(contact_id: str) -> Optional[dict]:
    """
    Get the full handoff state for a contact.
    Returns None if no handoff has ever happened.
    Returns dict with: bot_active, reason, triggered_at, triggered_by, etc.
    """
    state = _load_state()
    return state.get(contact_id)


def get_all_handoff_states() -> dict:
    """Get the full handoff state map {contact_id: {...}}."""
    return _load_state()


# -----------------------------------------------------------------------
# Handoff triggers
# -----------------------------------------------------------------------

def trigger_handoff(
    contact_id: str,
    reason: str,
    triggered_by: str = "system",
    contact_name: str = "",
    contact_phone: str = "",
    message_excerpt: str = "",
    detection_method: str = "keyword",
) -> dict:
    """
    Trigger a human handoff for a contact.

    Args:
        contact_id: The contact's unique ID.
        reason: Why the handoff happened (human-readable).
        triggered_by: "keyword", "ai", "manual", "error".
        contact_name: Customer name for notifications.
        contact_phone: Customer phone for notifications.
        message_excerpt: The message that triggered the handoff.
        detection_method: "keyword", "ai_intent", "ai_response", "manual".

    Returns:
        The handoff state entry.
    """
    now = datetime.now(IST).isoformat()

    state = _load_state()
    entry = {
        "bot_active": False,
        "reason": reason,
        "triggered_by": triggered_by,
        "triggered_at": now,
        "detection_method": detection_method,
        "contact_name": contact_name,
        "contact_phone": contact_phone,
        "message_excerpt": message_excerpt[:200],
        "human_responded": False,
        "human_responded_at": None,
        "resumed_at": None,
    }
    state[contact_id] = entry
    _save_state(state)

    # Log to audit trail
    _append_history({
        "event": "handoff_triggered",
        "contact_id": contact_id,
        "contact_name": contact_name,
        "timestamp": now,
        **entry,
    })

    logger.info(
        f"Handoff triggered for {contact_id} ({contact_name}): "
        f"{reason} [method={detection_method}]"
    )

    return entry


def resume_bot(
    contact_id: str,
    resumed_by: str = "manual",
    reason: str = "",
) -> dict:
    """
    Resume bot for a contact (end human mode).

    Args:
        contact_id: The contact's unique ID.
        resumed_by: "manual", "auto_timeout", "human_agent".
        reason: Optional reason for resuming.

    Returns:
        The updated state entry.
    """
    now = datetime.now(IST).isoformat()

    state = _load_state()
    entry = state.get(contact_id, {})
    entry["bot_active"] = True
    entry["resumed_at"] = now
    entry["resumed_by"] = resumed_by
    entry["resume_reason"] = reason
    state[contact_id] = entry
    _save_state(state)

    # Log to audit trail
    _append_history({
        "event": "bot_resumed",
        "contact_id": contact_id,
        "timestamp": now,
        "resumed_by": resumed_by,
        "reason": reason,
    })

    logger.info(f"Bot resumed for {contact_id} by {resumed_by}")
    return entry


def mark_human_responded(contact_id: str):
    """Mark that a human agent has responded to this handoff."""
    now = datetime.now(IST).isoformat()
    state = _load_state()
    entry = state.get(contact_id)
    if entry:
        entry["human_responded"] = True
        entry["human_responded_at"] = now
        _save_state(state)
        _append_history({
            "event": "human_responded",
            "contact_id": contact_id,
            "timestamp": now,
        })


# -----------------------------------------------------------------------
# Keyword detection (fast first-pass — no LLM cost)
# -----------------------------------------------------------------------

def check_keyword_handoff(message: str) -> Optional[dict]:
    """
    Check if a message matches keyword-based handoff triggers.

    Returns None if no match, or a dict with:
        {"reason": str, "category": "explicit_request"|"escalation"}
    """
    lower = message.lower()

    # Check explicit requests to talk to a human
    for phrase in EXPLICIT_HANDOFF_PHRASES:
        if phrase in lower:
            return {
                "reason": f"Customer requested a human: '{phrase}'",
                "category": "explicit_request",
            }

    # Check escalation keywords
    for keyword in ESCALATION_KEYWORDS:
        if keyword in lower:
            return {
                "reason": f"Escalation detected: '{keyword}'",
                "category": "escalation",
            }

    return None


# -----------------------------------------------------------------------
# AI-powered intent detection
# -----------------------------------------------------------------------

AI_HANDOFF_CHECK_PROMPT = """You are a handoff detection system for a WhatsApp sales bot. Analyze the customer message and conversation context to determine if a human agent should take over.

Trigger a handoff if ANY of these are true:
1. Customer explicitly asks for a human/person/manager/agent
2. Customer is frustrated, angry, or emotionally escalating
3. Customer has a complaint that the bot cannot resolve
4. Complex pricing negotiation beyond standard plans
5. Legal, contractual, or compliance questions
6. Custom requirements not answerable from a knowledge base
7. The customer has asked the same question 3+ times (bot is failing them)
8. Sensitive topics: cancellation, refund disputes, data deletion

DO NOT trigger a handoff for:
- Normal product questions
- Casual use of words like "human" in non-request context (e.g., "I'm only human")
- Mild confusion that can be resolved with a better answer
- Price inquiries about standard plans

Respond with EXACTLY one JSON object (no markdown, no explanation):
{"handoff": true/false, "reason": "one-line reason", "confidence": 0.0-1.0, "category": "explicit_request|frustration|escalation|complex_query|legal|repeated_failure|none"}
"""


async def check_ai_handoff(
    message: str,
    recent_messages: list,
    llm_call: Callable,
    contact_name: str = "",
) -> Optional[dict]:
    """
    Use the LLM to determine if a handoff is needed.

    This is the smart check — more expensive but much more accurate
    than keyword matching. Only called when keyword check is negative
    and smart_handoff is enabled.

    Args:
        message: The current customer message.
        recent_messages: Last few messages for context.
        llm_call: async callable(messages) -> str.
        contact_name: Customer name for context.

    Returns:
        None if no handoff needed, or dict with reason/confidence/category.
    """
    # Build context from recent messages
    context_lines = []
    for msg in recent_messages[-6:]:
        role = "Customer" if msg.get("direction") == "inbound" else "Bot"
        context_lines.append(f"{role}: {msg['content'][:150]}")
    context = "\n".join(context_lines)

    messages = [
        {"role": "system", "content": AI_HANDOFF_CHECK_PROMPT},
        {"role": "user", "content": f"Customer name: {contact_name or 'Unknown'}\n\nRecent conversation:\n{context}\n\nLatest customer message:\n{message}"},
    ]

    try:
        raw = await llm_call(messages)
        # Parse JSON from response
        raw = raw.strip()
        # Handle markdown-wrapped JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)

        if result.get("handoff") is True and result.get("confidence", 0) >= 0.7:
            return {
                "reason": result.get("reason", "AI detected handoff needed"),
                "category": result.get("category", "unknown"),
                "confidence": result.get("confidence", 0.0),
            }

        return None

    except json.JSONDecodeError:
        logger.warning(f"AI handoff check returned invalid JSON: {raw[:100]}")
        return None
    except Exception as e:
        logger.warning(f"AI handoff check failed: {e}")
        return None


# -----------------------------------------------------------------------
# AI response self-detection
# -----------------------------------------------------------------------

def check_ai_response_handoff(ai_response: str) -> Optional[dict]:
    """
    Check if the AI's own response indicates it is handing off.

    The SOUL.md instructs the AI to say things like:
    "Let me connect you with someone from the team..."

    If the AI says this, we should actually trigger the handoff
    rather than letting the bot continue handling the next message.

    Returns None or {"reason": str}.
    """
    lower = ai_response.lower()

    handoff_phrases = [
        "connect you with",
        "someone from the team",
        "team member will",
        "team member who can",
        "have someone reach out",
        "let me get someone",
        "transfer you to",
        "have a colleague",
        "our team will reach out",
        "our team will get back",
        "a specialist will",
        "right person to help",
        "pass this along",
        "escalate this",
    ]

    for phrase in handoff_phrases:
        if phrase in lower:
            return {
                "reason": f"AI initiated handoff in response (matched: '{phrase}')",
                "category": "ai_self_handoff",
            }

    return None


# -----------------------------------------------------------------------
# Auto-resume check
# -----------------------------------------------------------------------

def check_auto_resume(auto_resume_hours: int = 0) -> list:
    """
    Check for contacts that should be auto-resumed.

    Args:
        auto_resume_hours: Hours after which to auto-resume.
                          0 = disabled.

    Returns:
        List of contact_ids that were auto-resumed.
    """
    if auto_resume_hours <= 0:
        return []

    now = datetime.now(IST)
    state = _load_state()
    resumed = []

    for contact_id, entry in state.items():
        if entry.get("bot_active", True):
            continue  # Already active

        triggered_at = entry.get("triggered_at")
        if not triggered_at:
            continue

        try:
            triggered_dt = datetime.fromisoformat(triggered_at)
            hours_since = (now - triggered_dt).total_seconds() / 3600
            if hours_since >= auto_resume_hours:
                resume_bot(
                    contact_id,
                    resumed_by="auto_timeout",
                    reason=f"Auto-resumed after {auto_resume_hours}h with no human response",
                )
                resumed.append(contact_id)
        except Exception as e:
            logger.warning(f"Auto-resume check failed for {contact_id}: {e}")

    return resumed


# -----------------------------------------------------------------------
# Handoff queue for dashboard
# -----------------------------------------------------------------------

def get_handoff_queue() -> list:
    """
    Get all contacts currently in human mode (bot off).
    Returns a list sorted by triggered_at (newest first).
    """
    state = _load_state()
    queue = []

    for contact_id, entry in state.items():
        if not entry.get("bot_active", True):
            queue.append({
                "contact_id": contact_id,
                "contact_name": entry.get("contact_name", "Unknown"),
                "contact_phone": entry.get("contact_phone", ""),
                "reason": entry.get("reason", "Unknown"),
                "category": entry.get("category", entry.get("detection_method", "unknown")),
                "triggered_at": entry.get("triggered_at", ""),
                "triggered_by": entry.get("triggered_by", "unknown"),
                "detection_method": entry.get("detection_method", "unknown"),
                "message_excerpt": entry.get("message_excerpt", ""),
                "human_responded": entry.get("human_responded", False),
                "human_responded_at": entry.get("human_responded_at"),
            })

    queue.sort(key=lambda x: x.get("triggered_at", ""), reverse=True)
    return queue


def get_handoff_history(limit: int = 50) -> list:
    """
    Get the handoff audit log (most recent first).

    Returns list of event dicts.
    """
    path = _history_path()
    if not path.exists():
        return []

    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except Exception as e:
        logger.warning(f"Failed to read handoff history: {e}")
        return []

    events.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return events[:limit]


def get_handoff_stats() -> dict:
    """
    Get aggregate handoff statistics.

    Returns dict with counts by category, avg time to human response, etc.
    """
    history = get_handoff_history(limit=500)

    triggers = [e for e in history if e.get("event") == "handoff_triggered"]
    resumes = [e for e in history if e.get("event") == "bot_resumed"]

    by_category = {}
    by_method = {}
    for t in triggers:
        cat = t.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1

        method = t.get("detection_method", "unknown")
        by_method[method] = by_method.get(method, 0) + 1

    queue = get_handoff_queue()

    return {
        "total_handoffs": len(triggers),
        "total_resumes": len(resumes),
        "currently_in_queue": len(queue),
        "by_category": by_category,
        "by_detection_method": by_method,
    }


# -----------------------------------------------------------------------
# Full handoff evaluation (the main entry point)
# -----------------------------------------------------------------------

async def evaluate_handoff(
    contact_id: str,
    message: str,
    recent_messages: list,
    llm_call: Optional[Callable] = None,
    contact_name: str = "",
    contact_phone: str = "",
    smart_handoff_enabled: bool = True,
) -> Optional[dict]:
    """
    Full handoff evaluation pipeline:
    1. Keyword check (fast, free)
    2. AI intent check (smart, costs tokens — only if enabled)

    Args:
        contact_id: Contact ID.
        message: Current inbound message.
        recent_messages: Recent conversation for context.
        llm_call: async callable for AI check (haiku tier).
        contact_name: Customer name.
        contact_phone: Customer phone.
        smart_handoff_enabled: Whether to run AI check after keywords.

    Returns:
        None if no handoff, or the handoff state entry dict.
    """
    # 1. Keyword check (always runs — free and fast)
    keyword_result = check_keyword_handoff(message)
    if keyword_result:
        entry = trigger_handoff(
            contact_id=contact_id,
            reason=keyword_result["reason"],
            triggered_by="system",
            contact_name=contact_name,
            contact_phone=contact_phone,
            message_excerpt=message,
            detection_method="keyword",
        )
        return entry

    # 2. AI intent check (only if smart handoff is enabled and llm available)
    if smart_handoff_enabled and llm_call:
        ai_result = await check_ai_handoff(
            message=message,
            recent_messages=recent_messages,
            llm_call=llm_call,
            contact_name=contact_name,
        )
        if ai_result:
            entry = trigger_handoff(
                contact_id=contact_id,
                reason=ai_result["reason"],
                triggered_by="system",
                contact_name=contact_name,
                contact_phone=contact_phone,
                message_excerpt=message,
                detection_method="ai_intent",
            )
            return entry

    return None


async def evaluate_response_handoff(
    contact_id: str,
    ai_response: str,
    contact_name: str = "",
    contact_phone: str = "",
) -> Optional[dict]:
    """
    Check if the AI's own response triggered a handoff.
    Called AFTER the AI generates a reply.

    Returns None or the handoff state entry.
    """
    result = check_ai_response_handoff(ai_response)
    if result:
        entry = trigger_handoff(
            contact_id=contact_id,
            reason=result["reason"],
            triggered_by="ai",
            contact_name=contact_name,
            contact_phone=contact_phone,
            message_excerpt=ai_response[:200],
            detection_method="ai_response",
        )
        return entry
    return None


# -----------------------------------------------------------------------
# Team notification helper
# -----------------------------------------------------------------------

def build_team_notification(
    contact_name: str,
    contact_phone: str,
    reason: str,
    message_excerpt: str,
) -> str:
    """
    Build a WhatsApp notification message for the team.

    Returns a formatted string ready to send.
    """
    return (
        f"🔔 *Handoff Alert*\n\n"
        f"*Customer:* {contact_name or 'Unknown'}\n"
        f"*Phone:* {contact_phone}\n"
        f"*Reason:* {reason}\n"
        f"*Last message:* \"{message_excerpt[:150]}\"\n\n"
        f"The bot has paused for this customer. "
        f"Reply to them directly or re-enable the bot from the dashboard."
    )


# -----------------------------------------------------------------------
# Test
# -----------------------------------------------------------------------

if __name__ == "__main__":
    import shutil
    import asyncio

    # Clean
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)

    # 1. Keyword detection
    assert check_keyword_handoff("I want to talk to a person") is not None
    assert check_keyword_handoff("I want to sue you") is not None
    assert check_keyword_handoff("What's the price?") is None
    assert check_keyword_handoff("I'm only human, I make mistakes") is None  # No false positive!
    print("✅ Keyword detection tests passed")

    # 2. Trigger handoff
    entry = trigger_handoff(
        "test123", "Customer requested human",
        contact_name="Raj", contact_phone="+919876543210",
        message_excerpt="Talk to a person please",
        detection_method="keyword",
    )
    assert entry["bot_active"] is False
    assert is_bot_active("test123") is False
    assert is_bot_active("other_contact") is True  # default
    print("✅ Trigger handoff tests passed")

    # 3. Queue
    queue = get_handoff_queue()
    assert len(queue) == 1
    assert queue[0]["contact_id"] == "test123"
    print("✅ Queue tests passed")

    # 4. Resume
    resume_bot("test123", resumed_by="manual")
    assert is_bot_active("test123") is True
    queue = get_handoff_queue()
    assert len(queue) == 0
    print("✅ Resume tests passed")

    # 5. History
    history = get_handoff_history()
    assert len(history) >= 2  # triggered + resumed
    print("✅ History tests passed")

    # 6. AI response detection
    assert check_ai_response_handoff("Here's the pricing for plan A") is None
    assert check_ai_response_handoff("Let me connect you with someone from the team who can help") is not None
    print("✅ AI response detection tests passed")

    # 7. Stats
    stats = get_handoff_stats()
    assert stats["total_handoffs"] >= 1
    print(f"✅ Stats: {json.dumps(stats, indent=2)}")

    # 8. Notification
    msg = build_team_notification("Raj", "+919876543210", "Customer frustrated", "This is terrible")
    assert "Raj" in msg
    assert "Handoff Alert" in msg
    print("✅ Notification format tests passed")

    # Cleanup
    shutil.rmtree(DATA_DIR)
    print("\n✅ All handoff manager tests passed!")
