"""
Nazar — Billing & Plan Manager

Handles:
- Plan definitions (Starter / Growth / Pro / Enterprise)
- Usage metering (contacts, messages, campaigns, AI calls)
- Plan limit enforcement (hard + soft limits)
- Upgrade / downgrade tracking
- Trial period management
- Payment status tracking (Stripe webhook integration ready)

Plans:
   starter    — 1 user, 200 contacts, 500 AI messages/mo, 2 campaigns/mo
   growth     — 5 users, 2,000 contacts, 5,000 AI messages/mo, 20 campaigns/mo
   pro        — 20 users, 20,000 contacts, unlimited AI messages, unlimited campaigns
  enterprise — unlimited everything + SLA + dedicated support

Storage: data/billing/
  plans.json        — plan definitions
  subscriptions.json — per-workspace subscription state
  usage.json        — monthly usage counters per workspace
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data" / "billing"

# ---------------------------------------------------------------------------
# Plan definitions
# ---------------------------------------------------------------------------

PLANS = {
    "starter": {
        "id": "starter",
        "name": "Starter",
        "price_inr": 1999,
        "price_usd": 24,
        "billing_cycle": "monthly",
        "limits": {
            "contacts": 200,
            "ai_messages_per_month": 500,
            "campaigns_per_month": 2,
            "team_members": 1,
            "whatsapp_numbers": 1,
        },
        "features": [
            "AI conversation bot",
            "Pipeline management",
            "Basic analytics",
            "1 WhatsApp number",
            "Email support",
        ],
        "trial_days": 14,
    },
    "growth": {
        "id": "growth",
        "name": "Growth",
        "price_inr": 5999,
        "price_usd": 72,
        "billing_cycle": "monthly",
        "limits": {
            "contacts": 2000,
            "ai_messages_per_month": 5000,
            "campaigns_per_month": 20,
            "team_members": 5,
            "whatsapp_numbers": 2,
        },
        "features": [
            "Everything in Starter",
            "Smart handoff detection",
            "Advanced analytics",
            "Campaign management",
            "Template library",
            "Team roles",
            "Priority support",
        ],
        "trial_days": 14,
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "price_inr": 14999,
        "price_usd": 180,
        "billing_cycle": "monthly",
        "limits": {
            "contacts": 20000,
            "ai_messages_per_month": -1,   # unlimited
            "campaigns_per_month": -1,     # unlimited
            "team_members": 20,
            "whatsapp_numbers": 5,
        },
        "features": [
            "Everything in Growth",
            "Unlimited AI messages",
            "Unlimited campaigns",
            "Full audit logs",
            "AI persona customisation",
            "Knowledge base editor",
            "CRM integrations (coming soon)",
            "Dedicated account manager",
        ],
        "trial_days": 14,
    },
    "enterprise": {
        "id": "enterprise",
        "name": "Enterprise",
        "price_inr": 0,  # Custom pricing
        "price_usd": 0,
        "billing_cycle": "annual",
        "limits": {
            "contacts": -1,             # unlimited
            "ai_messages_per_month": -1,
            "campaigns_per_month": -1,
            "team_members": -1,
            "whatsapp_numbers": -1,
        },
        "features": [
            "Everything in Pro",
            "Unlimited contacts and messages",
            "Custom AI persona and prompts",
            "SSO / SAML",
            "Dedicated infrastructure",
            "SLA guarantee",
            "On-premise option",
            "Custom integrations",
            "White-labelling",
        ],
        "trial_days": 30,
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load(filename: str) -> dict:
    _ensure_dir()
    path = DATA_DIR / filename
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(filename: str, data: dict):
    _ensure_dir()
    (DATA_DIR / filename).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _current_month() -> str:
    return datetime.now(IST).strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------

def create_subscription(
    workspace_id: str,
    plan_id: str = "starter",
    trial: bool = True,
) -> dict:
    """
    Create a subscription for a workspace.

    Returns the subscription dict.
    Raises ValueError if plan is invalid.
    """
    if plan_id not in PLANS:
        raise ValueError(f"Invalid plan '{plan_id}'. Must be one of: {list(PLANS)}")

    plan = PLANS[plan_id]
    now = datetime.now(IST)
    trial_end = None
    if trial and plan.get("trial_days", 0) > 0:
        trial_end = (now + timedelta(days=plan["trial_days"])).isoformat()

    subs = _load("subscriptions.json")
    sub = {
        "workspace_id": workspace_id,
        "plan_id": plan_id,
        "status": "trialing" if trial else "active",
        "trial_end": trial_end,
        "current_period_start": now.isoformat(),
        "current_period_end": (now + timedelta(days=30)).isoformat(),
        "payment_provider": None,   # "stripe" when connected
        "payment_subscription_id": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "cancel_at_period_end": False,
    }
    subs[workspace_id] = sub
    _save("subscriptions.json", subs)
    logger.info(f"Subscription created: workspace={workspace_id} plan={plan_id} trial={trial}")
    return sub


def get_subscription(workspace_id: str) -> Optional[dict]:
    """Get the subscription for a workspace. Returns None if not found."""
    subs = _load("subscriptions.json")
    return subs.get(workspace_id)


def update_subscription(workspace_id: str, **fields) -> dict:
    """Update subscription fields."""
    subs = _load("subscriptions.json")
    if workspace_id not in subs:
        raise ValueError(f"No subscription for workspace {workspace_id}")
    subs[workspace_id].update(fields)
    subs[workspace_id]["updated_at"] = datetime.now(IST).isoformat()
    _save("subscriptions.json", subs)
    return subs[workspace_id]


def upgrade_plan(workspace_id: str, new_plan_id: str) -> dict:
    """Upgrade or downgrade a workspace to a new plan."""
    if new_plan_id not in PLANS:
        raise ValueError(f"Invalid plan '{new_plan_id}'")
    sub = update_subscription(
        workspace_id,
        plan_id=new_plan_id,
        status="active",
        updated_at=datetime.now(IST).isoformat(),
    )
    logger.info(f"Plan changed: workspace={workspace_id} → {new_plan_id}")
    return sub


def cancel_subscription(workspace_id: str, at_period_end: bool = True) -> dict:
    """Cancel a subscription."""
    if at_period_end:
        return update_subscription(workspace_id, cancel_at_period_end=True)
    else:
        return update_subscription(workspace_id, status="canceled")


def is_subscription_active(workspace_id: str) -> bool:
    """Check if a workspace has an active or trialing subscription."""
    sub = get_subscription(workspace_id)
    if not sub:
        return False
    status = sub.get("status", "")
    if status == "active":
        return True
    if status == "trialing":
        trial_end = sub.get("trial_end")
        if trial_end:
            try:
                end_dt = datetime.fromisoformat(trial_end)
                return datetime.now(IST) < end_dt
            except Exception:
                pass
    return False


def get_plan_limits(workspace_id: str) -> dict:
    """
    Get the effective plan limits for a workspace.

    Returns the limits dict from the plan definition.
    Falls back to starter limits if no subscription found.
    """
    sub = get_subscription(workspace_id)
    plan_id = sub.get("plan_id", "starter") if sub else "starter"
    plan = PLANS.get(plan_id, PLANS["starter"])
    return plan["limits"]


def get_trial_days_remaining(workspace_id: str) -> Optional[int]:
    """Return days remaining in trial, or None if not in trial."""
    sub = get_subscription(workspace_id)
    if not sub or sub.get("status") != "trialing":
        return None
    trial_end = sub.get("trial_end")
    if not trial_end:
        return None
    try:
        end_dt = datetime.fromisoformat(trial_end)
        remaining = (end_dt - datetime.now(IST)).days
        return max(0, remaining)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Usage metering
# ---------------------------------------------------------------------------

def _usage_key(workspace_id: str, month: str) -> str:
    return f"{workspace_id}:{month}"


def _load_usage() -> dict:
    return _load("usage.json")


def _save_usage(usage: dict):
    _save("usage.json", usage)


def increment_usage(
    workspace_id: str,
    metric: str,
    amount: int = 1,
) -> dict:
    """
    Increment a usage counter for a workspace in the current month.

    Args:
        workspace_id: The workspace.
        metric: One of "ai_messages", "campaigns", "contacts" (contacts is a gauge, not a counter).
        amount: How much to increment (default 1).

    Returns:
        The updated usage dict for this workspace/month.
    """
    usage = _load_usage()
    key = _usage_key(workspace_id, _current_month())
    if key not in usage:
        usage[key] = {
            "workspace_id": workspace_id,
            "month": _current_month(),
            "ai_messages": 0,
            "campaigns": 0,
            "contacts": 0,
        }
    usage[key][metric] = usage[key].get(metric, 0) + amount
    _save_usage(usage)
    return usage[key]


def set_usage(workspace_id: str, metric: str, value: int) -> dict:
    """
    Set an absolute usage value (e.g., contact count which is a gauge not a counter).
    """
    usage = _load_usage()
    key = _usage_key(workspace_id, _current_month())
    if key not in usage:
        usage[key] = {
            "workspace_id": workspace_id,
            "month": _current_month(),
            "ai_messages": 0,
            "campaigns": 0,
            "contacts": 0,
        }
    usage[key][metric] = value
    _save_usage(usage)
    return usage[key]


def get_usage(workspace_id: str, month: Optional[str] = None) -> dict:
    """Get usage for a workspace in a given month (default: current)."""
    usage = _load_usage()
    key = _usage_key(workspace_id, month or _current_month())
    return usage.get(key, {
        "workspace_id": workspace_id,
        "month": month or _current_month(),
        "ai_messages": 0,
        "campaigns": 0,
        "contacts": 0,
    })


def check_limit(workspace_id: str, metric: str, proposed_amount: int = 1) -> dict:
    """
    Check if a workspace is within its plan limits for a metric.

    Args:
        workspace_id: The workspace.
        metric: Usage metric to check ("ai_messages", "campaigns", "contacts").
        proposed_amount: How many more units are being requested.

    Returns:
        {
          "allowed": bool,
          "current": int,
          "limit": int,           # -1 = unlimited
          "remaining": int,        # -1 = unlimited
          "pct_used": float,
          "upgrade_required": bool,
          "plan_id": str,
        }
    """
    limits = get_plan_limits(workspace_id)
    usage = get_usage(workspace_id)
    sub = get_subscription(workspace_id)
    plan_id = sub.get("plan_id", "starter") if sub else "starter"

    # Map metric to limit key
    limit_key_map = {
        "ai_messages": "ai_messages_per_month",
        "campaigns": "campaigns_per_month",
        "contacts": "contacts",
        "team_members": "team_members",
    }
    limit_key = limit_key_map.get(metric, metric)
    limit = limits.get(limit_key, 0)
    current = usage.get(metric, 0)

    if limit == -1:
        # Unlimited
        return {
            "allowed": True,
            "current": current,
            "limit": -1,
            "remaining": -1,
            "pct_used": 0.0,
            "upgrade_required": False,
            "plan_id": plan_id,
        }

    remaining = max(0, limit - current)
    allowed = remaining >= proposed_amount
    pct_used = round(current / max(limit, 1) * 100, 1)

    return {
        "allowed": allowed,
        "current": current,
        "limit": limit,
        "remaining": remaining,
        "pct_used": pct_used,
        "upgrade_required": not allowed,
        "plan_id": plan_id,
    }


def get_usage_summary(workspace_id: str) -> dict:
    """
    Get a full usage summary for a workspace, including limit status for all metrics.

    Suitable for the billing dashboard panel.
    """
    sub = get_subscription(workspace_id)
    plan_id = sub.get("plan_id", "starter") if sub else "starter"
    plan = PLANS.get(plan_id, PLANS["starter"])
    usage = get_usage(workspace_id)

    metrics = ["ai_messages", "campaigns", "contacts", "team_members"]
    metric_status = {}
    for m in metrics:
        metric_status[m] = check_limit(workspace_id, m)

    trial_days = get_trial_days_remaining(workspace_id)

    return {
        "workspace_id": workspace_id,
        "plan": {
            "id": plan_id,
            "name": plan["name"],
            "price_inr": plan["price_inr"],
            "price_usd": plan["price_usd"],
        },
        "status": sub.get("status", "none") if sub else "none",
        "trial_days_remaining": trial_days,
        "active": is_subscription_active(workspace_id),
        "current_period_end": sub.get("current_period_end") if sub else None,
        "cancel_at_period_end": sub.get("cancel_at_period_end", False) if sub else False,
        "usage": usage,
        "limits": plan["limits"],
        "metric_status": metric_status,
        "features": plan.get("features", []),
    }


# ---------------------------------------------------------------------------
# Plan comparison helper
# ---------------------------------------------------------------------------

def get_plans_for_display() -> list:
    """Return all plans formatted for the pricing/upgrade page."""
    return [
        {
            "id": pid,
            "name": p["name"],
            "price_inr": p["price_inr"],
            "price_usd": p["price_usd"],
            "billing_cycle": p["billing_cycle"],
            "limits": p["limits"],
            "features": p["features"],
            "trial_days": p.get("trial_days", 0),
            "popular": pid == "growth",
        }
        for pid, p in PLANS.items()
    ]


# ---------------------------------------------------------------------------
# Stripe webhook integration stubs (wired in when Stripe is configured)
# ---------------------------------------------------------------------------

def handle_stripe_webhook(event_type: str, payload: dict) -> dict:
    """
    Process a Stripe webhook event.

    Supported events:
    - customer.subscription.created
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_succeeded
    - invoice.payment_failed

    Args:
        event_type: The Stripe event type string.
        payload: The Stripe event data.object dict.

    Returns:
        {"ok": bool, "action": str}
    """
    metadata = payload.get("metadata", {})
    workspace_id = metadata.get("workspace_id", "")

    if not workspace_id:
        return {"ok": False, "action": "no_workspace_id"}

    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        status = payload.get("status", "active")
        plan_nickname = payload.get("items", {}).get("data", [{}])[0].get(
            "price", {}
        ).get("nickname", "starter")
        sub_id = payload.get("id", "")

        # Map Stripe plan nickname → our plan_id
        plan_map = {
            "Starter": "starter",
            "Growth": "growth",
            "Pro": "pro",
            "Enterprise": "enterprise",
        }
        plan_id = plan_map.get(plan_nickname, "starter")

        update_subscription(
            workspace_id,
            plan_id=plan_id,
            status=status,
            payment_provider="stripe",
            payment_subscription_id=sub_id,
        )
        logger.info(f"Stripe: subscription {event_type} → workspace={workspace_id} plan={plan_id}")
        return {"ok": True, "action": "subscription_updated"}

    elif event_type == "customer.subscription.deleted":
        update_subscription(workspace_id, status="canceled")
        logger.info(f"Stripe: subscription canceled → workspace={workspace_id}")
        return {"ok": True, "action": "subscription_canceled"}

    elif event_type == "invoice.payment_succeeded":
        update_subscription(workspace_id, status="active")
        logger.info(f"Stripe: payment succeeded → workspace={workspace_id}")
        return {"ok": True, "action": "payment_ok"}

    elif event_type == "invoice.payment_failed":
        update_subscription(workspace_id, status="past_due")
        logger.warning(f"Stripe: payment failed → workspace={workspace_id}")
        return {"ok": True, "action": "payment_failed"}

    return {"ok": True, "action": "unhandled_event"}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import shutil

    # Clean
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)

    ws_id = "ws_test001"

    # 1. Create subscription (trial)
    sub = create_subscription(ws_id, "growth", trial=True)
    assert sub["status"] == "trialing"
    assert sub["trial_end"] is not None
    print(f"✅ Subscription created: {sub['status']}, trial_end={sub['trial_end'][:10]}")

    # 2. Active check
    assert is_subscription_active(ws_id) is True
    print("✅ Subscription is active (in trial)")

    # 3. Trial days
    days = get_trial_days_remaining(ws_id)
    assert days is not None and days >= 13
    print(f"✅ Trial days remaining: {days}")

    # 4. Usage metering
    increment_usage(ws_id, "ai_messages", 10)
    increment_usage(ws_id, "ai_messages", 5)
    increment_usage(ws_id, "campaigns", 1)
    set_usage(ws_id, "contacts", 42)
    usage = get_usage(ws_id)
    assert usage["ai_messages"] == 15
    assert usage["contacts"] == 42
    print(f"✅ Usage metered: {usage}")

    # 5. Limit check — within limits
    check = check_limit(ws_id, "ai_messages", 1)
    assert check["allowed"] is True
    assert check["current"] == 15
    assert check["limit"] == 5000  # growth plan
    print(f"✅ Limit check (within): {check['remaining']} remaining")

    # 6. Limit check — over limit
    check_over = check_limit(ws_id, "ai_messages", 10000)
    assert check_over["allowed"] is False
    assert check_over["upgrade_required"] is True
    print(f"✅ Limit check (over): upgrade_required={check_over['upgrade_required']}")

    # 7. Unlimited plan
    update_subscription(ws_id, plan_id="pro")
    check_pro = check_limit(ws_id, "ai_messages", 100000)
    assert check_pro["allowed"] is True
    assert check_pro["limit"] == -1
    print(f"✅ Pro plan unlimited: {check_pro}")

    # 8. Upgrade
    sub2 = upgrade_plan(ws_id, "enterprise")
    assert sub2["plan_id"] == "enterprise"
    print(f"✅ Upgraded to enterprise")

    # 9. Full usage summary
    summary = get_usage_summary(ws_id)
    assert summary["plan"]["id"] == "enterprise"
    print(f"✅ Usage summary: {json.dumps(summary['plan'], indent=2)}")

    # 10. Plans for display
    plans = get_plans_for_display()
    assert len(plans) == 4
    growth = next(p for p in plans if p["id"] == "growth")
    assert growth["popular"] is True
    print(f"✅ Plans for display: {[p['name'] for p in plans]}")

    # 11. Cancel
    cancel_subscription(ws_id)
    sub3 = get_subscription(ws_id)
    assert sub3["cancel_at_period_end"] is True
    print("✅ Cancellation scheduled")

    # 12. Stripe webhook
    result = handle_stripe_webhook("invoice.payment_succeeded", {"metadata": {"workspace_id": ws_id}})
    assert result["ok"]
    print(f"✅ Stripe webhook: {result}")

    # Cleanup
    shutil.rmtree(DATA_DIR)
    print("\n✅ All billing tests passed!")
