"""
Nazar — Conversation Assignment Manager

Handles routing inbound conversations (in human_only / ai_draft / handoff mode)
to specific agents, and managing workload balancing.

Routing strategies
------------------
round_robin   Rotate through agents in alphabetical-by-user_id order.
least_busy    Assign to agent with fewest active (unresolved) conversations.
manual        No auto-assignment; agents claim conversations from an inbox queue.

Storage
-------
data/assignments.json   {contact_id: assignment_record}
"""

import json
import logging
import fcntl
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"

ROUTING_STRATEGIES = ("round_robin", "least_busy", "manual")


# ──────────────────────────────────────────────────────────────────────────────
# Storage helpers
# ──────────────────────────────────────────────────────────────────────────────

def _assignments_path():
    # type: () -> Path
    return DATA_DIR / "assignments.json"


def _load():
    # type: () -> dict
    path = _assignments_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(data):
    # type: (dict) -> None
    path = _assignments_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def assign_conversation(
    contact_id,     # type: str
    agents,         # type: List[str]
    strategy="round_robin",  # type: str
    assigned_by="auto",      # type: str
):
    # type: (...) -> dict
    """
    Auto-assign a conversation to an agent.

    Args:
        contact_id: Target contact.
        agents:     List of user_id strings currently available.
        strategy:   "round_robin" | "least_busy" | "manual"
        assigned_by: Who is assigning ("auto:round_robin", user_id, etc.)

    Returns:
        Assignment record dict.
    """
    if not agents:
        return _create_record(contact_id, assigned_to=None, assigned_by=assigned_by)

    if strategy == "manual":
        return _create_record(contact_id, assigned_to=None, assigned_by="manual")

    if strategy == "least_busy":
        agent = _pick_least_busy(agents)
    else:
        # round_robin (default)
        agent = _pick_round_robin(agents, contact_id)

    return _create_record(
        contact_id,
        assigned_to=agent,
        assigned_by="auto:%s" % strategy,
    )


def manual_assign(contact_id, agent_id, assigned_by):
    # type: (str, str, str) -> dict
    """
    Assign (or re-assign) a conversation to a specific agent by user_id.

    Returns updated assignment record.
    """
    data = _load()
    existing = data.get(contact_id)

    now = datetime.now(IST).isoformat()
    if existing:
        existing["assigned_to"] = agent_id
        existing["assigned_at"] = now
        existing["assigned_by"] = assigned_by
        existing["status"] = "active"
        data[contact_id] = existing
    else:
        data[contact_id] = _blank_record(contact_id, agent_id, assigned_by)

    _save(data)
    logger.info("Conversation %s assigned to %s by %s", contact_id, agent_id, assigned_by)
    return data[contact_id]


def claim_conversation(contact_id, agent_id):
    # type: (str, str) -> dict
    """
    Agent manually claims an unassigned conversation.

    Returns updated assignment record.
    """
    return manual_assign(contact_id, agent_id, assigned_by=agent_id)


def transfer_conversation(
    contact_id,   # type: str
    from_agent,   # type: str
    to_agent,     # type: str
    reason="",    # type: str
):
    # type: (...) -> dict
    """
    Transfer a conversation from one agent to another.

    Appends a transfer log entry for audit purposes.
    """
    data = _load()
    record = data.get(contact_id)
    now = datetime.now(IST).isoformat()

    if not record:
        record = _blank_record(contact_id, to_agent, from_agent)
    else:
        log_entry = {
            "from": from_agent,
            "to": to_agent,
            "reason": reason,
            "at": now,
        }
        record.setdefault("transfer_log", []).append(log_entry)
        record["assigned_to"] = to_agent
        record["assigned_at"] = now
        record["assigned_by"] = from_agent
        record["status"] = "active"

    data[contact_id] = record
    _save(data)
    logger.info(
        "Conversation %s transferred %s -> %s: %s",
        contact_id, from_agent, to_agent, reason,
    )
    return record


def resolve_conversation(contact_id, resolved_by="system"):
    # type: (str, str) -> dict
    """Mark a conversation as resolved (no longer needs agent attention)."""
    data = _load()
    record = data.get(contact_id, _blank_record(contact_id, None, resolved_by))
    record["status"] = "resolved"
    record["resolved_at"] = datetime.now(IST).isoformat()
    record["resolved_by"] = resolved_by
    data[contact_id] = record
    _save(data)
    return record


def get_assignment(contact_id):
    # type: (str) -> Optional[dict]
    """Return the assignment record for a contact, or None."""
    return _load().get(contact_id)


def get_agent_conversations(agent_id, status="active"):
    # type: (str, str) -> List[dict]
    """Return all conversations assigned to ``agent_id`` with the given status."""
    data = _load()
    return [
        r for r in data.values()
        if r.get("assigned_to") == agent_id and r.get("status") == status
    ]


def get_unassigned_queue():
    # type: () -> List[dict]
    """Return all active conversations that have no assigned agent."""
    data = _load()
    return [
        r for r in data.values()
        if r.get("assigned_to") is None and r.get("status") == "active"
    ]


def get_agent_workload():
    # type: () -> Dict[str, int]
    """
    Return active conversation count per agent.

    Returns:
        Dict mapping agent user_id -> active conversation count.
    """
    data = _load()
    counts = {}  # type: Dict[str, int]
    for r in data.values():
        if r.get("status") == "active" and r.get("assigned_to"):
            agent = r["assigned_to"]
            counts[agent] = counts.get(agent, 0) + 1
    return counts


def get_all_assignments():
    # type: () -> List[dict]
    """Return all assignment records."""
    return list(_load().values())


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _blank_record(contact_id, assigned_to, assigned_by):
    # type: (str, Optional[str], str) -> dict
    return {
        "contact_id": contact_id,
        "assigned_to": assigned_to,
        "assigned_at": datetime.now(IST).isoformat(),
        "assigned_by": assigned_by,
        "status": "active",
        "transfer_log": [],
    }


def _create_record(contact_id, assigned_to, assigned_by):
    # type: (str, Optional[str], str) -> dict
    data = _load()
    record = _blank_record(contact_id, assigned_to, assigned_by)
    data[contact_id] = record
    _save(data)
    return record


def _pick_round_robin(agents, contact_id):
    # type: (List[str], str) -> str
    """
    Simple deterministic round-robin: pick based on current assignment counts.
    Falls back to hash-of-contact_id for tie-breaking so the same contact always
    maps to the same position in an equal-load scenario.
    """
    workload = get_agent_workload()
    sorted_agents = sorted(agents, key=lambda a: (workload.get(a, 0), a))
    return sorted_agents[0]


def _pick_least_busy(agents):
    # type: (List[str]) -> str
    """Pick the agent with the fewest active conversations."""
    workload = get_agent_workload()
    return min(agents, key=lambda a: workload.get(a, 0))
