# -*- coding: utf-8 -*-
"""
Nazar — Channel Manager (Multi-Phone-Number Support)

Each workspace can operate multiple WhatsApp phone numbers ("channels").
A channel encapsulates:
  - Meta phone_number_id + access_token (credentials)
  - display_name (e.g. "Sales", "Support")
  - persona_prompt (override SOUL.md per channel)
  - default_reply_mode (auto_ai | human_only | ai_draft)
  - kb_scope (knowledge base scope: 'global' or 'channel_{id}')

Contacts, messages, handoffs, opt-outs are all scoped to a channel.
The "default" channel uses env-var credentials for backward compatibility.

Storage: SQLite via core/database.py (channels table)
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

from database import get_db, row_to_dict, rows_to_list
from workspace_context import get_workspace

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_CHANNEL = "default"

VALID_REPLY_MODES = ("auto_ai", "human_only", "ai_draft")


# ──────────────────────────────────────────────────────────────────────────────
# CRUD
# ──────────────────────────────────────────────────────────────────────────────

def create_channel(
    phone_number_id: str,
    access_token: str,
    display_name: str = "",
    waba_id: str = "",
    persona_prompt: str = "",
    default_reply_mode: str = "auto_ai",
    kb_scope: str = "global",
    is_primary: bool = False,
    workspace_id: Optional[str] = None,
) -> dict:
    """
    Register a new WhatsApp phone number as a channel.

    Args:
        phone_number_id: Meta phone number ID (globally unique).
        access_token: Per-number access token for the WhatsApp Cloud API.
        display_name: Human-readable label (e.g. "Sales", "Support").
        waba_id: WhatsApp Business Account ID.
        persona_prompt: System prompt override; empty = use global SOUL.md.
        default_reply_mode: Channel-level default reply mode.
        kb_scope: Knowledge base scope ('global' or 'channel_{id}').
        is_primary: Whether this is the workspace's primary number.
        workspace_id: Workspace this channel belongs to.

    Returns:
        The created channel record as a dict.

    Raises:
        ValueError: If phone_number_id is already registered.
    """
    ws = workspace_id or get_workspace()
    now = datetime.now(IST).isoformat()
    channel_id = f"ch_{uuid.uuid4().hex[:12]}"

    if default_reply_mode not in VALID_REPLY_MODES:
        raise ValueError(f"Invalid reply mode: {default_reply_mode}")

    record = {
        "id": channel_id,
        "workspace_id": ws,
        "phone_number_id": phone_number_id,
        "waba_id": waba_id or "",
        "access_token": access_token,
        "display_name": display_name or "",
        "persona_prompt": persona_prompt or "",
        "default_reply_mode": default_reply_mode,
        "kb_scope": kb_scope or "global",
        "is_primary": 1 if is_primary else 0,
        "is_active": 1,
        "created_at": now,
        "updated_at": now,
    }

    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO channels
                   (id, workspace_id, phone_number_id, waba_id, access_token,
                    display_name, persona_prompt, default_reply_mode, kb_scope,
                    is_primary, is_active, created_at, updated_at)
                   VALUES (:id, :workspace_id, :phone_number_id, :waba_id,
                           :access_token, :display_name, :persona_prompt,
                           :default_reply_mode, :kb_scope, :is_primary,
                           :is_active, :created_at, :updated_at)""",
                record,
            )

            # If this is primary, un-primary all others in the workspace
            if is_primary:
                conn.execute(
                    "UPDATE channels SET is_primary = 0 "
                    "WHERE workspace_id = ? AND id != ?",
                    (ws, channel_id),
                )
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            raise ValueError(
                f"Phone number ID '{phone_number_id}' is already registered as a channel"
            )
        raise

    logger.info("Channel created: %s (%s) in workspace %s",
                channel_id, display_name or phone_number_id, ws)
    return record


def get_channel(channel_id: str, workspace_id: Optional[str] = None) -> Optional[dict]:
    """Get a channel by its ID."""
    ws = workspace_id or get_workspace()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM channels WHERE id = ? AND workspace_id = ?",
            (channel_id, ws),
        ).fetchone()
    return row_to_dict(row)


