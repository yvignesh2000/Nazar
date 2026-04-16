"""
Nazar — Audit Log System

Records every state-changing action for compliance, debugging, and accountability.
Storage: SQLite via core/database.py (audit_log table)
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from database import get_db

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def log_audit(
    action: str,
    resource_type: str,
    resource_id: str = "",
    actor_id: str = "system",
    details: Optional[dict] = None,
) -> dict:
    """Append an audit log entry."""
    entry_id = uuid.uuid4().hex[:16]
    now = datetime.now(IST).isoformat()

    entry = {
        "id": entry_id,
        "actor_id": actor_id or "system",
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id or "",
        "details": details or {},
        "timestamp": now,
    }

    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO audit_log
                   (id, actor_id, action, resource_type, resource_id, details, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (entry_id, actor_id or "system", action, resource_type,
                 resource_id or "", json.dumps(details or {}), now),
            )
    except Exception as e:
        logger.error("Audit log write failed: %s", e)

    return entry


def get_audit_log(
    days: int = 7,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    limit: int = 500,
) -> List[dict]:
    """Read and filter audit log entries."""
    cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()

    clauses = ["timestamp >= ?"]
    params = [cutoff]

    if action:
        clauses.append("action LIKE ?")
        params.append(f"{action}%")
    if resource_type:
        clauses.append("resource_type = ?")
        params.append(resource_type)
    if actor_id:
        clauses.append("actor_id = ?")
        params.append(actor_id)

    where = "WHERE " + " AND ".join(clauses)
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM audit_log {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()

    return [_row_to_entry(r) for r in rows]


def get_audit_stats(days: int = 30) -> dict:
    """Return aggregate counts per action type for the given period."""
    cutoff = (datetime.now(IST) - timedelta(days=days)).isoformat()

    with get_db() as conn:
        rows = conn.execute(
            "SELECT action, COUNT(*) as cnt FROM audit_log "
            "WHERE timestamp >= ? GROUP BY action",
            (cutoff,),
        ).fetchall()

        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM audit_log WHERE timestamp >= ?",
            (cutoff,),
        ).fetchone()["cnt"]

    counts = {r["action"]: r["cnt"] for r in rows}

    return {
        "total_entries": total,
        "by_action": counts,
        "days_scanned": days,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Internal
# ──────────────────────────────────────────────────────────────────────────────

def _row_to_entry(row) -> dict:
    d = dict(row)
    return {
        "id": d["id"],
        "actor_id": d.get("actor_id", "system"),
        "action": d["action"],
        "resource_type": d["resource_type"],
        "resource_id": d.get("resource_id", ""),
        "details": json.loads(d.get("details", "{}") or "{}"),
        "timestamp": d["timestamp"],
    }
