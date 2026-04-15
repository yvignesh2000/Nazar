"""
Unit tests for core/billing.py

Tests: plan definitions, subscriptions, usage metering,
       limit enforcement, trial management, Stripe webhook handling.
"""

import json
import pytest
from datetime import datetime, timezone, timedelta


IST = timezone(timedelta(hours=5, minutes=30))


class TestPlanDefinitions:
    def test_all_plans_present(self):
        from billing import PLANS
        assert "starter" in PLANS
        assert "growth" in PLANS
        assert "pro" in PLANS
        assert "enterprise" in PLANS

    def test_plans_have_required_fields(self):
        from billing import PLANS
        required = {"id", "name", "price_inr", "limits", "features"}
        for pid, plan in PLANS.items():
            for field in required:
                assert field in plan, f"Plan {pid} missing field {field}"

    def test_enterprise_has_unlimited_limits(self):
        from billing import PLANS
        limits = PLANS["enterprise"]["limits"]
        assert limits["contacts"] == -1
        assert limits["ai_messages_per_month"] == -1

    def test_get_plans_for_display(self):
        from billing import get_plans_for_display
        plans = get_plans_for_display()
        assert len(plans) == 4
        growth = next(p for p in plans if p["id"] == "growth")
        assert growth["popular"] is True


