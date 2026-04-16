# -*- coding: utf-8 -*-
"""
Nazar — Handoff Manager

Handles human handoff lifecycle:
1. AI-powered intent detection (replaces keyword matching)
2. Persistent handoff state (SQLite)
3. Reason logging with full audit trail
4. Team notification via WhatsApp
5. Auto-resume after configurable timeout
6. Handoff queue for the dashboard

Storage: SQLite via core/database.py (handoff_states + handoff_events tables)
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable

from database import get_db, row_to_dict, rows_to_list

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_AUTO_RESUME_HOURS = 0

# -----------------------------------------------------------------------
# Keyword triggers
# -----------------------------------------------------------------------

EXPLICIT_HANDOFF_PHRASES = [
    "talk to a person", "talk to someone", "real person",
    "speak to a human", "speak to someone",
    "connect me with someone", "connect me to a person",
    "transfer me", "let me talk to", "i want to speak with",
    "get me a human", "get me a manager",
    "i need a manager", "i need a supervisor",
    "can i talk to your manager",
]

ESCALATION_KEYWORDS = [
    "escalate", "complaint", "unsubscribe", "cancel my", "refund",
    "sue", "lawyer", "legal action", "consumer court", "trading standards",
    "file a complaint", "report you", "worst experience", "disgusted",
    "unacceptable", "ridiculous",
]


# -----------------------------------------------------------------------
# Bot mode queries
# -----------------------------------------------------------------------

def is_bot_active(contact_id: str) -> bool:
    """Check if the bot is active for a given contact (True = bot handles)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT bot_active FROM handoff_states WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()
    if row is None:
        return True  # Default: bot is on
    return bool(row["bot_active"])


def get_contact_handoff_state(contact_id: str) -> Optional[dict]:
    """Get the full handoff state for a contact."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM handoff_states WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_state(row)


def get_all_handoff_states() -> dict:
    """Get the full handoff state map {contact_id: {...}}."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM handoff_states").fetchall()
    return {r["contact_id"]: _row_to_state(r) for r in rows}


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
    """Trigger a human handoff for a contact."""
    now = datetime.now(IST).isoformat()

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

    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO handoff_states
               (contact_id, bot_active, reason, triggered_by, triggered_at,
                detection_method, contact_name, contact_phone, message_excerpt,
                human_responded, human_responded_at, resumed_at)
               VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL)""",
            (contact_id, reason, triggered_by, now,
             detection_method, contact_name, contact_phone, message_excerpt[:200]),
        )

        # Audit trail
        conn.execute(
            """INSERT INTO handoff_events
               (contact_id, event, reason, actor, contact_name, contact_phone,
                detection_method, message_excerpt, bot_active, triggered_by,
                triggered_at, timestamp)
               VALUES (?, 'handoff_triggered', ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
            (contact_id, reason, triggered_by, contact_name, contact_phone,
             detection_method, message_excerpt[:200], triggered_by, now, now),
        )

    logger.info(
        "Handoff triggered for %s (%s): %s [method=%s]",
        contact_id, contact_name, reason, detection_method,
    )
    return entry


