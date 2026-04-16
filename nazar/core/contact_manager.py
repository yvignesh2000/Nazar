"""
Nazar — Contact Manager (CRM Data Layer)

Handles contact creation, pipeline management, lead scoring,
conversation logging, and CSV import for the WhatsApp Sales
Intelligence Platform.

Storage: SQLite via core/database.py
Conversations are stored as rows in the messages table.

Multi-tenancy: All operations accept an optional workspace_id parameter
(defaults to 'default' for backward compatibility).
"""

import csv
import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from database import get_db, row_to_dict, rows_to_list

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

PIPELINE_STAGES = ["New", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]

DEFAULT_WORKSPACE = "default"


# ---------------------------------------------------------------------------
# Phone number normalization
# ---------------------------------------------------------------------------

def normalize_phone(phone: str) -> str:
    """Normalize a phone number to E.164 format."""
    cleaned = re.sub(r"[\s\-\(\)\.]", "", phone)
    if cleaned and cleaned[0] != "+" and cleaned[0].isdigit():
        cleaned = "+" + cleaned
    return cleaned


# ---------------------------------------------------------------------------
# Contact CRUD
# ---------------------------------------------------------------------------

def create_contact(
    name: str,
    phone: str,
    company: Optional[str] = None,
    source: Optional[str] = None,
    assigned_to: Optional[str] = None,
    tags: Optional[list] = None,
    workspace_id: str = DEFAULT_WORKSPACE,
) -> dict:
    """
    Create a new contact.

    Returns the full contact dict with generated contact_id.
    Raises ValueError if a contact with the same phone already exists in this workspace.
    """
    phone = normalize_phone(phone)

    if contact_exists(phone, workspace_id=workspace_id):
        raise ValueError(f"Contact with phone {phone} already exists")

    contact_id = uuid.uuid4().hex[:12]
    now = datetime.now(IST).isoformat()

    profile = {
        "contact_id": contact_id,
        "name": name,
        "phone": phone,
        "company": company or "",
        "pipeline_stage": "New",
        "deal_value": 0.0,
        "lead_score": 0,
        "assigned_to": assigned_to,
        "tags": tags or [],
        "source": source or "",
        "last_contacted_at": None,
        "last_replied_at": None,
        "total_messages": 0,
        "opt_in": False,
        "opt_in_date": None,
        "created_at": now,
        "notes": "",
        "workspace_id": workspace_id,
    }

    with get_db() as conn:
        conn.execute(
            """INSERT INTO contacts
               (id, workspace_id, phone, name, company, pipeline_stage, lead_score,
                deal_value, source, tags, notes, assigned_to, opt_in, opt_in_date,
                total_messages, last_contacted_at, last_replied_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                contact_id, workspace_id, phone, name, company or "", "New", 0, 0.0,
                source or "", json.dumps(tags or []), "", assigned_to,
                0, None, 0, None, None, now,
            ),
        )

    logger.info("Created contact: %s (%s, %s) ws=%s", contact_id, name, phone, workspace_id)
    return profile


def get_contact(contact_id: str) -> dict:
    """Load a contact's profile."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
    if not row:
        raise FileNotFoundError(f"Contact {contact_id} not found")
    return _row_to_profile(row)


def update_contact(contact_id: str, **fields) -> dict:
    """
    Update one or more fields on a contact's profile.

    Returns the updated profile dict.
    Raises FileNotFoundError if contact does not exist.
    """
    # Ensure contact exists
    profile = get_contact(contact_id)

    if "phone" in fields:
        fields["phone"] = normalize_phone(fields["phone"])

    if "pipeline_stage" in fields and fields["pipeline_stage"] not in PIPELINE_STAGES:
        raise ValueError(
            f"Invalid pipeline stage '{fields['pipeline_stage']}'. "
            f"Must be one of: {PIPELINE_STAGES}"
        )

    if "lead_score" in fields:
        score = fields["lead_score"]
        if not isinstance(score, (int, float)) or score < 0 or score > 100:
            raise ValueError("lead_score must be between 0 and 100")

    # Map profile field names → DB column names
    col_map = {
        "name": "name",
        "phone": "phone",
        "company": "company",
        "pipeline_stage": "pipeline_stage",
        "lead_score": "lead_score",
        "deal_value": "deal_value",
        "source": "source",
        "tags": "tags",
        "notes": "notes",
        "assigned_to": "assigned_to",
        "opt_in": "opt_in",
        "opt_in_date": "opt_in_date",
        "total_messages": "total_messages",
        "last_contacted_at": "last_contacted_at",
        "last_replied_at": "last_replied_at",
        "manual_stage_override": "manual_stage_override",
    }

    sets = []
    vals = []
    for k, v in fields.items():
        col = col_map.get(k)
        if col is None:
            continue
        if col == "tags":
            v = json.dumps(v) if isinstance(v, list) else v
        elif col == "opt_in":
            v = 1 if v else 0
        sets.append(f"{col} = ?")
        vals.append(v)

    if not sets:
        return profile

    sets.append("updated_at = ?")
    vals.append(datetime.now(IST).isoformat())
    vals.append(contact_id)

    with get_db() as conn:
        conn.execute(
            f"UPDATE contacts SET {', '.join(sets)} WHERE id = ?",
            vals,
        )

    updated = get_contact(contact_id)
    logger.info("Updated contact %s: %s", contact_id, list(fields.keys()))
    return updated


def delete_contact(contact_id: str):
    """Permanently delete a contact and all their data."""
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE contact_id = ?", (contact_id,))
        conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
    logger.info("Deleted contact: %s", contact_id)


def list_contacts(
    stage: Optional[str] = None,
    assigned_to: Optional[str] = None,
    tag: Optional[str] = None,
    workspace_id: str = DEFAULT_WORKSPACE,
) -> list:
    """List all contacts, optionally filtered. Scoped to workspace."""
    clauses = ["workspace_id = ?"]
    params = [workspace_id]

    if stage:
        clauses.append("pipeline_stage = ?")
        params.append(stage)
    if assigned_to:
        clauses.append("assigned_to = ?")
        params.append(assigned_to)

    where = "WHERE " + " AND ".join(clauses)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM contacts {where} ORDER BY created_at DESC",
            params,
        ).fetchall()

    results = [_row_to_profile(r) for r in rows]

    # Tag filter (tags stored as JSON array — filter in Python for simplicity)
    if tag:
        results = [c for c in results if tag in c.get("tags", [])]

    return results