class TestSubscriptions:
    def test_create_subscription_trial(self, tmp_data_dir):
        from billing import create_subscription, get_subscription
        sub = create_subscription("ws_test", "starter", trial=True)
        assert sub["status"] == "trialing"
        assert sub["trial_end"] is not None
        assert sub["plan_id"] == "starter"

    def test_create_subscription_active(self, tmp_data_dir):
        from billing import create_subscription
        sub = create_subscription("ws_test", "growth", trial=False)
        assert sub["status"] == "active"
        assert sub["trial_end"] is None

    def test_invalid_plan_rejected(self, tmp_data_dir):
        from billing import create_subscription
        with pytest.raises(ValueError):
            create_subscription("ws_test", "superplan")

    def test_get_subscription(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import get_subscription
        ws_id = sample_workspace["workspace"]["workspace_id"]
        sub = get_subscription(ws_id)
        assert sub is not None
        assert sub["plan_id"] == "growth"

    def test_upgrade_plan(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import upgrade_plan, get_subscription
        ws_id = sample_workspace["workspace"]["workspace_id"]
        sub = upgrade_plan(ws_id, "pro")
        assert sub["plan_id"] == "pro"

    def test_cancel_at_period_end(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import cancel_subscription, get_subscription
        ws_id = sample_workspace["workspace"]["workspace_id"]
        cancel_subscription(ws_id, at_period_end=True)
        sub = get_subscription(ws_id)
        assert sub["cancel_at_period_end"] is True

    def test_cancel_immediately(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import cancel_subscription, get_subscription
        ws_id = sample_workspace["workspace"]["workspace_id"]
        cancel_subscription(ws_id, at_period_end=False)
        sub = get_subscription(ws_id)
        assert sub["status"] == "canceled"

    def test_is_subscription_active_trialing(self, tmp_data_dir, sample_workspace):
        from billing import create_subscription, is_subscription_active
        ws_id = sample_workspace["workspace"]["workspace_id"]
        create_subscription(ws_id, "starter", trial=True)
        assert is_subscription_active(ws_id) is True

    def test_is_subscription_active_no_sub(self, tmp_data_dir):
        from billing import is_subscription_active
        assert is_subscription_active("nonexistent_ws") is False

    def test_trial_days_remaining(self, tmp_data_dir, sample_workspace):
        from billing import create_subscription, get_trial_days_remaining
        ws_id = sample_workspace["workspace"]["workspace_id"]
        create_subscription(ws_id, "growth", trial=True)
        days = get_trial_days_remaining(ws_id)
        assert days is not None
        assert 0 <= days <= 14

    def test_trial_days_none_for_active(self, tmp_data_dir, sample_workspace):
        from billing import create_subscription, get_trial_days_remaining
        ws_id = sample_workspace["workspace"]["workspace_id"]
        create_subscription(ws_id, "growth", trial=False)
        assert get_trial_days_remaining(ws_id) is None


class TestUsageMetering:
    def test_increment_usage(self, tmp_data_dir):
        from billing import increment_usage, get_usage
        increment_usage("ws_test", "ai_messages", 10)
        increment_usage("ws_test", "ai_messages", 5)
        usage = get_usage("ws_test")
        assert usage["ai_messages"] == 15

    def test_increment_campaigns(self, tmp_data_dir):
        """Test that campaign usage increments correctly."""
        from billing import increment_usage, get_usage
        increment_usage("ws_test", "campaigns", 1)
        increment_usage("ws_test", "campaigns", 1)
        usage = get_usage("ws_test")
        assert usage["campaigns"] == 2

    def test_set_contacts_gauge(self, tmp_data_dir):
        from billing import set_usage, get_usage
        set_usage("ws_test", "contacts", 150)
        usage = get_usage("ws_test")
        assert usage["contacts"] == 150

    def test_usage_default_zeros(self, tmp_data_dir):
        from billing import get_usage
        usage = get_usage("ws_new")
        assert usage["ai_messages"] == 0
        assert usage["contacts"] == 0


class TestLimitEnforcement:
    def test_within_limit_allowed(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import check_limit
        ws_id = sample_workspace["workspace"]["workspace_id"]
        check = check_limit(ws_id, "ai_messages", 1)
        assert check["allowed"] is True
        assert check["limit"] == 5000  # growth plan

    def test_over_limit_blocked(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import increment_usage, check_limit
        ws_id = sample_workspace["workspace"]["workspace_id"]
        increment_usage(ws_id, "ai_messages", 4999)
        check = check_limit(ws_id, "ai_messages", 10)
        assert check["allowed"] is False
        assert check["upgrade_required"] is True

    def test_unlimited_plan_never_blocks(self, tmp_data_dir, sample_workspace):
        from billing import create_subscription, check_limit
        ws_id = sample_workspace["workspace"]["workspace_id"]
        create_subscription(ws_id, "enterprise", trial=False)
        check = check_limit(ws_id, "ai_messages", 1_000_000)
        assert check["allowed"] is True
        assert check["limit"] == -1
        assert check["remaining"] == -1

    def test_pct_used_calculated(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import increment_usage, check_limit
        ws_id = sample_workspace["workspace"]["workspace_id"]
        increment_usage(ws_id, "ai_messages", 2500)  # 50% of 5000
        check = check_limit(ws_id, "ai_messages")
        assert check["pct_used"] == 50.0

    def test_contact_limit_enforced(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import set_usage, check_limit
        ws_id = sample_workspace["workspace"]["workspace_id"]
        set_usage(ws_id, "contacts", 2001)  # Over growth limit of 2000
        check = check_limit(ws_id, "contacts", 1)
        assert check["allowed"] is False


class TestUsageSummary:
    def test_full_usage_summary(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import get_usage_summary, increment_usage
        ws_id = sample_workspace["workspace"]["workspace_id"]
        increment_usage(ws_id, "ai_messages", 100)
        summary = get_usage_summary(ws_id)
        assert "plan" in summary
        assert "usage" in summary
        assert "limits" in summary
        assert "metric_status" in summary
        assert summary["plan"]["id"] == "growth"
        assert summary["usage"]["ai_messages"] == 100
        assert summary["active"] is True

    def test_summary_has_features(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import get_usage_summary
        ws_id = sample_workspace["workspace"]["workspace_id"]
        summary = get_usage_summary(ws_id)
        assert isinstance(summary["features"], list)
        assert len(summary["features"]) > 0


class TestStripeWebhook:
    def test_payment_succeeded(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import handle_stripe_webhook, get_subscription
        ws_id = sample_workspace["workspace"]["workspace_id"]
        result = handle_stripe_webhook(
            "invoice.payment_succeeded",
            {"metadata": {"workspace_id": ws_id}},
        )
        assert result["ok"] is True
        sub = get_subscription(ws_id)
        assert sub["status"] == "active"

    def test_payment_failed(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import handle_stripe_webhook, get_subscription
        ws_id = sample_workspace["workspace"]["workspace_id"]
        result = handle_stripe_webhook(
            "invoice.payment_failed",
            {"metadata": {"workspace_id": ws_id}},
        )
        assert result["ok"] is True
        sub = get_subscription(ws_id)
        assert sub["status"] == "past_due"

    def test_subscription_deleted(self, tmp_data_dir, sample_subscription, sample_workspace):
        from billing import handle_stripe_webhook, get_subscription
        ws_id = sample_workspace["workspace"]["workspace_id"]
        result = handle_stripe_webhook(
            "customer.subscription.deleted",
            {"metadata": {"workspace_id": ws_id}},
        )
        assert result["ok"] is True
        sub = get_subscription(ws_id)
        assert sub["status"] == "canceled"

    def test_no_workspace_id_graceful(self, tmp_data_dir):
        from billing import handle_stripe_webhook
        result = handle_stripe_webhook("invoice.payment_succeeded", {"metadata": {}})
        assert result["ok"] is False