def resume_bot(
    contact_id: str,
    resumed_by: str = "manual",
    reason: str = "",
) -> dict:
    """Resume bot for a contact (end human mode)."""
    now = datetime.now(IST).isoformat()

    with get_db() as conn:
        # Get existing state for the return value
        row = conn.execute(
            "SELECT * FROM handoff_states WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()

        conn.execute(
            """UPDATE handoff_states SET
               bot_active = 1, resumed_at = ?, resumed_by = ?, resume_reason = ?
               WHERE contact_id = ?""",
            (now, resumed_by, reason, contact_id),
        )

        if not row:
            # No existing state, create one
            conn.execute(
                """INSERT OR IGNORE INTO handoff_states
                   (contact_id, bot_active, resumed_at, resumed_by, resume_reason)
                   VALUES (?, 1, ?, ?, ?)""",
                (contact_id, now, resumed_by, reason),
            )

        conn.execute(
            """INSERT INTO handoff_events
               (contact_id, event, reason, actor, resumed_by, timestamp)
               VALUES (?, 'bot_resumed', ?, ?, ?, ?)""",
            (contact_id, reason, resumed_by, resumed_by, now),
        )

    entry = _row_to_state(row) if row else {}
    entry["bot_active"] = True
    entry["resumed_at"] = now
    entry["resumed_by"] = resumed_by
    entry["resume_reason"] = reason

    logger.info("Bot resumed for %s by %s", contact_id, resumed_by)
    return entry


def mark_human_responded(contact_id: str):
    """Mark that a human agent has responded to this handoff."""
    now = datetime.now(IST).isoformat()

    with get_db() as conn:
        conn.execute(
            "UPDATE handoff_states SET human_responded = 1, human_responded_at = ? "
            "WHERE contact_id = ?",
            (now, contact_id),
        )
        conn.execute(
            """INSERT INTO handoff_events
               (contact_id, event, timestamp)
               VALUES (?, 'human_responded', ?)""",
            (contact_id, now),
        )


# -----------------------------------------------------------------------
# Keyword detection
# -----------------------------------------------------------------------

def check_keyword_handoff(message: str) -> Optional[dict]:
    """Check if a message matches keyword-based handoff triggers."""
    lower = message.lower()

    for phrase in EXPLICIT_HANDOFF_PHRASES:
        if phrase in lower:
            return {
                "reason": f"Customer requested a human: '{phrase}'",
                "category": "explicit_request",
            }

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
- Casual use of words like "human" in non-request context
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
    """Use the LLM to determine if a handoff is needed."""
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
        raw = raw.strip()
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
        logger.warning("AI handoff check returned invalid JSON: %s", raw[:100])
        return None
    except Exception as e:
        logger.warning("AI handoff check failed: %s", e)
        return None


# -----------------------------------------------------------------------
# AI response self-detection
# -----------------------------------------------------------------------

def check_ai_response_handoff(ai_response: str) -> Optional[dict]:
    """Check if the AI's own response indicates it is handing off."""
    lower = ai_response.lower()

    handoff_phrases = [
        "connect you with", "someone from the team",
        "team member will", "team member who can",
        "have someone reach out", "let me get someone",
        "transfer you to", "have a colleague",
        "our team will reach out", "our team will get back",
        "a specialist will", "right person to help",
        "pass this along", "escalate this",
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
    """Check for contacts that should be auto-resumed."""
    if auto_resume_hours <= 0:
        return []

    now = datetime.now(IST)
    resumed = []

    with get_db() as conn:
        rows = conn.execute(
            "SELECT contact_id, triggered_at FROM handoff_states "
            "WHERE bot_active = 0 AND triggered_at IS NOT NULL"
        ).fetchall()

    for row in rows:
        triggered_at = row["triggered_at"]
        if not triggered_at:
            continue
        try:
            triggered_dt = datetime.fromisoformat(triggered_at)
            hours_since = (now - triggered_dt).total_seconds() / 3600
            if hours_since >= auto_resume_hours:
                resume_bot(
                    row["contact_id"],
                    resumed_by="auto_timeout",
                    reason=f"Auto-resumed after {auto_resume_hours}h with no human response",
                )
                resumed.append(row["contact_id"])
        except Exception as e:
            logger.warning("Auto-resume check failed for %s: %s", row["contact_id"], e)

    return resumed


# -----------------------------------------------------------------------
# Handoff queue for dashboard
# -----------------------------------------------------------------------

def get_handoff_queue() -> list:
    """Get all contacts currently in human mode (bot off)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM handoff_states WHERE bot_active = 0 "
            "ORDER BY triggered_at DESC"
        ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        result.append({
            "contact_id": d["contact_id"],
            "contact_name": d.get("contact_name") or "Unknown",
            "contact_phone": d.get("contact_phone") or "",
            "reason": d.get("reason") or "Unknown",
            "category": d.get("detection_method", "unknown"),
            "triggered_at": d.get("triggered_at") or "",
            "triggered_by": d.get("triggered_by") or "unknown",
            "detection_method": d.get("detection_method", "unknown"),
            "message_excerpt": d.get("message_excerpt") or "",
            "human_responded": bool(d.get("human_responded", 0)),
            "human_responded_at": d.get("human_responded_at"),
        })
    return result


def get_handoff_history(limit: int = 50) -> list:
    """Get the handoff audit log (most recent first)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM handoff_events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()

    return [dict(r) for r in rows]


def get_handoff_stats() -> dict:
    """Get aggregate handoff statistics."""
    with get_db() as conn:
        triggers = conn.execute(
            "SELECT COUNT(*) as cnt FROM handoff_events WHERE event = 'handoff_triggered'"
        ).fetchone()["cnt"]

        resumes = conn.execute(
            "SELECT COUNT(*) as cnt FROM handoff_events WHERE event = 'bot_resumed'"
        ).fetchone()["cnt"]

        queue_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM handoff_states WHERE bot_active = 0"
        ).fetchone()["cnt"]

        # By category
        cat_rows = conn.execute(
            "SELECT detection_method, COUNT(*) as cnt "
            "FROM handoff_events WHERE event = 'handoff_triggered' "
            "GROUP BY detection_method"
        ).fetchall()

    by_method = {r["detection_method"]: r["cnt"] for r in cat_rows}

    return {
        "total_handoffs": triggers,
        "total_resumes": resumes,
        "currently_in_queue": queue_count,
        "by_category": {},
        "by_detection_method": by_method,
    }


# -----------------------------------------------------------------------
# Full handoff evaluation
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
    """Full handoff evaluation pipeline."""
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
    """Check if the AI's own response triggered a handoff."""
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
    """Build a WhatsApp notification message for the team."""
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
# Internal
# -----------------------------------------------------------------------

def _row_to_state(row) -> dict:
    """Convert a handoff_states row to a dict."""
    d = dict(row)
    return {
        "bot_active": bool(d.get("bot_active", 1)),
        "reason": d.get("reason", ""),
        "triggered_by": d.get("triggered_by", ""),
        "triggered_at": d.get("triggered_at"),
        "detection_method": d.get("detection_method", ""),
        "contact_name": d.get("contact_name", ""),
        "contact_phone": d.get("contact_phone", ""),
        "message_excerpt": d.get("message_excerpt", ""),
        "human_responded": bool(d.get("human_responded", 0)),
        "human_responded_at": d.get("human_responded_at"),
        "resumed_at": d.get("resumed_at"),
        "resumed_by": d.get("resumed_by"),
        "resume_reason": d.get("resume_reason", ""),
    }
