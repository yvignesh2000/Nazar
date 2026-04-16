"""
Tests for Nazar — Payment Gateway (Razorpay integration)

Tests cover:
- Configuration checking
- Webhook signature verification
- Webhook event processing
- GST invoice data generation
"""

import hashlib
import hmac
import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure core modules are importable
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "core"))


class TestIsConfigured:
    """Test payment gateway configuration detection."""

    def test_not_configured_when_keys_empty(self):
        with patch("payment_gateway.RAZORPAY_KEY_ID", ""), \
             patch("payment_gateway.RAZORPAY_KEY_SECRET", ""):
            import payment_gateway as pg
            assert pg.is_configured() is False

    def test_configured_when_keys_set(self):
        with patch("payment_gateway.RAZORPAY_KEY_ID", "rzp_test_abc"), \
             patch("payment_gateway.RAZORPAY_KEY_SECRET", "secret123"):
            import payment_gateway as pg
            assert pg.is_configured() is True

    def test_not_configured_when_only_key_id(self):
        with patch("payment_gateway.RAZORPAY_KEY_ID", "rzp_test_abc"), \
             patch("payment_gateway.RAZORPAY_KEY_SECRET", ""):
            import payment_gateway as pg
            assert pg.is_configured() is False


class TestWebhookSignatureVerification:
    """Test Razorpay webhook signature verification."""

    def test_valid_signature_passes(self):
        import payment_gateway as pg
        secret = "test_webhook_secret_123"
        body = b'{"event":"subscription.activated","payload":{}}'
        expected_sig = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()

        with patch("payment_gateway.RAZORPAY_WEBHOOK_SECRET", secret):
            assert pg.verify_webhook_signature(body, expected_sig) is True

    def test_invalid_signature_fails(self):
        import payment_gateway as pg
        secret = "test_webhook_secret_123"
        body = b'{"event":"subscription.activated"}'

        with patch("payment_gateway.RAZORPAY_WEBHOOK_SECRET", secret):
            assert pg.verify_webhook_signature(body, "invalid_signature") is False

    def test_no_secret_rejects_webhook(self):
        """When no secret is set, webhooks must be REJECTED for security."""
        import payment_gateway as pg
        with patch("payment_gateway.RAZORPAY_WEBHOOK_SECRET", ""):
            assert pg.verify_webhook_signature(b"anything", "any_sig") is False

    def test_missing_signature_rejects(self):
        """When signature header is missing, webhooks must be rejected."""
        import payment_gateway as pg
        with patch("payment_gateway.RAZORPAY_WEBHOOK_SECRET", "some_secret"):
            assert pg.verify_webhook_signature(b"anything", "") is False


