"""
Nazar — Contact Groups

Manage named groups of contacts for campaign targeting and organization.
Groups are workspace-scoped. A contact can belong to multiple groups.

Storage: SQLite via core/database.py (contact_groups + contact_group_members tables)
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from database import get_db, row_to_dict, rows_to_list

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_WORKSPACE = "default"

GROUP_COLORS = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#ef4444",
    "#f97316", "#eab308", "#22c55e", "#14b8a6", "#06b6d4",
    "#3b82f6", "#6b7280",
]


# ---------------------------------------------------------------------------
# Group CRUD
# ---------------------------------------------------------------------------

def create_group(
    name: str,
    description: str = "",
    color: str = "#6366f1",
    workspace_id: str = DEFAULT_WORKSPACE,
) -> dict:
    """Create a new contact group."""
    group_id = f"grp_{uuid.uuid4().hex[:8]}"
    now = datetime.now(IST).isoformat()

    with get_db() as conn:
        conn.execute(
            """INSERT INTO contact_groups (id, workspace_id, name, description, color, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (group_id, workspace_id, name, description, color, now),
        )

    logger.info("Group created: %s (%s)", name, group_id)
    return {
        "id": group_id,
        "name": name,
        "description": description,
        "color": color,
        "workspace_id": workspace_id,
        "member_count": 0,
        "created_at": now,
    }


def list_groups(workspace_id: str = DEFAULT_WORKSPACE) -> List[dict]:
    """List all groups with member counts."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT g.*, COUNT(m.contact_id) as member_count
               FROM contact_groups g
               LEFT JOIN contact_group_members m ON g.id = m.group_id
               WHERE g.workspace_id = ?
               GROUP BY g.id
               ORDER BY g.name""",
            (workspace_id,),
        ).fetchall()

    return [_row_to_group(r) for r in rows]


def get_group(group_id: str) -> Optional[dict]:
    """Get a group by ID."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT g.*, COUNT(m.contact_id) as member_count
               FROM contact_groups g
               LEFT JOIN contact_group_members m ON g.id = m.group_id
               WHERE g.id = ?
               GROUP BY g.id""",
            (group_id,),
        ).fetchone()
    return _row_to_group(row) if row else None


def update_group(group_id: str, **fields) -> dict:
    """Update group fields (name, description, color)."""
    allowed = {"name", "description", "color"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        raise ValueError("No valid fields to update")

    now = datetime.now(IST).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [now, group_id]

    with get_db() as conn:
        conn.execute(
            f"UPDATE contact_groups SET {set_clause}, updated_at = ? WHERE id = ?",
            values,
        )

    return get_group(group_id)


def delete_group(group_id: str) -> bool:
    """Delete a group and all its memberships."""
    with get_db() as conn:
        conn.execute("DELETE FROM contact_group_members WHERE group_id = ?", (group_id,))
        cursor = conn.execute("DELETE FROM contact_groups WHERE id = ?", (group_id,))
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Group membership
# ---------------------------------------------------------------------------

def add_members(group_id: str, contact_ids: List[str], workspace_id: str = DEFAULT_WORKSPACE) -> int:
    """Add contacts to a group. Returns count of newly added members."""
    now = datetime.now(IST).isoformat()
    added = 0
    with get_db() as conn:
        for cid in contact_ids:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO contact_group_members
                       (group_id, contact_id, workspace_id, added_at)
                       VALUES (?, ?, ?, ?)""",
                    (group_id, cid, workspace_id, now),
                )
                added += 1
            except Exception:
                pass
    return added


def remove_members(group_id: str, contact_ids: List[str]) -> int:
    """Remove contacts from a group. Returns count removed."""
    removed = 0
    with get_db() as conn:
        for cid in contact_ids:
            cursor = conn.execute(
                "DELETE FROM contact_group_members WHERE group_id = ? AND contact_id = ?",
                (group_id, cid),
            )
            removed += cursor.rowcount
    return removed


def get_group_members(group_id: str) -> List[dict]:
    """Get all contacts in a group (with contact details)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT c.*, m.added_at as group_added_at
               FROM contacts c
               INNER JOIN contact_group_members m ON c.id = m.contact_id
               WHERE m.group_id = ?
               ORDER BY c.name""",
            (group_id,),
        ).fetchall()
    return rows_to_list(rows)


def get_contact_groups(contact_id: str) -> List[dict]:
    """Get all groups a contact belongs to."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT g.*, m.added_at as joined_at
               FROM contact_groups g
               INNER JOIN contact_group_members m ON g.id = m.group_id
               WHERE m.contact_id = ?
               ORDER BY g.name""",
            (contact_id,),
        ).fetchall()
    return [_row_to_group(r) for r in rows]


def get_contacts_by_group_ids(group_ids: List[str]) -> List[str]:
    """Get unique contact IDs across multiple groups."""
    if not group_ids:
        return []
    placeholders = ",".join("?" for _ in group_ids)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT contact_id FROM contact_group_members WHERE group_id IN ({placeholders})",
            group_ids,
        ).fetchall()
    return [r["contact_id"] for r in rows]


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _row_to_group(row) -> dict:
    """Convert a DB row to a group dict."""
    if row is None:
        return None
    d = dict(row)
    return {
        "id": d["id"],
        "name": d["name"],
        "description": d.get("description", ""),
        "color": d.get("color", "#6366f1"),
        "workspace_id": d.get("workspace_id", DEFAULT_WORKSPACE),
        "member_count": d.get("member_count", 0),
        "created_at": d.get("created_at", ""),
        "updated_at": d.get("updated_at"),
    }
