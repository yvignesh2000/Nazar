"""
Nazar — Contact Segmentation Engine

Build complex audience segments for targeted campaign sends.
Saved segments stored in SQLite via core/database.py.
"""

import json
import logging
import uuid as _uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from database import get_db

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Operator registry
# ---------------------------------------------------------------------------

def _op_eq(a, b):       return a == b
def _op_neq(a, b):      return a != b
def _op_gt(a, b):       return float(a) > float(b)   if a is not None else False
def _op_gte(a, b):      return float(a) >= float(b)  if a is not None else False
def _op_lt(a, b):       return float(a) < float(b)   if a is not None else False
def _op_lte(a, b):      return float(a) <= float(b)  if a is not None else False
def _op_in(a, b):       return a in b if isinstance(b, (list, tuple)) else str(a) in str(b)
def _op_not_in(a, b):   return a not in b if isinstance(b, (list, tuple)) else str(a) not in str(b)
def _op_contains(a, b): return b in a if isinstance(a, (list, str)) else False
def _op_not_contains(a, b): return b not in a if isinstance(a, (list, str)) else True
def _op_starts_with(a, b): return str(a).startswith(str(b)) if a is not None else False
def _op_exists(a, b):   return a is not None and a != "" and a != []
def _op_not_exists(a, b): return a is None or a == "" or a == []

OPERATORS = {
    "eq": _op_eq, "neq": _op_neq,
    "gt": _op_gt, "gte": _op_gte, "lt": _op_lt, "lte": _op_lte,
    "in": _op_in, "not_in": _op_not_in,
    "contains": _op_contains, "not_contains": _op_not_contains,
    "starts_with": _op_starts_with,
    "exists": _op_exists, "not_exists": _op_not_exists,
}

SEGMENTABLE_FIELDS = {
    "pipeline_stage": "Pipeline Stage",
    "lead_score": "Lead Score",
    "tags": "Tags",
    "source": "Lead Source",
    "company": "Company",
    "deal_value": "Deal Value",
    "last_contact_days": "Days Since Last Contact",
    "created_days_ago": "Days Since Created",
    "opt_out": "Opted Out",
    "reply_mode": "Reply Mode",
}


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_segment(contacts: List[dict], segment: dict) -> List[dict]:
    """Filter contacts to those matching the segment definition."""
    conditions = segment.get("conditions", [])
    logic = segment.get("logic", "AND").upper()

    if not conditions:
        return [c for c in contacts if not c.get("opt_out")]

    result = []
    for contact in contacts:
        if contact.get("opt_out"):
            continue

        matches = []
        for cond in conditions:
            try:
                matches.append(_evaluate_condition(contact, cond))
            except Exception as e:
                logger.debug("Condition eval error: %s", e)
                matches.append(False)

        if logic == "OR":
            if any(matches):
                result.append(contact)
        else:
            if all(matches):
                result.append(contact)

    return result


def _evaluate_condition(contact: dict, condition: dict) -> bool:
    field_name = condition.get("field", "")
    operator = condition.get("operator", "eq")
    value = condition.get("value")

    actual = _resolve_field(contact, field_name)
    op_func = OPERATORS.get(operator)
    if op_func is None:
        return False

    try:
        return bool(op_func(actual, value))
    except (TypeError, ValueError, AttributeError):
        return False


def _resolve_field(contact: dict, field_name: str) -> Any:
    if field_name == "last_contact_days":
        ts = contact.get("last_contacted_at") or contact.get("last_replied_at")
        return _days_since(ts)
    if field_name == "created_days_ago":
        return _days_since(contact.get("created_at"))
    return contact.get(field_name)


def _days_since(iso_ts: Optional[str]) -> Optional[int]:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return (datetime.now(IST) - dt).days
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Segment preview
# ---------------------------------------------------------------------------

def preview_segment(contacts: List[dict], segment: dict, sample_size: int = 5) -> dict:
    matched = evaluate_segment(contacts, segment)
    sample = [
        {
            "contact_id": c.get("contact_id", ""),
            "name": c.get("name", ""),
            "pipeline_stage": c.get("pipeline_stage", ""),
            "lead_score": c.get("lead_score", 0),
        }
        for c in matched[:sample_size]
    ]
    return {"count": len(matched), "sample": sample, "segment": segment}


# ---------------------------------------------------------------------------
# Saved segments (SQLite)
# ---------------------------------------------------------------------------

def save_segment(name: str, segment: dict) -> dict:
    seg_id = "seg_%s" % _uuid.uuid4().hex[:8]
    now = datetime.now(IST).isoformat()
    record = {
        "id": seg_id,
        "name": name,
        "segment": segment,
        "created_at": now,
    }
    with get_db() as conn:
        conn.execute(
            "INSERT INTO segments (id, name, segment, created_at) VALUES (?, ?, ?, ?)",
            (seg_id, name, json.dumps(segment), now),
        )
    return record


def list_segments() -> List[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM segments ORDER BY created_at DESC").fetchall()
    return [_row_to_segment(r) for r in rows]


def get_segment(segment_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM segments WHERE id = ?", (segment_id,)
        ).fetchone()
    return _row_to_segment(row) if row else None


def delete_segment(segment_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM segments WHERE id = ?", (segment_id,)
        )
    return cursor.rowcount > 0


def _row_to_segment(row) -> dict:
    d = dict(row)
    return {
        "id": d["id"],
        "name": d["name"],
        "segment": json.loads(d.get("segment", "{}") or "{}"),
        "created_at": d.get("created_at", ""),
    }
