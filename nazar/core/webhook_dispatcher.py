"""
Nazar — Outbound Webhook Dispatcher

Sends real-time event notifications to external systems.
Storage: SQLite via core/database.py (webhooks table)
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from database import get_db

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

SUPPORTED_EVENTS = [
    "message.inbound", "message.outbound",
    "contact.created", "contact.stage_changed", "contact.opted_out",
    "handoff.triggered", "handoff.resolved",
    "campaign.completed",
    "draft.pending", "draft.approved",
]


# ──────────────────────────────────────────────────────────────────────────────
# Webhook management
# ──────────────────────────────────────────────────────────────────────────────

def register_webhook(url: str, events: List[str] = None, secret: str = "", name: str = "") -> dict:
    """Register a new outbound webhook endpoint."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("Webhook URL must start with http:// or https://")

    wh_id = "wh_%s" % uuid.uuid4().hex[:10]
    now = datetime.now(IST).isoformat()
    record = {
        "id": wh_id,
        "url": url,
        "events": events or ["*"],
        "secret": secret,
        "name": name or url,
        "active": True,
        "created_at": now,
        "last_triggered_at": None,
        "total_deliveries": 0,
        "failed_deliveries": 0,
    }

    with get_db() as conn:
        conn.execute(
            """INSERT INTO webhooks
               (id, url, events, secret, name, active, created_at,
                total_deliveries, failed_deliveries)
               VALUES (?, ?, ?, ?, ?, 1, ?, 0, 0)""",
            (wh_id, url, json.dumps(events or ["*"]), secret, name or url, now),
        )

    logger.info("Webhook registered: %r for events %s", url, events)
    return record


def list_webhooks(active_only: bool = False) -> List[dict]:
    """List all registered webhooks."""
    with get_db() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM webhooks WHERE active = 1"
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM webhooks").fetchall()
    return [_row_to_webhook(r) for r in rows]


def get_webhook(webhook_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM webhooks WHERE id = ?", (webhook_id,)
        ).fetchone()
    return _row_to_webhook(row) if row else None


def update_webhook(webhook_id: str, **kwargs) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM webhooks WHERE id = ?", (webhook_id,)
        ).fetchone()
        if not row:
            raise ValueError("Webhook %r not found" % webhook_id)

        allowed = {"url", "events", "secret", "name", "active"}
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k in allowed:
                if k == "events":
                    v = json.dumps(v)
                elif k == "active":
                    v = 1 if v else 0
                sets.append(f"{k} = ?")
                vals.append(v)

        if sets:
            vals.append(webhook_id)
            conn.execute(
                f"UPDATE webhooks SET {', '.join(sets)} WHERE id = ?",
                vals,
            )

    return get_webhook(webhook_id)


def delete_webhook(webhook_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM webhooks WHERE id = ?", (webhook_id,)
        )
    return cursor.rowcount > 0


# ──────────────────────────────────────────────────────────────────────────────
# Dispatch
# ──────────────────────────────────────────────────────────────────────────────

async def dispatch(event_type: str, payload: Dict[str, Any]) -> int:
    """Fire an event to all subscribed active webhook endpoints."""
    hooks = [
        h for h in list_webhooks(active_only=True)
        if "*" in h.get("events", []) or event_type in h.get("events", [])
    ]
    for hook in hooks:
        asyncio.create_task(_send(hook, event_type, payload))
    return len(hooks)


async def dispatch_test(webhook_id: str) -> dict:
    """Send a test event to verify a webhook endpoint."""
    hook = get_webhook(webhook_id)
    if not hook:
        raise ValueError("Webhook %r not found" % webhook_id)

    test_payload = {
        "test": True,
        "contact_id": "test_contact_001",
        "message": "Hello from Nazar — webhook test",
    }
    ok, status_code, error = await _send(hook, "test.ping", test_payload, record_stats=False)
    return {
        "ok": ok,
        "status_code": status_code,
        "error": error,
        "webhook_id": webhook_id,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Internal delivery
# ──────────────────────────────────────────────────────────────────────────────

async def _send(
    hook: dict,
    event_type: str,
    payload: dict,
    record_stats: bool = True,
) -> Tuple[bool, int, str]:
    """POST event to a single webhook."""
    body = {
        "event": event_type,
        "timestamp": datetime.now(IST).isoformat(),
        "data": payload,
    }
    body_str = json.dumps(body, ensure_ascii=False)
    headers = {"Content-Type": "application/json"}

    secret = hook.get("secret", "")
    if secret:
        sig = hmac.new(secret.encode(), body_str.encode(), hashlib.sha256).hexdigest()
        headers["X-Nazar-Signature"] = "sha256=%s" % sig

    status_code = 0
    error_msg = ""
    ok = False

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                hook["url"], data=body_str, headers=headers, timeout=timeout,
            ) as resp:
                status_code = resp.status
                ok = 200 <= status_code < 300
                if not ok:
                    body_text = await resp.text()
                    error_msg = "HTTP %d: %s" % (status_code, body_text[:200])
                    logger.warning("Webhook %s -> %s returned %d", hook["id"], hook["url"], status_code)
    except asyncio.TimeoutError:
        error_msg = "Request timed out after 10s"
        logger.warning("Webhook %s timed out for event %r", hook["id"], event_type)
    except Exception as e:
        error_msg = str(e)[:200]
        logger.error("Webhook %s dispatch error: %s", hook["id"], e)

    if record_stats:
        try:
            with get_db() as conn:
                conn.execute(
                    """UPDATE webhooks SET
                       last_triggered_at = ?,
                       total_deliveries = total_deliveries + 1,
                       failed_deliveries = failed_deliveries + CASE WHEN ? THEN 0 ELSE 1 END
                       WHERE id = ?""",
                    (datetime.now(IST).isoformat(), 1 if ok else 0, hook["id"]),
                )
        except Exception:
            pass

    return ok, status_code, error_msg


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _row_to_webhook(row) -> dict:
    d = dict(row)
    return {
        "id": d["id"],
        "url": d["url"],
        "events": json.loads(d.get("events", '["*"]') or '["*"]'),
        "secret": d.get("secret", ""),
        "name": d.get("name", ""),
        "active": bool(d.get("active", 1)),
        "created_at": d.get("created_at", ""),
        "last_triggered_at": d.get("last_triggered_at"),
        "total_deliveries": d.get("total_deliveries", 0),
        "failed_deliveries": d.get("failed_deliveries", 0),
    }
