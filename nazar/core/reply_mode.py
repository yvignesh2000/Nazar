# -*- coding: utf-8 -*-
"""
Nazar — Reply Mode Manager

Manages how AI/humans respond to inbound messages per conversation and campaign.

Three modes:
  auto_ai     — AI replies automatically (default)
  human_only  — Only human agents can reply. AI is silent.
  ai_draft    — AI generates a draft. Human reviews/edits before it's sent.

Storage: SQLite via core/database.py
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from database import get_db

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"

VALID_MODES = ("auto_ai", "human_only", "ai_draft")
DEFAULT_MODE = "auto_ai"


# ───────────────────────────────────────────────
# Contact reply mode overrides
# ───────────────────────────────────────────────

def get_contact_reply_mode(contact_id: str) -> str:
    """Get the reply mode for a specific contact. Returns default if not set."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT mode FROM reply_modes WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()
    if row:
        return row["mode"]
    return DEFAULT_MODE


def set_contact_reply_mode(contact_id: str, mode: str, set_by: str = "manual") -> dict:
    """Set reply mode for a contact."""
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid reply mode: {mode}. Must be one of {VALID_MODES}")

    now = datetime.now(IST).isoformat()

    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO reply_modes
               (contact_id, mode, set_by, updated_at)
               VALUES (?, ?, ?, ?)""",
            (contact_id, mode, set_by, now),
        )

    logger.info("Reply mode for %s set to '%s' by %s", contact_id, mode, set_by)
    return {"mode": mode, "set_by": set_by, "updated_at": now}


def clear_contact_reply_mode(contact_id: str):
    """Remove custom reply mode for a contact (reverts to default)."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM reply_modes WHERE contact_id = ?",
            (contact_id,),
        )


# ───────────────────────────────────────────────
# Campaign reply mode + knowledge base
# ───────────────────────────────────────────────

def _campaign_kb_dir() -> Path:
    d = DATA_DIR / "campaign_kb"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_campaign_kb(campaign_id: str, content: str):
    """Save campaign-specific knowledge base content.

    Strips HTML tags to prevent XSS when the content is later injected into
    AI prompts or rendered in dashboard previews.
    """
    import re as _re
    # Strip HTML tags (defense-in-depth against prompt injection / XSS)
    sanitized = _re.sub(r"<[^>]+>", "", content)
    # Limit to 50000 chars (same as schema validation)
    sanitized = sanitized[:50000]
    path = _campaign_kb_dir() / f"{campaign_id}.txt"
    path.write_text(sanitized, encoding="utf-8")
    logger.info("Campaign KB saved for %s: %d chars", campaign_id, len(sanitized))


def get_campaign_kb(campaign_id: str) -> str:
    """Get campaign-specific knowledge base content."""
    path = _campaign_kb_dir() / f"{campaign_id}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")[:8000]
    return ""


def delete_campaign_kb(campaign_id: str):
    """Delete campaign-specific knowledge base."""
    path = _campaign_kb_dir() / f"{campaign_id}.txt"
    if path.exists():
        path.unlink()


# ───────────────────────────────────────────────
# Campaign → Contact association
# ───────────────────────────────────────────────

def associate_contacts_to_campaign(contact_ids: list, campaign_id: str):
    """Mark contacts as recipients of a campaign."""
    with get_db() as conn:
        for cid in contact_ids:
            conn.execute(
                """INSERT OR REPLACE INTO campaign_contacts
                   (contact_id, campaign_id) VALUES (?, ?)""",
                (cid, campaign_id),
            )


def get_contact_campaign(contact_id: str) -> Optional[str]:
    """Get the most recent campaign a contact was part of."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT campaign_id FROM campaign_contacts WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()
    return row["campaign_id"] if row else None


def clear_contact_campaign(contact_id: str):
    """Remove campaign association for a contact."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM campaign_contacts WHERE contact_id = ?",
            (contact_id,),
        )


# ───────────────────────────────────────────────
# AI Draft Management
# ───────────────────────────────────────────────

