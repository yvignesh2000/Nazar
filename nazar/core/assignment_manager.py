"""
Nazar — Conversation Assignment Manager

Handles routing inbound conversations to agents and workload balancing.
Storage: SQLite via core/database.py (assignments table)
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from database import get_db

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

ROUTING_STRATEGIES = ("round_robin", "least_busy", "manual")


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def assign_conversation(
    contact_id: str,
    agents: List[str],
    strategy: str = "round_robin",
    assigned_by: str = "auto",
) -> dict:
    """Auto-assign a conversation to an agent."""
    if not agents:
        return _create_record(contact_id, assigned_to=None, assigned_by=assigned_by)

    if strategy == "manual":
        return _create_record(contact_id, assigned_to=None, assigned_by="manual")

    if strategy == "least_busy":
        agent = _pick_least_busy(agents)
    else:
        agent = _pick_round_robin(agents, contact_id)

    return _create_record(contact_id, assigned_to=agent, assigned_by=f"auto:{strategy}")


def manual_assign(contact_id: str, agent_id: str, assigned_by: str) -> dict:
    """Assign (or re-assign) a conversation to a specific agent."""
    now = datetime.now(IST).isoformat()

    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM assignments WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE assignments SET assigned_to = ?, assigned_at = ?,
                   assigned_by = ?, status = 'active' WHERE contact_id = ?""",
                (agent_id, now, assigned_by, contact_id),
            )
        else:
            conn.execute(
                """INSERT INTO assignments
                   (contact_id, assigned_to, assigned_at, assigned_by, status, transfer_log)
                   VALUES (?, ?, ?, ?, 'active', '[]')""",
                (contact_id, agent_id, now, assigned_by),
            )

    logger.info("Conversation %s assigned to %s by %s", contact_id, agent_id, assigned_by)
    return _get_record(contact_id)


def claim_conversation(contact_id: str, agent_id: str) -> dict:
    """Agent manually claims an unassigned conversation."""
    return manual_assign(contact_id, agent_id, assigned_by=agent_id)


def transfer_conversation(
    contact_id: str,
    from_agent: str,
    to_agent: str,
    reason: str = "",
) -> dict:
    """Transfer a conversation from one agent to another."""
    now = datetime.now(IST).isoformat()

    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM assignments WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()

        log_entry = {"from": from_agent, "to": to_agent, "reason": reason, "at": now}

        if existing:
            transfer_log = json.loads(existing["transfer_log"] or "[]")
            transfer_log.append(log_entry)
            conn.execute(
                """UPDATE assignments SET assigned_to = ?, assigned_at = ?,
                   assigned_by = ?, status = 'active', transfer_log = ?
                   WHERE contact_id = ?""",
                (to_agent, now, from_agent, json.dumps(transfer_log), contact_id),
            )
        else:
            conn.execute(
                """INSERT INTO assignments
                   (contact_id, assigned_to, assigned_at, assigned_by, status, transfer_log)
                   VALUES (?, ?, ?, ?, 'active', ?)""",
                (contact_id, to_agent, now, from_agent, json.dumps([log_entry])),
            )

    logger.info(
        "Conversation %s transferred %s -> %s: %s",
        contact_id, from_agent, to_agent, reason,
    )
    return _get_record(contact_id)


def resolve_conversation(contact_id: str, resolved_by: str = "system") -> dict:
    """Mark a conversation as resolved."""
    now = datetime.now(IST).isoformat()

    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM assignments WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE assignments SET status = 'resolved',
                   resolved_at = ?, resolved_by = ? WHERE contact_id = ?""",
                (now, resolved_by, contact_id),
            )
        else:
            conn.execute(
                """INSERT INTO assignments
                   (contact_id, assigned_to, assigned_at, assigned_by, status,
                    resolved_at, resolved_by, transfer_log)
                   VALUES (?, NULL, ?, ?, 'resolved', ?, ?, '[]')""",
                (contact_id, now, resolved_by, now, resolved_by),
            )

    return _get_record(contact_id)


def get_assignment(contact_id: str) -> Optional[dict]:
    """Return the assignment record for a contact, or None."""
    return _get_record(contact_id)


def get_agent_conversations(agent_id: str, status: str = "active") -> List[dict]:
    """Return all conversations assigned to an agent."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM assignments WHERE assigned_to = ? AND status = ?",
            (agent_id, status),
        ).fetchall()
    return [_row_to_assignment(r) for r in rows]


def get_unassigned_queue() -> List[dict]:
    """Return all active conversations that have no assigned agent."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM assignments WHERE assigned_to IS NULL AND status = 'active'"
        ).fetchall()
    return [_row_to_assignment(r) for r in rows]


def get_agent_workload() -> Dict[str, int]:
    """Return active conversation count per agent."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT assigned_to, COUNT(*) as cnt FROM assignments "
            "WHERE status = 'active' AND assigned_to IS NOT NULL "
            "GROUP BY assigned_to"
        ).fetchall()
    return {r["assigned_to"]: r["cnt"] for r in rows}


def get_all_assignments() -> List[dict]:
    """Return all assignment records."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM assignments").fetchall()
    return [_row_to_assignment(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_record(contact_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM assignments WHERE contact_id = ?",
            (contact_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_assignment(row)


def _row_to_assignment(row) -> dict:
    d = dict(row)
    return {
        "contact_id": d["contact_id"],
        "assigned_to": d.get("assigned_to"),
        "assigned_at": d.get("assigned_at", ""),
        "assigned_by": d.get("assigned_by", ""),
        "status": d.get("status", "active"),
        "transfer_log": json.loads(d.get("transfer_log", "[]") or "[]"),
        "resolved_at": d.get("resolved_at"),
        "resolved_by": d.get("resolved_by"),
    }


def _create_record(contact_id: str, assigned_to: Optional[str], assigned_by: str) -> dict:
    now = datetime.now(IST).isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO assignments
               (contact_id, assigned_to, assigned_at, assigned_by, status, transfer_log)
               VALUES (?, ?, ?, ?, 'active', '[]')""",
            (contact_id, assigned_to, now, assigned_by),
        )
    return _get_record(contact_id)


def _pick_round_robin(agents: List[str], contact_id: str) -> str:
    workload = get_agent_workload()
    sorted_agents = sorted(agents, key=lambda a: (workload.get(a, 0), a))
    return sorted_agents[0]


def _pick_least_busy(agents: List[str]) -> str:
    workload = get_agent_workload()
    return min(agents, key=lambda a: workload.get(a, 0))
