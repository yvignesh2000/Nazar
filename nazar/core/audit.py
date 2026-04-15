"""
Nazar — Audit Log System

Records every state-changing action for compliance, debugging, and accountability.
Uses append-only JSONL files (one per day) — same pattern as analytics.

GDPR note: Audit records use resource IDs (contact_id, campaign_id, user_id) —
NEVER raw PII like names, phone numbers, or email addresses.

Log entry schema::

    {
        "id":            str,   unique entry id
        "actor_id":      str,   user_id or "system" or "webhook"
        "action":        str,   e.g. "contact.stage_changed"
        "resource_type": str,   "contact" | "campaign" | "draft" | "config" | ...
        "resource_id":   str,   e.g. the contact_id or campaign_id
        "details":       dict,  action-specific payload (no PII)
        "timestamp":     ISO str
    }

Action taxonomy::

    contact.created           contact.updated           contact.deleted
    contact.stage_changed     contact.tag_added         contact.tag_removed
    contact.opted_out         contact.opted_in
    campaign.created          campaign.sent             campaign.cancelled
    draft.created             draft.approved            draft.rejected
    draft.edited              draft.regenerated
    handoff.triggered         handoff.resumed
    reply_mode.changed
    config.updated
    user.created              user.deleted              user.password_changed
    user.login                user.logout
    template.created          template.updated          template.deleted
    kb.updated
    webhook.registered        webhook.deleted
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data" / "audit"


# ──────────────────────────────────────────────────────────────────────────────
# Storage
# ──────────────────────────────────────────────────────────────────────────────

def _log_path(date_str=None):
    # type: (Optional[str]) -> Path
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if date_str is None:
        date_str = datetime.now(IST).strftime("%Y-%m-%d")
    return DATA_DIR / ("%s.jsonl" % date_str)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def log_audit(
    action,          # type: str
    resource_type,   # type: str
    resource_id="",  # type: str
    actor_id="system",  # type: str
    details=None,    # type: Optional[dict]
):
    # type: (...) -> dict
    """
    Append an audit log entry.

    Args:
        action:        Dot-separated action name (e.g. "contact.stage_changed").
        resource_type: Type of resource affected ("contact", "campaign", ...).
        resource_id:   ID of the affected resource. Must NOT be a raw phone/email.
        actor_id:      user_id of the person/system that triggered the action.
        details:       Extra context dict. Must NOT contain PII.

    Returns:
        The written log entry.
    """
    entry = {
        "id": uuid.uuid4().hex[:16],
        "actor_id": actor_id or "system",
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id or "",
        "details": details or {},
        "timestamp": datetime.now(IST).isoformat(),
    }
    try:
        with _log_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error("Audit log write failed: %s", e)
    return entry


def get_audit_log(
    days=7,             # type: int
    action=None,        # type: Optional[str]
    resource_type=None, # type: Optional[str]
    actor_id=None,      # type: Optional[str]
    limit=500,          # type: int
):
    # type: (...) -> List[dict]
    """
    Read and filter audit log entries.

    Args:
        days:          How many past days to scan.
        action:        Filter by action prefix (e.g. "contact" matches all contact.*)
        resource_type: Filter by resource type.
        actor_id:      Filter by actor.
        limit:         Maximum number of entries to return (most recent first).

    Returns:
        List of matching log entries, newest first.
    """
    entries = []  # type: List[dict]
    now = datetime.now(IST)

    for day_offset in range(days):
        date_str = (now - timedelta(days=day_offset)).strftime("%Y-%m-%d")
        path = _log_path(date_str)
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entries.append(entry)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Audit log read error for %s: %s", date_str, e)

    # Apply filters
    if action:
        entries = [e for e in entries if e.get("action", "").startswith(action)]
    if resource_type:
        entries = [e for e in entries if e.get("resource_type") == resource_type]
    if actor_id:
        entries = [e for e in entries if e.get("actor_id") == actor_id]

    # Sort newest first
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return entries[:limit]


def get_audit_stats(days=30):
    # type: (int) -> dict
    """Return aggregate counts per action type for the given period."""
    entries = get_audit_log(days=days, limit=10_000)
    counts = {}  # type: Dict[str, int]
    for e in entries:
        act = e.get("action", "unknown")
        counts[act] = counts.get(act, 0) + 1
    return {
        "total_entries": len(entries),
        "by_action": counts,
        "days_scanned": days,
    }
