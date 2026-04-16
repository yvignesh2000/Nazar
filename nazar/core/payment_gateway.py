# -*- coding: utf-8 -*-
"""
Nazar — Razorpay Payment Gateway Integration

Handles:
- Subscription creation via Razorpay Subscriptions API
- Order creation for one-time purchases
- Webhook signature verification & event processing
- Plan synchronization (Nazar plans ↔ Razorpay plans)
- Payment status tracking
- GST invoice data preparation

Environment Variables Required:
  RAZORPAY_KEY_ID       — Razorpay API key
  RAZORPAY_KEY_SECRET   — Razorpay API secret
  RAZORPAY_WEBHOOK_SECRET — Webhook signature secret

Flow:
  1. User clicks "Upgrade" on dashboard
  2. Backend creates a Razorpay subscription → returns subscription_id + short_url
  3. Frontend redirects to Razorpay checkout / embeds checkout widget
  4. Razorpay sends webhook on payment success/failure
  5. Backend updates billing state
"""

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))

# Razorpay credentials (set via environment)
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

# Razorpay Plan IDs (create these in Razorpay Dashboard or via API)
# Maps our plan_id → Razorpay plan_id
_RAZORPAY_PLAN_MAP = {
    "starter": os.environ.get("RAZORPAY_PLAN_STARTER", ""),
    "growth": os.environ.get("RAZORPAY_PLAN_GROWTH", ""),
    "pro": os.environ.get("RAZORPAY_PLAN_PRO", ""),
}

_client = None


def _get_client():
    """Lazy-init Razorpay client."""
    global _client
    if _client is None:
        if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
            raise RuntimeError(
                "Razorpay credentials not configured. "
                "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET environment variables."
            )
        import razorpay
        _client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return _client


def is_configured() -> bool:
    """Check if Razorpay credentials are set."""
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


# ---------------------------------------------------------------------------
# Plan Sync — Create Razorpay plans to match our billing plans
# ---------------------------------------------------------------------------

def ensure_razorpay_plans() -> dict:
    """
    Create Razorpay plans for each Nazar plan if they don't exist.
    Returns a mapping of plan_id → razorpay_plan_id.

    Call once during setup or server startup (idempotent if plans already exist).
    """
    from billing import PLANS

    client = _get_client()
    plan_map = {}

    for plan_id, plan in PLANS.items():
        if plan_id == "enterprise":
            continue  # Enterprise is custom pricing

        price_paise = plan["price_inr"] * 100  # Razorpay uses paise
        if price_paise <= 0:
            continue

        # Check if we already have a plan ID in env
        existing = _RAZORPAY_PLAN_MAP.get(plan_id, "")
        if existing:
            plan_map[plan_id] = existing
            continue

        try:
            rz_plan = client.plan.create({
                "period": "monthly",
                "interval": 1,
                "item": {
                    "name": f"Nazar {plan['name']}",
                    "amount": price_paise,
                    "currency": "INR",
                    "description": f"Nazar {plan['name']} Plan — Monthly subscription",
                },
                "notes": {
                    "nazar_plan_id": plan_id,
                },
            })
            plan_map[plan_id] = rz_plan["id"]
            logger.info("Created Razorpay plan: %s → %s", plan_id, rz_plan["id"])
        except Exception as e:
            logger.error("Failed to create Razorpay plan %s: %s", plan_id, e)

    return plan_map


# ---------------------------------------------------------------------------
# Subscription Management
# ---------------------------------------------------------------------------

def create_subscription(
    workspace_id: str,
    plan_id: str,
    customer_email: str,
    customer_name: str = "",
    customer_phone: str = "",
    total_count: int = 0,
    notes: Optional[dict] = None,
) -> dict:
    """
    Create a Razorpay subscription for a workspace.

    Args:
        workspace_id: Internal workspace ID
        plan_id: Our plan ID (starter/growth/pro)
        customer_email: Customer email for Razorpay
        customer_name: Customer name
        customer_phone: Customer phone
        total_count: 0 = infinite billing cycles (until cancelled)
        notes: Additional metadata

    Returns:
        {
            "subscription_id": "sub_xyz",
            "short_url": "https://rzp.io/...",
            "status": "created",
            "plan_id": "plan_xyz",
        }
    """
    client = _get_client()

    rz_plan_id = _RAZORPAY_PLAN_MAP.get(plan_id, "")
    if not rz_plan_id:
        raise ValueError(
            f"No Razorpay plan ID configured for '{plan_id}'. "
            f"Set RAZORPAY_PLAN_{plan_id.upper()} environment variable."
        )

    payload = {
        "plan_id": rz_plan_id,
        "total_count": total_count,
        "quantity": 1,
        "customer_notify": 1,
        "notes": {
            "workspace_id": workspace_id,
            "nazar_plan_id": plan_id,
            **(notes or {}),
        },
    }

    # Create or find customer
    if customer_email:
        try:
            customer = client.customer.create({
                "name": customer_name or customer_email.split("@")[0],
                "email": customer_email,
                "contact": customer_phone.replace("+", "") if customer_phone else "",
                "notes": {"workspace_id": workspace_id},
            })
            payload["customer_id"] = customer["id"]
        except Exception as e:
            logger.warning("Could not create Razorpay customer: %s", e)

    sub = client.subscription.create(payload)

    logger.info(
        "Razorpay subscription created: sub=%s plan=%s workspace=%s",
        sub["id"], plan_id, workspace_id,
    )

    return {
        "subscription_id": sub["id"],
        "short_url": sub.get("short_url", ""),
        "status": sub.get("status", "created"),
        "plan_id": rz_plan_id,
        "razorpay_plan_id": rz_plan_id,
    }


