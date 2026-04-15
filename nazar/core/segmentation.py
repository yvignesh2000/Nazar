"""
Nazar — Contact Segmentation Engine

Build complex audience segments for targeted campaign sends.

Segment definition (JSON-serialisable dict)::

    {
        "conditions": [
            {"field": "stage",            "operator": "in",      "value": ["Qualified", "Proposal"]},
            {"field": "lead_score",       "operator": "gte",     "value": 60},
            {"field": "tags",             "operator": "contains","value": "enterprise"},
            {"field": "last_contact_days","operator": "gte",     "value": 7},
            {"field": "opt_out",          "operator": "eq",      "value": false},
        ],
        "logic": "AND"
    }

Supported operators
-------------------
eq, neq           equality / inequality
gt, gte, lt, lte  numeric comparisons
in, not_in        membership in a list  (field value is IN the provided list)
contains          list/string contains the value
not_contains      list/string does NOT contain the value
starts_with       string starts with value
exists            field is non-None and non-empty
not_exists        field is None or empty string

Computed fields
---------------
last_contact_days   Integer days since last_contacted_at / last_replied_at
created_days_ago    Integer days since created_at
"""

import json
import logging
import fcntl
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    "eq":           _op_eq,
    "neq":          _op_neq,
    "gt":           _op_gt,
    "gte":          _op_gte,
    "lt":           _op_lt,
    "lte":          _op_lte,
    "in":           _op_in,
    "not_in":       _op_not_in,
    "contains":     _op_contains,
    "not_contains": _op_not_contains,
    "starts_with":  _op_starts_with,
    "exists":       _op_exists,
    "not_exists":   _op_not_exists,
}  # type: Dict[str, Any]

# Human-readable labels for the UI
SEGMENTABLE_FIELDS = {
    "pipeline_stage":     "Pipeline Stage",
    "lead_score":         "Lead Score",
    "tags":               "Tags",
    "source":             "Lead Source",
    "company":            "Company",
    "deal_value":         "Deal Value",
    "last_contact_days":  "Days Since Last Contact",
    "created_days_ago":   "Days Since Created",
    "opt_out":            "Opted Out",
    "reply_mode":         "Reply Mode",
}  # type: Dict[str, str]


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_segment(contacts, segment):
    # type: (List[dict], dict) -> List[dict]
    """
    Filter ``contacts`` to those matching the segment definition.

    Args:
        contacts: List of contact dicts as returned by ``list_contacts()``.
        segment:  Segment definition dict (see module docstring).

    Returns:
        Filtered list — never mutates the input.
    """
    conditions = segment.get("conditions", [])
    logic = segment.get("logic", "AND").upper()

    if not conditions:
        return [c for c in contacts if not c.get("opt_out")]

    result = []
    for contact in contacts:
        # Opted-out contacts are always excluded regardless of segment
        if contact.get("opt_out"):
            continue

        matches = []
        for cond in conditions:
            try:
                matches.append(_evaluate_condition(contact, cond))
            except Exception as e:
                logger.debug("Condition eval error for contact %s: %s", contact.get("contact_id"), e)
                matches.append(False)

        if logic == "OR":
            if any(matches):
                result.append(contact)
        else:  # AND (default)
            if all(matches):
                result.append(contact)

    return result


def _evaluate_condition(contact, condition):
    # type: (dict, dict) -> bool
    """Evaluate a single condition dict against a contact."""
    field_name = condition.get("field", "")
    operator = condition.get("operator", "eq")
    value = condition.get("value")

    # Resolve computed fields
    actual = _resolve_field(contact, field_name)

    op_func = OPERATORS.get(operator)
    if op_func is None:
        logger.warning("Unknown segment operator: %r", operator)
        return False

    try:
        return bool(op_func(actual, value))
    except (TypeError, ValueError, AttributeError) as e:
        logger.debug("Operator %r failed on (%r, %r): %s", operator, actual, value, e)
        return False


def _resolve_field(contact, field_name):
    # type: (dict, str) -> Any
    """Return the contact field value, computing derived fields as needed."""
    if field_name == "last_contact_days":
        ts = contact.get("last_contacted_at") or contact.get("last_replied_at")
        return _days_since(ts)

    if field_name == "created_days_ago":
        return _days_since(contact.get("created_at"))

    return contact.get(field_name)


def _days_since(iso_ts):
    # type: (Optional[str]) -> Optional[int]
    """Return integer days since an ISO timestamp, or None if missing."""
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
# Segment preview helper
# ---------------------------------------------------------------------------

def preview_segment(contacts, segment, sample_size=5):
    # type: (List[dict], dict, int) -> dict
    """
    Return a preview of contacts matching the segment.

    Args:
        contacts:    Full contact list.
        segment:     Segment definition.
        sample_size: How many sample contacts to return.

    Returns:
        Dict with ``count``, ``sample`` (list of contact stubs), and ``segment``.
    """
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
    return {
        "count": len(matched),
        "sample": sample,
        "segment": segment,
    }


# ---------------------------------------------------------------------------
# Saved segments (persisted to data/segments.json)
# ---------------------------------------------------------------------------

_SEGMENTS_PATH = Path(__file__).parent.parent / "data" / "segments.json"


def _load_segments():
    # type: () -> dict
    if _SEGMENTS_PATH.exists():
        try:
            return json.loads(_SEGMENTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_segments(data):
    # type: (dict) -> None
    _SEGMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = _SEGMENTS_PATH.with_suffix(".lock")
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        _SEGMENTS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_segment(name, segment):
    # type: (str, dict) -> dict
    """Persist a named segment for reuse in future campaigns."""
    import uuid as _uuid
    data = _load_segments()
    seg_id = "seg_%s" % _uuid.uuid4().hex[:8]
    record = {
        "id": seg_id,
        "name": name,
        "segment": segment,
        "created_at": datetime.now(IST).isoformat(),
    }
    data[seg_id] = record
    _save_segments(data)
    return record


def list_segments():
    # type: () -> List[dict]
    """List all saved segments."""
    return list(_load_segments().values())


def get_segment(segment_id):
    # type: (str) -> Optional[dict]
    return _load_segments().get(segment_id)


def delete_segment(segment_id):
    # type: (str) -> bool
    data = _load_segments()
    if segment_id in data:
        del data[segment_id]
        _save_segments(data)
        return True
    return False