def get_contact_by_phone(phone: str, workspace_id: str = DEFAULT_WORKSPACE) -> Optional[dict]:
    """Look up a contact by phone number within a workspace."""
    phone = normalize_phone(phone)
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM contacts WHERE phone = ? AND workspace_id = ?",
            (phone, workspace_id),
        ).fetchone()
    if not row:
        return None
    return _row_to_profile(row)


def contact_exists(phone: str, workspace_id: str = DEFAULT_WORKSPACE) -> bool:
    """Check if a contact with the given phone number exists in this workspace."""
    phone = normalize_phone(phone)
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM contacts WHERE phone = ? AND workspace_id = ?",
            (phone, workspace_id),
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Pipeline & scoring
# ---------------------------------------------------------------------------

def move_stage(contact_id: str, new_stage: str) -> dict:
    """Move a contact to a new pipeline stage."""
    if new_stage not in PIPELINE_STAGES:
        raise ValueError(
            f"Invalid pipeline stage '{new_stage}'. "
            f"Must be one of: {PIPELINE_STAGES}"
        )
    return update_contact(contact_id, pipeline_stage=new_stage)


def update_lead_score(contact_id: str, score: int) -> dict:
    """Set the lead score for a contact (0-100)."""
    if not isinstance(score, (int, float)) or score < 0 or score > 100:
        raise ValueError("lead_score must be between 0 and 100")
    return update_contact(contact_id, lead_score=int(score))


def add_tag(contact_id: str, tag: str) -> dict:
    """Add a tag to a contact."""
    profile = get_contact(contact_id)
    tags = profile.get("tags", [])
    if tag not in tags:
        tags.append(tag)
        return update_contact(contact_id, tags=tags)
    return profile


def remove_tag(contact_id: str, tag: str) -> dict:
    """Remove a tag from a contact."""
    profile = get_contact(contact_id)
    tags = profile.get("tags", [])
    if tag in tags:
        tags.remove(tag)
        return update_contact(contact_id, tags=tags)
    return profile


def get_pipeline_summary(workspace_id: str = DEFAULT_WORKSPACE) -> dict:
    """Return a summary of the sales pipeline for a workspace."""
    summary = {stage: {"count": 0, "total_value": 0.0} for stage in PIPELINE_STAGES}

    with get_db() as conn:
        rows = conn.execute(
            "SELECT pipeline_stage, COUNT(*) as cnt, COALESCE(SUM(deal_value), 0) as total_val "
            "FROM contacts WHERE workspace_id = ? GROUP BY pipeline_stage",
            (workspace_id,),
        ).fetchall()

    for row in rows:
        stage = row["pipeline_stage"]
        if stage in summary:
            summary[stage]["count"] = row["cnt"]
            summary[stage]["total_value"] = float(row["total_val"])

    return summary


# ---------------------------------------------------------------------------
# Conversation logging
# ---------------------------------------------------------------------------