def cancel_subscription(subscription_id: str, cancel_at_cycle_end: bool = True) -> dict:
    """Cancel a Razorpay subscription."""
    client = _get_client()
    try:
        result = client.subscription.cancel(subscription_id, {
            "cancel_at_cycle_end": 1 if cancel_at_cycle_end else 0,
        })
        logger.info("Razorpay subscription cancelled: %s", subscription_id)
        return {"ok": True, "status": result.get("status", "cancelled")}
    except Exception as e:
        logger.error("Failed to cancel Razorpay subscription %s: %s", subscription_id, e)
        return {"ok": False, "error": str(e)}


def get_subscription_status(subscription_id: str) -> dict:
    """Fetch current status of a Razorpay subscription."""
    client = _get_client()
    try:
        sub = client.subscription.fetch(subscription_id)
        return {
            "subscription_id": sub["id"],
            "status": sub.get("status", "unknown"),
            "plan_id": sub.get("plan_id", ""),
            "current_start": sub.get("current_start"),
            "current_end": sub.get("current_end"),
            "charge_at": sub.get("charge_at"),
            "paid_count": sub.get("paid_count", 0),
        }
    except Exception as e:
        logger.error("Failed to fetch Razorpay subscription %s: %s", subscription_id, e)
        return {"subscription_id": subscription_id, "status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# One-time Order (for add-ons, custom pricing, etc.)
# ---------------------------------------------------------------------------

def create_order(
    amount_inr: float,
    workspace_id: str,
    description: str = "Nazar payment",
    notes: Optional[dict] = None,
) -> dict:
    """
    Create a Razorpay order for one-time payment.

    Args:
        amount_inr: Amount in INR (will be converted to paise)
        workspace_id: Internal workspace ID
        description: Payment description
        notes: Additional metadata

    Returns:
        {"order_id": "order_xyz", "amount": 199900, "currency": "INR", ...}
    """
    client = _get_client()
    amount_paise = int(amount_inr * 100)

    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": f"nazar_{workspace_id}_{datetime.now(IST).strftime('%Y%m%d%H%M%S')}",
        "notes": {
            "workspace_id": workspace_id,
            "description": description,
            **(notes or {}),
        },
    })

    logger.info("Razorpay order created: %s for ₹%.2f", order["id"], amount_inr)
    return {
        "order_id": order["id"],
        "amount": amount_paise,
        "currency": "INR",
        "key_id": RAZORPAY_KEY_ID,
    }


# ---------------------------------------------------------------------------
# Payment Verification
# ---------------------------------------------------------------------------

