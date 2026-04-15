"""
Unit tests for core/schemas.py

Tests: input validation, field constraints, error messages.
"""

import pytest
from pydantic import ValidationError


class TestCreateContactRequest:
    def test_valid_minimal(self):
        from schemas import CreateContactRequest
        req = CreateContactRequest(name="Alice", phone="+919876543210")
        assert req.name == "Alice"
        assert req.phone == "+919876543210"

    def test_valid_full(self):
        from schemas import CreateContactRequest
        req = CreateContactRequest(
            name="Alice",
            phone="+919876543210",
            company="Acme",
            source="website",
            tags=["vip", "enterprise"],
            deal_value=50000.0,
        )
        assert req.company == "Acme"
        assert req.deal_value == 50000.0
        assert "vip" in req.tags

    def test_missing_name_fails(self):
        from schemas import CreateContactRequest
        with pytest.raises(ValidationError):
            CreateContactRequest(phone="+919876543210")

    def test_missing_phone_fails(self):
        from schemas import CreateContactRequest
        with pytest.raises(ValidationError):
            CreateContactRequest(name="Alice")

    def test_short_name_fails(self):
        from schemas import CreateContactRequest
        with pytest.raises(ValidationError):
            CreateContactRequest(name="", phone="+919876543210")

    def test_negative_deal_value_fails(self):
        from schemas import CreateContactRequest
        with pytest.raises(ValidationError):
            CreateContactRequest(name="Alice", phone="+919876543210", deal_value=-100)

    def test_tags_trimmed(self):
        from schemas import CreateContactRequest
        req = CreateContactRequest(name="Alice", phone="+919876543210", tags=["  vip  ", " "])
        assert "vip" in req.tags
        assert " " not in req.tags  # empty stripped tag removed


class TestCreateTemplateRequest:
    def test_valid_template(self):
        from schemas import CreateTemplateRequest
        req = CreateTemplateRequest(
            name="my_template",
            body="Hello {{1}}!",
            category="utility",
        )
        assert req.name == "my_template"

    def test_invalid_category(self):
        from schemas import CreateTemplateRequest
        with pytest.raises(ValidationError):
            CreateTemplateRequest(name="test", body="Hello", category="invalid_cat")

    def test_name_with_spaces_fails(self):
        from schemas import CreateTemplateRequest
        with pytest.raises(ValidationError):
            CreateTemplateRequest(name="my template", body="Hello", category="utility")

    def test_name_with_uppercase_fails(self):
        from schemas import CreateTemplateRequest
        with pytest.raises(ValidationError):
            CreateTemplateRequest(name="MyTemplate", body="Hello", category="utility")

    def test_too_many_buttons_fails(self):
        from schemas import CreateTemplateRequest
        with pytest.raises(ValidationError):
            CreateTemplateRequest(
                name="test",
                body="Hello",
                category="utility",
                buttons=[
                    {"type": "quick_reply", "text": "A"},
                    {"type": "quick_reply", "text": "B"},
                    {"type": "quick_reply", "text": "C"},
                    {"type": "quick_reply", "text": "D"},
                ],
            )


class TestCreateCampaignRequest:
    def test_valid_campaign(self):
        from schemas import CreateCampaignRequest
        req = CreateCampaignRequest(name="Test Campaign", template_id="tpl_abc")
        assert req.reply_mode == "auto_ai"

    def test_invalid_reply_mode(self):
        from schemas import CreateCampaignRequest
        with pytest.raises(ValidationError):
            CreateCampaignRequest(
                name="Test",
                template_id="tpl_abc",
                reply_mode="invalid_mode",
            )

    def test_empty_name_fails(self):
        from schemas import CreateCampaignRequest
        with pytest.raises(ValidationError):
            CreateCampaignRequest(name="", template_id="tpl_abc")


class TestLoginRequest:
    def test_valid_login(self):
        from schemas import LoginRequest
        req = LoginRequest(email="user@example.com", password="password123")
        assert req.email == "user@example.com"

    def test_email_lowercased(self):
        from schemas import LoginRequest
        req = LoginRequest(email="USER@EXAMPLE.COM", password="password123")
        assert req.email == "user@example.com"

    def test_invalid_email_fails(self):
        from schemas import LoginRequest
        with pytest.raises(ValidationError):
            LoginRequest(email="notanemail", password="password123")

    def test_short_password_fails(self):
        from schemas import LoginRequest
        with pytest.raises(ValidationError):
            LoginRequest(email="user@example.com", password="abc")


class TestCreateUserRequest:
    def test_valid_user(self):
        from schemas import CreateUserRequest
        req = CreateUserRequest(email="agent@biz.com", password="securepass", role="agent")
        assert req.role == "agent"

    def test_invalid_role_fails(self):
        from schemas import CreateUserRequest
        with pytest.raises(ValidationError):
            CreateUserRequest(email="x@biz.com", password="securepass", role="superadmin")

    def test_short_password_fails(self):
        from schemas import CreateUserRequest
        with pytest.raises(ValidationError):
            CreateUserRequest(email="x@biz.com", password="abc")


class TestSendMessageRequest:
    def test_valid_message(self):
        from schemas import SendMessageRequest
        req = SendMessageRequest(message="Hello there!")
        assert req.message == "Hello there!"

    def test_empty_message_fails(self):
        from schemas import SendMessageRequest
        with pytest.raises(ValidationError):
            SendMessageRequest(message="")

    def test_very_long_message_fails(self):
        from schemas import SendMessageRequest
        with pytest.raises(ValidationError):
            SendMessageRequest(message="A" * 5000)


class TestUpgradePlanRequest:
    def test_valid_plan(self):
        from schemas import UpgradePlanRequest
        req = UpgradePlanRequest(plan_id="growth")
        assert req.plan_id == "growth"

    def test_invalid_plan_fails(self):
        from schemas import UpgradePlanRequest
        with pytest.raises(ValidationError):
            UpgradePlanRequest(plan_id="superplan")


class TestSetReplyModeRequest:
    def test_valid_modes(self):
        from schemas import SetReplyModeRequest
        for mode in ("auto_ai", "human_only", "ai_draft"):
            req = SetReplyModeRequest(mode=mode)
            assert req.mode == mode

    def test_invalid_mode_fails(self):
        from schemas import SetReplyModeRequest
        with pytest.raises(ValidationError):
            SetReplyModeRequest(mode="random_mode")


class TestCreateInviteRequest:
    def test_valid_invite(self):
        from schemas import CreateInviteRequest
        req = CreateInviteRequest(email="new@biz.com", role="agent")
        assert req.email == "new@biz.com"

    def test_cannot_invite_as_owner(self):
        from schemas import CreateInviteRequest
        with pytest.raises(ValidationError):
            CreateInviteRequest(email="x@biz.com", role="owner")

    def test_invalid_email_fails(self):
        from schemas import CreateInviteRequest
        with pytest.raises(ValidationError):
            CreateInviteRequest(email="notanemail", role="agent")