def save_draft(contact_id: str, draft_text: str, customer_message: str = "",
               campaign_id: str = "") -> dict:
    """Save an AI-generated draft for human review."""
    now = datetime.now(IST).isoformat()
    entry = {
        "draft": draft_text,
        "customer_message": customer_message[:500],
        "campaign_id": campaign_id,
        "generated_at": now,
        "status": "pending",
    }

    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO ai_drafts
               (contact_id, draft, customer_message, campaign_id, generated_at, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (contact_id, draft_text, customer_message[:500], campaign_id, now),
        )

    logger.info("AI draft saved for %s: %s...", contact_id, draft_text[:60])
    return entry


def get_draft(contact_id: str) -> Optional[dict]:
    """Get pending AI draft for a contact."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM ai_drafts WHERE contact_id = ? AND status = 'pending'",
            (contact_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_draft(row)


def get_all_pending_drafts() -> list:
    """Get all contacts with pending AI drafts."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_drafts WHERE status = 'pending' "
            "ORDER BY generated_at DESC"
        ).fetchall()
    return [_row_to_draft(r) for r in rows]


def approve_draft(contact_id: str, edited_text: str = "") -> Optional[dict]:
    """Approve an AI draft (optionally with edits)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM ai_drafts WHERE contact_id = ? AND status = 'pending'",
            (contact_id,),
        ).fetchone()
        if not row:
            return None

        now = datetime.now(IST).isoformat()
        final_text = edited_text or row["draft"]
        status = "edited" if edited_text else "approved"

        conn.execute(
            """UPDATE ai_drafts SET status = ?, final_text = ?, approved_at = ?
               WHERE contact_id = ? AND status = 'pending'""",
            (status, final_text, now, contact_id),
        )

    entry = _row_to_draft(row)
    entry["status"] = status
    entry["final_text"] = final_text
    entry["approved_at"] = now
    return entry


def reject_draft(contact_id: str) -> Optional[dict]:
    """Reject an AI draft."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM ai_drafts WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()
        if not row:
            return None

        now = datetime.now(IST).isoformat()
        conn.execute(
            """UPDATE ai_drafts SET status = 'rejected', rejected_at = ?
               WHERE contact_id = ?""",
            (now, contact_id),
        )

    entry = _row_to_draft(row)
    entry["status"] = "rejected"
    entry["rejected_at"] = now
    return entry


def clear_draft(contact_id: str):
    """Remove draft for a contact."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM ai_drafts WHERE contact_id = ?",
            (contact_id,),
        )


# ───────────────────────────────────────────────
# Effective reply mode resolution
# ───────────────────────────────────────────────

def get_effective_reply_mode(contact_id: str) -> dict:
    """
    Determine the effective reply mode for a contact.

    Resolution order:
      1. Contact-level override
      2. Campaign reply mode
      3. Global default (auto_ai)
    """
    # 1. Contact-level override
    with get_db() as conn:
        row = conn.execute(
            "SELECT mode FROM reply_modes WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()

    if row and row["mode"] and row["mode"] != DEFAULT_MODE:
        return {
            "mode": row["mode"],
            "source": "contact",
            "campaign_id": None,
            "campaign_kb": "",
        }

    # 2. Campaign association
    campaign_id = get_contact_campaign(contact_id)
    if campaign_id:
        from outbound import get_campaign
        campaign = get_campaign(campaign_id)
        if campaign:
            campaign_mode = campaign.get("reply_mode", DEFAULT_MODE)
            campaign_kb = get_campaign_kb(campaign_id)
            return {
                "mode": campaign_mode,
                "source": "campaign",
                "campaign_id": campaign_id,
                "campaign_kb": campaign_kb,
            }

    # 3. Default
    return {
        "mode": DEFAULT_MODE,
        "source": "default",
        "campaign_id": None,
        "campaign_kb": "",
    }


# ───────────────────────────────────────────────
# Internal
# ───────────────────────────────────────────────

def _row_to_draft(row) -> dict:
    d = dict(row)
    return {
        "contact_id": d["contact_id"],
        "draft": d["draft"],
        "customer_message": d.get("customer_message", ""),
        "campaign_id": d.get("campaign_id", ""),
        "generated_at": d.get("generated_at", ""),
        "status": d.get("status", "pending"),
        "final_text": d.get("final_text"),
        "approved_at": d.get("approved_at"),
        "rejected_at": d.get("rejected_at"),
    }