def verify_payment_signature(
    razorpay_order_id: str = "",
    razorpay_payment_id: str = "",
    razorpay_signature: str = "",
    razorpay_subscription_id: str = "",
) -> bool:
    """
    Verify Razorpay payment signature.

    For orders: verify(order_id + "|" + payment_id, signature)
    For subscriptions: verify(payment_id + "|" + subscription_id, signature)
    """
    client = _get_client()
    try:
        if razorpay_subscription_id:
            client.utility.verify_subscription_payment_signature({
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_subscription_id": razorpay_subscription_id,
                "razorpay_signature": razorpay_signature,
            })
        else:
            client.utility.verify_payment_signature({
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature,
            })
        return True
    except Exception as e:
        logger.warning("Payment signature verification failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Webhook Processing
# ---------------------------------------------------------------------------

def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """
    Verify Razorpay webhook signature using HMAC-SHA256.

    Args:
        body: Raw request body bytes
        signature: X-Razorpay-Signature header value

    Returns:
        True if valid, False otherwise
    """
    if not RAZORPAY_WEBHOOK_SECRET:
        # SECURITY: Reject ALL webhooks if secret is not configured.
        # This prevents forged payment success events from upgrading plans for free.
        logger.error(
            "RAZORPAY_WEBHOOK_SECRET not set — rejecting webhook. "
            "Set RAZORPAY_WEBHOOK_SECRET in .env to enable payment webhooks."
        )
        return False

    if not signature:
        logger.warning("Razorpay webhook: missing X-Razorpay-Signature header")
        return False

    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def process_webhook_event(event_type: str, payload: dict) -> dict:
    """
    Process a Razorpay webhook event and update billing state.

    Supported events:
      - subscription.activated
      - subscription.charged
      - subscription.completed
      - subscription.halted
      - subscription.cancelled
      - subscription.pending
      - payment.captured
      - payment.failed
      - invoice.paid

    Returns:
        {"ok": bool, "action": str, "workspace_id": str}
    """
    from billing import update_subscription, get_subscription

    # Extract workspace_id from notes
    entity = payload.get("entity", {})
    notes = entity.get("notes", {})
    workspace_id = notes.get("workspace_id", "")

    # For subscription events, entity is inside subscription
    subscription = entity.get("subscription", entity) if "subscription" in entity else entity

    if not workspace_id:
        # Try to find from subscription notes
        sub_notes = subscription.get("notes", {})
        workspace_id = sub_notes.get("workspace_id", "")

    if not workspace_id:
        logger.warning("Razorpay webhook: no workspace_id in notes for event %s", event_type)
        return {"ok": False, "action": "no_workspace_id"}

    razorpay_sub_id = subscription.get("id", "") or entity.get("subscription_id", "")
    nazar_plan_id = notes.get("nazar_plan_id", "") or subscription.get("notes", {}).get("nazar_plan_id", "")

    if event_type in ("subscription.activated", "subscription.charged"):
        update_subscription(
            workspace_id,
            status="active",
            payment_provider="razorpay",
            payment_subscription_id=razorpay_sub_id,
            plan_id=nazar_plan_id or None,
        )
        logger.info("Razorpay: subscription active → workspace=%s", workspace_id)
        return {"ok": True, "action": "subscription_activated", "workspace_id": workspace_id}

    elif event_type == "subscription.halted":
        update_subscription(workspace_id, status="past_due")
        logger.warning("Razorpay: subscription halted → workspace=%s", workspace_id)
        return {"ok": True, "action": "subscription_halted", "workspace_id": workspace_id}

    elif event_type == "subscription.cancelled":
        update_subscription(workspace_id, status="canceled")
        logger.info("Razorpay: subscription cancelled → workspace=%s", workspace_id)
        return {"ok": True, "action": "subscription_cancelled", "workspace_id": workspace_id}

    elif event_type == "subscription.pending":
        update_subscription(workspace_id, status="pending")
        logger.info("Razorpay: subscription pending → workspace=%s", workspace_id)
        return {"ok": True, "action": "subscription_pending", "workspace_id": workspace_id}

    elif event_type == "subscription.completed":
        update_subscription(workspace_id, status="completed")
        logger.info("Razorpay: subscription completed → workspace=%s", workspace_id)
        return {"ok": True, "action": "subscription_completed", "workspace_id": workspace_id}

    elif event_type == "payment.captured":
        update_subscription(workspace_id, status="active")
        logger.info("Razorpay: payment captured → workspace=%s", workspace_id)
        return {"ok": True, "action": "payment_captured", "workspace_id": workspace_id}

    elif event_type == "payment.failed":
        update_subscription(workspace_id, status="past_due")
        logger.warning("Razorpay: payment failed → workspace=%s", workspace_id)
        return {"ok": True, "action": "payment_failed", "workspace_id": workspace_id}

    elif event_type == "invoice.paid":
        update_subscription(workspace_id, status="active")
        logger.info("Razorpay: invoice paid → workspace=%s", workspace_id)
        return {"ok": True, "action": "invoice_paid", "workspace_id": workspace_id}

    return {"ok": True, "action": "unhandled_event", "workspace_id": workspace_id}


# ---------------------------------------------------------------------------
# GST Invoice Data
# ---------------------------------------------------------------------------

def get_invoice_data(workspace_id: str, plan_id: str) -> dict:
    """
    Generate GST invoice data for a subscription payment.

    Returns a dict with all fields needed for a GST invoice.
    This does NOT generate the PDF — that's a frontend concern.
    """
    from billing import PLANS, get_subscription

    plan = PLANS.get(plan_id, PLANS.get("starter", {}))
    sub = get_subscription(workspace_id) or {}

    base_amount = plan.get("price_inr", 0)
    gst_rate = 0.18  # 18% GST
    gst_amount = round(base_amount * gst_rate, 2)
    total = round(base_amount + gst_amount, 2)

    now = datetime.now(IST)

    return {
        "invoice_number": f"NZR-{now.strftime('%Y%m')}-{workspace_id[:6].upper()}",
        "invoice_date": now.strftime("%Y-%m-%d"),
        "workspace_id": workspace_id,
        "plan_name": plan.get("name", ""),
        "plan_id": plan_id,
        "billing_cycle": plan.get("billing_cycle", "monthly"),
        "base_amount": base_amount,
        "currency": "INR",
        "gst_rate_pct": 18,
        "cgst": round(gst_amount / 2, 2),
        "sgst": round(gst_amount / 2, 2),
        "igst": 0,  # For inter-state, swap CGST+SGST for IGST
        "total_gst": gst_amount,
        "total_amount": total,
        "payment_provider": sub.get("payment_provider", "razorpay"),
        "subscription_id": sub.get("payment_subscription_id", ""),
        "seller": {
            "name": "Nazar Technologies Pvt Ltd",
            "gstin": os.environ.get("NAZAR_GSTIN", ""),
            "address": os.environ.get("NAZAR_ADDRESS", ""),
            "state": os.environ.get("NAZAR_STATE", ""),
            "pan": os.environ.get("NAZAR_PAN", ""),
        },
    }
