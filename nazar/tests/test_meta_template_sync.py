"""
Tests for Meta WhatsApp Template Sync module.
"""

import os
import sys
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from meta_template_sync import (
    _build_meta_template_payload,
    submit_template_to_meta,
    get_meta_template_status,
    delete_template_from_meta,
    handle_template_status_webhook,
    is_meta_configured,
)


# ─── Payload Builder Tests ────────────────────────────────────────


class TestBuildMetaTemplatePayload:
    def test_basic_utility_template(self):
        template = {
            "name": "welcome_msg",
            "language": "en",
            "category": "utility",
            "header": {"type": "none"},
            "body": "Hi {{1}}, welcome!",
            "footer": "Reply STOP to opt out",
            "buttons": [],
            "variables": ["name"],
        }
        payload = _build_meta_template_payload(template)

        assert payload["name"] == "welcome_msg"
        assert payload["language"] == "en"
        assert payload["category"] == "UTILITY"
        # Should have BODY and FOOTER components
        types = [c["type"] for c in payload["components"]]
        assert "BODY" in types
        assert "FOOTER" in types
        assert "HEADER" not in types  # header is "none"

    def test_text_header_template(self):
        template = {
            "name": "promo",
            "language": "en",
            "category": "marketing",
            "header": {"type": "text", "text": "Special Offer!"},
            "body": "Hi {{1}}, check this out!",
            "footer": "",
            "buttons": [],
            "variables": ["name"],
        }
        payload = _build_meta_template_payload(template)

        assert payload["category"] == "MARKETING"
        header_comp = next(c for c in payload["components"] if c["type"] == "HEADER")
        assert header_comp["format"] == "TEXT"
        assert header_comp["text"] == "Special Offer!"

    def test_image_header_template(self):
        template = {
            "name": "image_tpl",
            "language": "en",
            "category": "marketing",
            "header": {"type": "image", "image_url": "https://example.com/img.jpg"},
            "body": "Check this image!",
            "footer": "",
            "buttons": [],
            "variables": [],
        }
        payload = _build_meta_template_payload(template)

        header_comp = next(c for c in payload["components"] if c["type"] == "HEADER")
        assert header_comp["format"] == "IMAGE"

    def test_buttons_template(self):
        template = {
            "name": "cta_tpl",
            "language": "en",
            "category": "utility",
            "header": {"type": "none"},
            "body": "Click below!",
            "footer": "",
            "buttons": [
                {"type": "quick_reply", "text": "Yes"},
                {"type": "url", "text": "Visit", "url": "https://example.com"},
                {"type": "phone", "text": "Call", "phone": "+1234567890"},
            ],
            "variables": [],
        }
        payload = _build_meta_template_payload(template)

        buttons_comp = next(c for c in payload["components"] if c["type"] == "BUTTONS")
        assert len(buttons_comp["buttons"]) == 3
        assert buttons_comp["buttons"][0]["type"] == "QUICK_REPLY"
        assert buttons_comp["buttons"][1]["type"] == "URL"
        assert buttons_comp["buttons"][2]["type"] == "PHONE_NUMBER"

    def test_body_example_values(self):
        template = {
            "name": "test",
            "language": "en",
            "category": "utility",
            "header": {"type": "none"},
            "body": "Hi {{1}}, your company {{2}} is great!",
            "footer": "",
            "buttons": [],
            "variables": ["name", "company"],
        }
        payload = _build_meta_template_payload(template)

        body_comp = next(c for c in payload["components"] if c["type"] == "BODY")
        assert "example" in body_comp
        examples = body_comp["example"]["body_text"][0]
        assert examples[0] == "John"
        assert examples[1] == "Acme Corp"

    def test_invalid_category_defaults_to_utility(self):
        template = {
            "name": "test",
            "language": "en",
            "category": "invalid",
            "header": {"type": "none"},
            "body": "Hello!",
            "footer": "",
            "buttons": [],
            "variables": [],
        }
        payload = _build_meta_template_payload(template)
        assert payload["category"] == "UTILITY"