class TestProcessWebhookEvent:
    """Test webhook event processing updates billing state."""

    def test_subscription_activated(self, tmp_data_dir):
        import payment_gateway as pg
        from billing import create_subscription, get_subscription

        ws_id = "ws_test_pay"
        create_subscription(ws_id, "starter", trial=True)

        result = pg.process_webhook_event("subscription.activated", {
            "entity": {
                "id": "sub_rz_123",
                "notes": {"workspace_id": ws_id, "nazar_plan_id": "growth"},
            },
        })

        assert result["ok"] is True
        assert result["action"] == "subscription_activated"
        sub = get_subscription(ws_id)
        assert sub["status"] == "active"
        assert sub["payment_provider"] == "razorpay"

    def test_subscription_halted(self, tmp_data_dir):
        import payment_gateway as pg
        from billing import create_subscription, get_subscription

        ws_id = "ws_test_halt"
        create_subscription(ws_id, "growth", trial=False)

        result = pg.process_webhook_event("subscription.halted", {
            "entity": {
                "notes": {"workspace_id": ws_id},
            },
        })

        assert result["ok"] is True
        sub = get_subscription(ws_id)
        assert sub["status"] == "past_due"

    def test_subscription_cancelled(self, tmp_data_dir):
        import payment_gateway as pg
        from billing import create_subscription, get_subscription

        ws_id = "ws_test_cancel"
        create_subscription(ws_id, "growth", trial=False)

        result = pg.process_webhook_event("subscription.cancelled", {
            "entity": {
                "notes": {"workspace_id": ws_id},
            },
        })

        assert result["ok"] is True
        sub = get_subscription(ws_id)
        assert sub["status"] == "canceled"

    def test_payment_captured(self, tmp_data_dir):
        import payment_gateway as pg
        from billing import create_subscription, get_subscription

        ws_id = "ws_test_captured"
        create_subscription(ws_id, "pro", trial=True)

        result = pg.process_webhook_event("payment.captured", {
            "entity": {
                "notes": {"workspace_id": ws_id},
            },
        })

        assert result["ok"] is True
        sub = get_subscription(ws_id)
        assert sub["status"] == "active"

    def test_payment_failed(self, tmp_data_dir):
        import payment_gateway as pg
        from billing import create_subscription, get_subscription

        ws_id = "ws_test_failed"
        create_subscription(ws_id, "growth", trial=False)

        result = pg.process_webhook_event("payment.failed", {
            "entity": {
                "notes": {"workspace_id": ws_id},
            },
        })

        assert result["ok"] is True
        sub = get_subscription(ws_id)
        assert sub["status"] == "past_due"

    def test_no_workspace_id_returns_error(self, tmp_data_dir):
        import payment_gateway as pg

        result = pg.process_webhook_event("subscription.activated", {
            "entity": {"notes": {}},
        })

        assert result["ok"] is False
        assert result["action"] == "no_workspace_id"

    def test_unhandled_event(self, tmp_data_dir):
        import payment_gateway as pg
        from billing import create_subscription

        ws_id = "ws_test_unhandled"
        create_subscription(ws_id, "starter")

        result = pg.process_webhook_event("some.unknown.event", {
            "entity": {"notes": {"workspace_id": ws_id}},
        })

        assert result["ok"] is True
        assert result["action"] == "unhandled_event"


class TestGSTInvoiceData:
    """Test GST invoice generation."""

    def test_invoice_data_structure(self, tmp_data_dir):
        import payment_gateway as pg
        from billing import create_subscription

        ws_id = "ws_invoice_test"
        create_subscription(ws_id, "growth", trial=False)

        invoice = pg.get_invoice_data(ws_id, "growth")

        assert invoice["workspace_id"] == ws_id
        assert invoice["plan_id"] == "growth"
        assert invoice["plan_name"] == "Growth"
        assert invoice["base_amount"] == 5999
        assert invoice["currency"] == "INR"
        assert invoice["gst_rate_pct"] == 18
        assert invoice["total_gst"] == round(5999 * 0.18, 2)
        assert invoice["cgst"] == round(5999 * 0.18 / 2, 2)
        assert invoice["sgst"] == round(5999 * 0.18 / 2, 2)
        assert invoice["total_amount"] == round(5999 * 1.18, 2)
        assert "invoice_number" in invoice
        assert "invoice_date" in invoice
        assert "seller" in invoice

    def test_invoice_for_starter_plan(self, tmp_data_dir):
        import payment_gateway as pg
        from billing import create_subscription

        ws_id = "ws_invoice_starter"
        create_subscription(ws_id, "starter")

        invoice = pg.get_invoice_data(ws_id, "starter")

        assert invoice["base_amount"] == 1999
        assert invoice["total_amount"] == round(1999 * 1.18, 2)

    def test_invoice_for_enterprise_has_zero(self, tmp_data_dir):
        import payment_gateway as pg
        from billing import create_subscription

        ws_id = "ws_invoice_ent"
        create_subscription(ws_id, "enterprise")

        invoice = pg.get_invoice_data(ws_id, "enterprise")

        assert invoice["base_amount"] == 0
        assert invoice["total_amount"] == 0
