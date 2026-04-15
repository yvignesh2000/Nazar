"""
Nazar — Outbound Webhook Dispatcher

Sends real-time event notifications to external systems (Zapier, CRM, Slack,
custom HTTP endpoints). Allows operators to integrate Nazar into their existing
tooling without polling.

Supported events
----------------
message.inbound         Customer sent a message
message.outbound        Bot / agent sent a reply
contact.created         New contact created
contact.stage_changed   Contact moved in the pipeline
contact.opted_out       Contact opted out (STOP)
handoff.triggered       AI -> human handoff initiated
handoff.resolved        Handoff resolved (bot resumed)
campaign.completed      Campaign finished sending
draft.pending           AI draft awaiting human approval
draft.approved          AI draft approved and sent

Webhook record schema::

    {
        "id":       str,
        "url":      str,     HTTPS endpoint to POST to
        "events":   list,    ["*"] = all events; else specific event names
        "secret":   str,     HMAC signing secret (empty = no signature)
        "name":     str,     human label
        "active":   bool,
        "created_at": ISO str
    }

Delivery
--------
- Fire-and-forget asyncio tasks — never blocks the main flow
- 10-second per-request timeout
- HMAC-SHA256 signature header: ``X-Nazar-Signature: sha256=<hex>``
- Non-2xx responses are logged as warnings (no retry in V1)

Storage
-------
data/webhooks.json
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
import fcntl
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"

SUPPORTED_EVENTS = [
    "message.inbound",
    "message.outbound",
    "contact.created",
    "contact.stage_changed",
    "contact.opted_out",
    "handoff.triggered",
    "handoff.resolved",
    "campaign.completed",
    "draft.pending",
    "draft.approved",
]


# ──────────────────────────────────────────────────────────────────────────────
# Storage helpers
# ──────────────────────────────────────────────────────────────────────────────

def _path():
    # type: () -> Path
    return DATA_DIR / "webhooks.json"


def _load():
    # type: () -> dict
    p = _path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(data):
    # type: (dict) -> None
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = p.with_suffix(".lock")
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Webhook management
# ──────────────────────────────────────────────────────────────────────────────

def register_webhook(
    url,            # type: str
    events=None,    # type: Optional[List[str]]
    secret="",      # type: str
    name="",        # type: str
):
    # type: (...) -> dict
    """Register a new outbound webhook endpoint."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("Webhook URL must start with http:// or https://")

    wh_id = "wh_%s" % uuid.uuid4().hex[:10]
    record = {
        "id": wh_id,
        "url": url,
        "events": events or ["*"],
        "secret": secret,
        "name": name or url,
        "active": True,
        "created_at": datetime.now(IST).isoformat(),
        "last_triggered_at": None,
        "total_deliveries": 0,
        "failed_deliveries": 0,
    }
    data = _load()
    data[wh_id] = record
    _save(data)
    logger.info("Webhook registered: %r for events %s", url, events)
    return record


def list_webhooks(active_only=False):
    # type: (bool) -> List[dict]
    """List all registered webhooks."""
    hooks = list(_load().values())
    if active_only:
        hooks = [h for h in hooks if h.get("active")]
    return hooks


def get_webhook(webhook_id):
    # type: (str) -> Optional[dict]
    return _load().get(webhook_id)


def update_webhook(webhook_id, **kwargs):
    # type: (str, **Any) -> dict
    data = _load()
    if webhook_id not in data:
        raise ValueError("Webhook %r not found" % webhook_id)
    allowed = {"url", "events", "secret", "name", "active"}
    for k, v in kwargs.items():
        if k in allowed:
            data[webhook_id][k] = v
    _save(data)
    return data[webhook_id]


def delete_webhook(webhook_id):
    # type: (str) -> bool
    data = _load()
    if webhook_id in data:
        del data[webhook_id]
        _save(data)
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Dispatch
# ──────────────────────────────────────────────────────────────────────────────

async def dispatch(event_type, payload):
    # type: (str, Dict[str, Any]) -> int
    """
    Fire an event to all subscribed active webhook endpoints.

    Returns:
        Number of webhooks targeted (delivery is async; errors are logged).
    """
    hooks = [
        h for h in list_webhooks(active_only=True)
        if "*" in h.get("events", []) or event_type in h.get("events", [])
    ]

    for hook in hooks:
        asyncio.create_task(_send(hook, event_type, payload))

    return len(hooks)


async def dispatch_test(webhook_id):
    # type: (str) -> dict
    """Send a test event to verify a webhook endpoint is reachable."""
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
    hook,               # type: dict
    event_type,         # type: str
    payload,            # type: dict
    record_stats=True,  # type: bool
):
    # type: (...) -> Tuple[bool, int, str]
    """POST event to a single webhook. Returns (ok, status_code, error_msg)."""
    body = {
        "event": event_type,
        "timestamp": datetime.now(IST).isoformat(),
        "data": payload,
    }
    body_str = json.dumps(body, ensure_ascii=False)

    headers = {"Content-Type": "application/json"}  # type: Dict[str, str]

    # HMAC signature
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
                hook["url"],
                data=body_str,
                headers=headers,
                timeout=timeout,
            ) as resp:
                status_code = resp.status
                ok = 200 <= status_code < 300
                if not ok:
                    body_text = await resp.text()
                    error_msg = "HTTP %d: %s" % (status_code, body_text[:200])
                    logger.warning(
                        "Webhook %s -> %s returned %d",
                        hook["id"], hook["url"], status_code,
                    )
    except asyncio.TimeoutError:
        error_msg = "Request timed out after 10s"
        logger.warning("Webhook %s timed out for event %r", hook["id"], event_type)
    except Exception as e:
        error_msg = str(e)[:200]
        logger.error("Webhook %s dispatch error: %s", hook["id"], e)

    # Update delivery stats
    if record_stats:
        try:
            data = _load()
            if hook["id"] in data:
                data[hook["id"]]["last_triggered_at"] = datetime.now(IST).isoformat()
                data[hook["id"]]["total_deliveries"] = data[hook["id"]].get("total_deliveries", 0) + 1
                if not ok:
                    data[hook["id"]]["failed_deliveries"] = data[hook["id"]].get("failed_deliveries", 0) + 1
                _save(data)
        except Exception:
            pass

    return ok, status_code, error_msg