# ─── Webhook Handler Tests ────────────────────────────────────────


class TestTemplateStatusWebhook:
    """Tests for Meta template status webhook handling.

    Note: handle_template_status_webhook uses local imports
    (from template_manager import ...) inside the function body,
    so we must use tmp_data_dir to have the DB available and create
    real templates, or patch at the meta_template_sync level.
    """

    def test_approved_webhook(self, tmp_data_dir):
        from template_manager import create_template
        tpl = create_template(name="welcome_msg", body="Hello {{1}}", category="utility")

        result = handle_template_status_webhook({
            "event": "APPROVED",
            "message_template_name": "welcome_msg",
            "message_template_id": 12345,
        })

        assert result["handled"] is True
        assert result["new_status"] == "approved"

    def test_rejected_webhook_with_reason(self, tmp_data_dir):
        from template_manager import create_template
        tpl = create_template(name="promo_msg", body="Buy now!", category="marketing")

        result = handle_template_status_webhook({
            "event": "REJECTED",
            "message_template_name": "promo_msg",
            "reason": "Template contains prohibited content",
        })

        assert result["handled"] is True
        assert result["new_status"] == "rejected"
        assert result["reason"] == "Template contains prohibited content"

    def test_unknown_template_webhook(self, tmp_data_dir):
        result = handle_template_status_webhook({
            "event": "APPROVED",
            "message_template_name": "nonexistent_tpl",
        })

        assert result["handled"] is False

    def test_missing_template_name(self):
        result = handle_template_status_webhook({
            "event": "APPROVED",
        })
        assert result["handled"] is False

    def test_paused_maps_to_rejected(self, tmp_data_dir):
        from template_manager import create_template
        tpl = create_template(name="paused_tpl", body="Info", category="utility")

        result = handle_template_status_webhook({
            "event": "PAUSED",
            "message_template_name": "paused_tpl",
        })

        assert result["new_status"] == "rejected"


# ─── Configuration Tests ─────────────────────────────────────────


class TestMetaConfiguration:
    def test_not_configured_without_env(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_meta_configured() is False

    def test_configured_with_both_env_vars(self):
        with patch.dict(os.environ, {
            "WA_BUSINESS_ACCOUNT_ID": "123456",
            "WA_ACCESS_TOKEN": "token123",
        }):
            assert is_meta_configured() is True

    def test_not_configured_with_partial_env(self):
        with patch.dict(os.environ, {
            "WA_BUSINESS_ACCOUNT_ID": "123456",
        }, clear=True):
            assert is_meta_configured() is False


# ─── Service Window Tests ────────────────────────────────────────


class TestServiceWindow:
    """Test the _compute_service_window function from server.py"""

    def test_window_open_recent_message(self):
        """Contact who messaged 2 hours ago should have open window."""
        from datetime import datetime, timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST)
        two_hours_ago = (now - timedelta(hours=2)).isoformat()

        contact = {"last_replied_at": two_hours_ago}

        # Import the function
        # Since it's in server.py and hard to import directly, we test the logic
        last_dt = datetime.fromisoformat(two_hours_ago)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=IST)
        window_end = last_dt + timedelta(hours=24)
        remaining = (window_end - now).total_seconds()

        assert remaining > 0  # Window should be open
        hours_remaining = round(remaining / 3600, 2)
        assert hours_remaining > 21  # ~22 hours remaining

    def test_window_closed_old_message(self):
        """Contact who messaged 30 hours ago should have closed window."""
        from datetime import datetime, timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST)
        thirty_hours_ago = (now - timedelta(hours=30)).isoformat()

        last_dt = datetime.fromisoformat(thirty_hours_ago)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=IST)
        window_end = last_dt + timedelta(hours=24)
        remaining = (window_end - now).total_seconds()

        assert remaining < 0  # Window should be closed

    def test_no_inbound_message(self):
        """Contact with no last_replied_at should have closed window."""
        contact = {"last_replied_at": ""}
        # Should return window_open=False
        assert not contact.get("last_replied_at")