def save_message(
    contact_id: str,
    direction: str,
    content: str,
    sent_by: str = "bot",
    wa_message_id: Optional[str] = None,
    workspace_id: str = DEFAULT_WORKSPACE,
) -> dict:
    """Save a message to the contact's conversation log."""
    now = datetime.now(IST)

    message = {
        "timestamp": now.isoformat(),
        "direction": direction,
        "content": content,
        "sent_by": sent_by,
        "wa_message_id": wa_message_id,
    }

    with get_db() as conn:
        conn.execute(
            """INSERT INTO messages
               (workspace_id, contact_id, direction, content, content_type, sent_by,
                wa_message_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (workspace_id, contact_id, direction, content, "text", sent_by,
             wa_message_id, now.isoformat()),
        )

        # Update profile stats
        if direction == "outbound":
            conn.execute(
                "UPDATE contacts SET total_messages = total_messages + 1, "
                "last_contacted_at = ? WHERE id = ?",
                (now.isoformat(), contact_id),
            )
        elif direction == "inbound":
            conn.execute(
                "UPDATE contacts SET total_messages = total_messages + 1, "
                "last_replied_at = ? WHERE id = ?",
                (now.isoformat(), contact_id),
            )

    return message


def get_today_conversation(contact_id: str) -> list:
    """Get today's messages for a contact."""
    today = datetime.now(IST).strftime("%Y-%m-%d")

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE contact_id = ? AND timestamp LIKE ? "
            "ORDER BY timestamp ASC",
            (contact_id, f"{today}%"),
        ).fetchall()

    return [_row_to_message(r) for r in rows]


def get_conversation_history(contact_id: str, days: int = 7) -> list:
    """Get conversation history for the last N days."""
    cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE contact_id = ? AND timestamp >= ? "
            "ORDER BY timestamp ASC",
            (contact_id, cutoff),
        ).fetchall()

    return [_row_to_message(r) for r in rows]


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

def import_contacts_csv(csv_content: str, workspace_id: str = DEFAULT_WORKSPACE) -> dict:
    """Parse CSV content and create contacts in bulk."""
    result = {"created": 0, "skipped": 0, "errors": []}

    reader = csv.DictReader(io.StringIO(csv_content))

    required_headers = {"name", "phone"}
    if not reader.fieldnames:
        result["errors"].append("CSV has no headers")
        return result

    headers = {h.strip().lower() for h in reader.fieldnames}
    missing = required_headers - headers
    if missing:
        result["errors"].append(f"Missing required CSV headers: {missing}")
        return result

    for row_num, row in enumerate(reader, start=2):
        row = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k is not None}

        name = row.get("name", "").strip()
        phone = row.get("phone", "").strip()

        if not name or not phone:
            result["errors"].append(f"Row {row_num}: missing name or phone")
            continue

        phone = normalize_phone(phone)

        if contact_exists(phone, workspace_id=workspace_id):
            result["skipped"] += 1
            continue

        try:
            tags_str = row.get("tags", "")
            tags = [t.strip() for t in tags_str.split(";") if t.strip()] if tags_str else []

            create_contact(
                name=name,
                phone=phone,
                company=row.get("company", "").strip() or None,
                source=row.get("source", "").strip() or None,
                tags=tags,
                workspace_id=workspace_id,
            )
            result["created"] += 1
        except Exception as e:
            result["errors"].append(f"Row {row_num} ({name}): {e}")

    logger.info(
        "CSV import complete: %d created, %d skipped, %d errors",
        result["created"], result["skipped"], len(result["errors"]),
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_profile(row) -> dict:
    """Convert a sqlite3.Row to a contact profile dict."""
    d = dict(row)
    # Map DB column names → profile field names
    profile = {
        "contact_id": d["id"],
        "workspace_id": d.get("workspace_id", DEFAULT_WORKSPACE),
        "name": d["name"],
        "phone": d["phone"],
        "company": d.get("company", ""),
        "pipeline_stage": d["pipeline_stage"],
        "deal_value": float(d.get("deal_value", 0) or 0),
        "lead_score": int(d.get("lead_score", 0) or 0),
        "assigned_to": d.get("assigned_to"),
        "tags": json.loads(d.get("tags", "[]") or "[]"),
        "source": d.get("source", ""),
        "last_contacted_at": d.get("last_contacted_at"),
        "last_replied_at": d.get("last_replied_at"),
        "total_messages": int(d.get("total_messages", 0) or 0),
        "opt_in": bool(d.get("opt_in", 0)),
        "opt_in_date": d.get("opt_in_date"),
        "created_at": d.get("created_at", ""),
        "notes": d.get("notes", ""),
        "manual_stage_override": bool(d.get("manual_stage_override", 0)),
    }
    return profile


def _row_to_message(row) -> dict:
    """Convert a sqlite3.Row to a message dict."""
    d = dict(row)
    return {
        "timestamp": d["timestamp"],
        "direction": d["direction"],
        "content": d["content"],
        "sent_by": d.get("sent_by", "bot"),
        "wa_message_id": d.get("wa_message_id"),
    }
