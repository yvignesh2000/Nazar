# -*- coding: utf-8 -*-
"""
Nazar — Reply Mode Manager

Manages how AI/humans respond to inbound messages per conversation and campaign.

Three modes:
  auto_ai     — AI replies automatically (default, current behavior)
  human_only  — Only human agents can reply. AI is silent.
  ai_draft    — AI generates a draft. Human reviews/edits before it's sent.

Hierarchy:
  1. Campaign-level reply mode (if contact replied to a campaign)
  2. Contact-level reply mode override
  3. Global default (auto_ai)

Also manages campaign-specific knowledge bases so the AI can reference
campaign-scoped context when responding to replies.
"""

import json
import logging
import fcntl
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"

VALID_MODES = ("auto_ai", "human_only", "ai_draft")
DEFAULT_MODE = "auto_ai"


# ───────────────────────────────────────────────
# Contact reply mode overrides
# ───────────────────────────────────────────────

def _reply_modes_path() -> Path:
    return DATA_DIR / "reply_modes.json"


def _load_reply_modes() -> dict:
    path = _reply_modes_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_reply_modes(modes: dict):
    path = _reply_modes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        path.write_text(json.dumps(modes, indent=2, ensure_ascii=False), encoding="utf-8")


def get_contact_reply_mode(contact_id: str) -> str:
    """Get the reply mode for a specific contact. Returns default if not set."""
    modes = _load_reply_modes()
    entry = modes.get(contact_id, {})
    return entry.get("mode", DEFAULT_MODE)