def get_channel_by_phone_number_id(phone_number_id: str) -> Optional[dict]:
    """
    Look up a channel by Meta phone_number_id (globally unique).
    Used in webhook routing to determine which workspace+channel an
    inbound message belongs to.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM channels WHERE phone_number_id = ? AND is_active = 1",
            (phone_number_id,),
        ).fetchone()
    return row_to_dict(row)


def list_channels(workspace_id: Optional[str] = None, include_inactive: bool = False) -> List[dict]:
    """List all channels in a workspace."""
    ws = workspace_id or get_workspace()
    with get_db() as conn:
        if include_inactive:
            rows = conn.execute(
                "SELECT * FROM channels WHERE workspace_id = ? ORDER BY is_primary DESC, created_at ASC",
                (ws,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM channels WHERE workspace_id = ? AND is_active = 1 "
                "ORDER BY is_primary DESC, created_at ASC",
                (ws,),
            ).fetchall()
    return rows_to_list(rows)


def update_channel(channel_id: str, updates: dict, workspace_id: Optional[str] = None) -> Optional[dict]:
    """
    Update a channel's mutable fields.

    Allowed fields: display_name, persona_prompt, default_reply_mode,
    kb_scope, is_primary, is_active, access_token, waba_id.

    Returns the updated channel or None if not found.
    """
    ws = workspace_id or get_workspace()
    allowed = {
        "display_name", "persona_prompt", "default_reply_mode",
        "kb_scope", "is_primary", "is_active", "access_token", "waba_id",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return get_channel(channel_id, ws)

    if "default_reply_mode" in filtered:
        if filtered["default_reply_mode"] not in VALID_REPLY_MODES:
            raise ValueError(f"Invalid reply mode: {filtered['default_reply_mode']}")

    filtered["updated_at"] = datetime.now(IST).isoformat()

    set_clauses = ", ".join(f"{k} = ?" for k in filtered)
    values = list(filtered.values()) + [channel_id, ws]

    with get_db() as conn:
        conn.execute(
            f"UPDATE channels SET {set_clauses} WHERE id = ? AND workspace_id = ?",
            values,
        )

        # If setting as primary, un-primary others
        if filtered.get("is_primary"):
            conn.execute(
                "UPDATE channels SET is_primary = 0 "
                "WHERE workspace_id = ? AND id != ?",
                (ws, channel_id),
            )

    return get_channel(channel_id, ws)


def delete_channel(channel_id: str, workspace_id: Optional[str] = None, hard: bool = False) -> bool:
    """
    Deactivate (soft-delete) or hard-delete a channel.

    Soft-delete (default): sets is_active = 0. Data remains.
    Hard-delete: removes the channel row. Contacts/messages are NOT deleted.

    Returns True if a channel was affected.
    """
    ws = workspace_id or get_workspace()
    with get_db() as conn:
        if hard:
            result = conn.execute(
                "DELETE FROM channels WHERE id = ? AND workspace_id = ?",
                (channel_id, ws),
            )
        else:
            result = conn.execute(
                "UPDATE channels SET is_active = 0, updated_at = ? "
                "WHERE id = ? AND workspace_id = ?",
                (datetime.now(IST).isoformat(), channel_id, ws),
            )
    return result.rowcount > 0


def get_primary_channel(workspace_id: Optional[str] = None) -> Optional[dict]:
    """Get the primary (default) channel for a workspace."""
    ws = workspace_id or get_workspace()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM channels WHERE workspace_id = ? AND is_primary = 1 AND is_active = 1",
            (ws,),
        ).fetchone()
    return row_to_dict(row)


def get_channel_config(channel_id: str, workspace_id: Optional[str] = None) -> Optional[dict]:
    """
    Get configuration fields for a channel (persona, reply mode, KB scope).
    Returns None if channel not found.
    """
    ch = get_channel(channel_id, workspace_id)
    if not ch:
        return None
    return {
        "id": ch["id"],
        "display_name": ch["display_name"],
        "persona_prompt": ch["persona_prompt"],
        "default_reply_mode": ch["default_reply_mode"],
        "kb_scope": ch["kb_scope"],
        "phone_number_id": ch["phone_number_id"],
        "is_primary": bool(ch["is_primary"]),
    }


def get_channel_credentials(channel_id: str) -> Optional[dict]:
    """
    Get the Meta API credentials for a channel.
    Used by outbound send functions to route through the correct phone number.

    Returns dict with phone_number_id, access_token, or None.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT phone_number_id, access_token, waba_id FROM channels "
            "WHERE id = ? AND is_active = 1",
            (channel_id,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def ensure_default_channel(
    phone_number_id: str,
    access_token: str,
    workspace_id: str = "default",
    waba_id: str = "",
) -> dict:
    """
    Ensure a 'default' channel exists for backward compatibility.
    Called on startup when env vars WA_PHONE_NUMBER_ID / WA_ACCESS_TOKEN are set.

    If a channel with this phone_number_id already exists, returns it.
    Otherwise creates a new primary channel with id='default'.
    """
    existing = get_channel_by_phone_number_id(phone_number_id)
    if existing:
        return existing

    now = datetime.now(IST).isoformat()
    record = {
        "id": DEFAULT_CHANNEL,
        "workspace_id": workspace_id,
        "phone_number_id": phone_number_id,
        "waba_id": waba_id,
        "access_token": access_token,
        "display_name": "Primary",
        "persona_prompt": "",
        "default_reply_mode": "auto_ai",
        "kb_scope": "global",
        "is_primary": 1,
        "is_active": 1,
        "created_at": now,
        "updated_at": now,
    }

    try:
        with get_db() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO channels
                   (id, workspace_id, phone_number_id, waba_id, access_token,
                    display_name, persona_prompt, default_reply_mode, kb_scope,
                    is_primary, is_active, created_at, updated_at)
                   VALUES (:id, :workspace_id, :phone_number_id, :waba_id,
                           :access_token, :display_name, :persona_prompt,
                           :default_reply_mode, :kb_scope, :is_primary,
                           :is_active, :created_at, :updated_at)""",
                record,
            )
    except Exception as e:
        logger.warning("ensure_default_channel failed: %s", e)
        # If it already exists, return it
        existing = get_channel_by_phone_number_id(phone_number_id)
        if existing:
            return existing
        raise

    logger.info("Default channel created for phone_number_id=%s", phone_number_id)
    return record


def channel_count(workspace_id: Optional[str] = None) -> int:
    """Count active channels in a workspace."""
    ws = workspace_id or get_workspace()
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM channels WHERE workspace_id = ? AND is_active = 1",
            (ws,),
        ).fetchone()
    return row[0] if row else 0