def set_contact_reply_mode(contact_id: str, mode: str, set_by: str = "manual") -> dict:
    """
    Set reply mode for a contact.
    Returns the updated entry.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid reply mode: {mode}. Must be one of {VALID_MODES}")

    modes = _load_reply_modes()
    now = datetime.now(IST).isoformat()
    modes[contact_id] = {
        "mode": mode,
        "set_by": set_by,
        "updated_at": now,
    }
    _save_reply_modes(modes)
    logger.info(f"Reply mode for {contact_id} set to '{mode}' by {set_by}")
    return modes[contact_id]


def clear_contact_reply_mode(contact_id: str):
    """Remove custom reply mode for a contact (reverts to default)."""
    modes = _load_reply_modes()
    if contact_id in modes:
        del modes[contact_id]
        _save_reply_modes(modes)


# ───────────────────────────────────────────────
# Campaign reply mode + knowledge base
# ───────────────────────────────────────────────

def _campaign_kb_dir() -> Path:
    d = DATA_DIR / "campaign_kb"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_campaign_kb(campaign_id: str, content: str):
    """Save campaign-specific knowledge base content."""
    path = _campaign_kb_dir() / f"{campaign_id}.txt"
    path.write_text(content, encoding="utf-8")
    logger.info(f"Campaign KB saved for {campaign_id}: {len(content)} chars")


def get_campaign_kb(campaign_id: str) -> str:
    """Get campaign-specific knowledge base content. Returns empty string if none."""
    path = _campaign_kb_dir() / f"{campaign_id}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")[:8000]  # Cap at 8K chars
    return ""


def delete_campaign_kb(campaign_id: str):
    """Delete campaign-specific knowledge base."""
    path = _campaign_kb_dir() / f"{campaign_id}.txt"
    if path.exists():
        path.unlink()


# ───────────────────────────────────────────────
# Campaign → Contact association (track which
# contacts received which campaign, so we know
# the reply mode and KB to use for replies)
# ───────────────────────────────────────────────

def _campaign_contacts_path() -> Path:
    return DATA_DIR / "campaign_contacts.json"


def _load_campaign_contacts() -> dict:
    """Returns {contact_id: campaign_id} for active campaign associations."""
    path = _campaign_contacts_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_campaign_contacts(mapping: dict):
    path = _campaign_contacts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")


def associate_contacts_to_campaign(contact_ids: list, campaign_id: str):
    """Mark contacts as recipients of a campaign (so replies route correctly)."""
    mapping = _load_campaign_contacts()
    for cid in contact_ids:
        mapping[cid] = campaign_id
    _save_campaign_contacts(mapping)


def get_contact_campaign(contact_id: str) -> Optional[str]:
    """Get the most recent campaign a contact was part of."""
    mapping = _load_campaign_contacts()
    return mapping.get(contact_id)


def clear_contact_campaign(contact_id: str):
    """Remove campaign association for a contact."""
    mapping = _load_campaign_contacts()
    if contact_id in mapping:
        del mapping[contact_id]
        _save_campaign_contacts(mapping)


# ───────────────────────────────────────────────
# AI Draft Management
# ───────────────────────────────────────────────

def _drafts_path() -> Path:
    return DATA_DIR / "ai_drafts.json"


def _load_drafts() -> dict:
    """Returns {contact_id: {draft, generated_at, ...}}"""
    path = _drafts_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_drafts(drafts: dict):
    path = _drafts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(drafts, indent=2, ensure_ascii=False), encoding="utf-8")


def save_draft(contact_id: str, draft_text: str, customer_message: str = "",
               campaign_id: str = "") -> dict:
    """Save an AI-generated draft for human review."""
    drafts = _load_drafts()
    now = datetime.now(IST).isoformat()
    entry = {
        "draft": draft_text,
        "customer_message": customer_message[:500],
        "campaign_id": campaign_id,
        "generated_at": now,
        "status": "pending",  # pending, approved, edited, rejected
    }
    drafts[contact_id] = entry
    _save_drafts(drafts)
    logger.info(f"AI draft saved for {contact_id}: {draft_text[:60]}...")
    return entry


def get_draft(contact_id: str) -> Optional[dict]:
    """Get pending AI draft for a contact."""
    drafts = _load_drafts()
    entry = drafts.get(contact_id)
    if entry and entry.get("status") == "pending":
        return entry
    return None


def get_all_pending_drafts() -> list:
    """Get all contacts with pending AI drafts."""
    drafts = _load_drafts()
    pending = []
    for contact_id, entry in drafts.items():
        if entry.get("status") == "pending":
            pending.append({
                "contact_id": contact_id,
                **entry,
            })
    pending.sort(key=lambda x: x.get("generated_at", ""), reverse=True)
    return pending


def approve_draft(contact_id: str, edited_text: str = "") -> Optional[dict]:
    """
    Approve an AI draft (optionally with edits).
    Returns the draft entry with the final text to send.
    """
    drafts = _load_drafts()
    entry = drafts.get(contact_id)
    if not entry or entry.get("status") != "pending":
        return None

    now = datetime.now(IST).isoformat()
    entry["status"] = "edited" if edited_text else "approved"
    entry["final_text"] = edited_text or entry["draft"]
    entry["approved_at"] = now
    drafts[contact_id] = entry
    _save_drafts(drafts)
    return entry


def reject_draft(contact_id: str) -> Optional[dict]:
    """Reject an AI draft."""
    drafts = _load_drafts()
    entry = drafts.get(contact_id)
    if not entry:
        return None

    now = datetime.now(IST).isoformat()
    entry["status"] = "rejected"
    entry["rejected_at"] = now
    drafts[contact_id] = entry
    _save_drafts(drafts)
    return entry


def clear_draft(contact_id: str):
    """Remove draft for a contact."""
    drafts = _load_drafts()
    if contact_id in drafts:
        del drafts[contact_id]
        _save_drafts(drafts)


# ───────────────────────────────────────────────
# Effective reply mode resolution
# ───────────────────────────────────────────────

def get_effective_reply_mode(contact_id: str) -> dict:
    """
    Determine the effective reply mode for a contact.

    Resolution order:
      1. Contact-level override (set manually from conversation UI)
      2. Campaign reply mode (if contact has an active campaign association)
      3. Global default (auto_ai)

    Returns:
      {
        "mode": "auto_ai" | "human_only" | "ai_draft",
        "source": "contact" | "campaign" | "default",
        "campaign_id": str or None,
        "campaign_kb": str or ""
      }
    """
    # 1. Contact-level override
    modes = _load_reply_modes()
    contact_entry = modes.get(contact_id, {})
    if contact_entry.get("mode") and contact_entry["mode"] != DEFAULT_MODE:
        return {
            "mode": contact_entry["mode"],
            "source": "contact",
            "campaign_id": None,
            "campaign_kb": "",
        }

    # 2. Campaign association
    campaign_id = get_contact_campaign(contact_id)
    if campaign_id:
        # Load campaign record to get its reply mode
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
