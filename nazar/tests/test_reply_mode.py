"""
Unit tests for core/reply_mode.py

Tests: reply mode CRUD, draft management, campaign association,
       effective mode resolution, campaign KB storage.
"""

import pytest


class TestReplyModeCRUD:
    def test_default_mode_is_auto_ai(self, tmp_data_dir):
        from reply_mode import get_contact_reply_mode
        assert get_contact_reply_mode("c1") == "auto_ai"

    def test_set_contact_reply_mode(self, tmp_data_dir):
        from reply_mode import set_contact_reply_mode, get_contact_reply_mode
        set_contact_reply_mode("c1", "human_only")
        assert get_contact_reply_mode("c1") == "human_only"

    def test_set_all_valid_modes(self, tmp_data_dir):
        from reply_mode import set_contact_reply_mode
        for mode in ("auto_ai", "human_only", "ai_draft"):
            entry = set_contact_reply_mode("c1", mode)
            assert entry["mode"] == mode

    def test_invalid_mode_raises(self, tmp_data_dir):
        from reply_mode import set_contact_reply_mode
        with pytest.raises(ValueError, match="Invalid reply mode"):
            set_contact_reply_mode("c1", "invalid_mode")

    def test_clear_contact_reply_mode(self, tmp_data_dir):
        from reply_mode import set_contact_reply_mode, clear_contact_reply_mode, get_contact_reply_mode
        set_contact_reply_mode("c1", "human_only")
        clear_contact_reply_mode("c1")
        assert get_contact_reply_mode("c1") == "auto_ai"

    def test_clear_nonexistent_mode_safe(self, tmp_data_dir):
        from reply_mode import clear_contact_reply_mode
        # Should not raise
        clear_contact_reply_mode("nonexistent_contact")


class TestDraftManagement:
    def test_save_and_get_draft(self, tmp_data_dir):
        from reply_mode import save_draft, get_draft
        entry = save_draft("c1", "Hello there!", customer_message="What's the price?")
        assert entry["status"] == "pending"
        assert entry["draft"] == "Hello there!"

        draft = get_draft("c1")
        assert draft is not None
        assert draft["draft"] == "Hello there!"

    def test_get_draft_returns_none_when_missing(self, tmp_data_dir):
        from reply_mode import get_draft
        assert get_draft("no_contact") is None

    def test_get_all_pending_drafts(self, tmp_data_dir):
        from reply_mode import save_draft, get_all_pending_drafts
        save_draft("c1", "Draft 1", customer_message="Msg 1")
        save_draft("c2", "Draft 2", customer_message="Msg 2")
        drafts = get_all_pending_drafts()
        assert len(drafts) == 2

    def test_approve_draft(self, tmp_data_dir):
        from reply_mode import save_draft, approve_draft, get_draft
        save_draft("c1", "Original draft", customer_message="test")
        entry = approve_draft("c1")
        assert entry["status"] == "approved"
        assert entry["final_text"] == "Original draft"
        # No longer pending
        assert get_draft("c1") is None

    def test_approve_with_edit(self, tmp_data_dir):
        from reply_mode import save_draft, approve_draft
        save_draft("c1", "Original draft", customer_message="test")
        entry = approve_draft("c1", edited_text="Edited reply!")
        assert entry["status"] == "edited"
        assert entry["final_text"] == "Edited reply!"

    def test_reject_draft(self, tmp_data_dir):
        from reply_mode import save_draft, reject_draft, get_draft
        save_draft("c1", "Draft", customer_message="test")
        entry = reject_draft("c1")
        assert entry["status"] == "rejected"
        assert get_draft("c1") is None

    def test_approve_nonexistent_draft_returns_none(self, tmp_data_dir):
        from reply_mode import approve_draft
        assert approve_draft("no_contact") is None

    def test_clear_draft(self, tmp_data_dir):
        from reply_mode import save_draft, clear_draft, get_draft
        save_draft("c1", "Draft", customer_message="test")
        clear_draft("c1")
        assert get_draft("c1") is None


class TestCampaignAssociation:
    def test_associate_and_get(self, tmp_data_dir):
        from reply_mode import associate_contacts_to_campaign, get_contact_campaign
        associate_contacts_to_campaign(["c1", "c2"], "cmp_abc")
        assert get_contact_campaign("c1") == "cmp_abc"
        assert get_contact_campaign("c2") == "cmp_abc"

    def test_no_association_returns_none(self, tmp_data_dir):
        from reply_mode import get_contact_campaign
        assert get_contact_campaign("no_contact") is None

    def test_clear_campaign_association(self, tmp_data_dir):
        from reply_mode import associate_contacts_to_campaign, clear_contact_campaign, get_contact_campaign
        associate_contacts_to_campaign(["c1"], "cmp_abc")
        clear_contact_campaign("c1")
        assert get_contact_campaign("c1") is None


class TestCampaignKB:
    def test_save_and_get_kb(self, tmp_data_dir):
        from reply_mode import save_campaign_kb, get_campaign_kb
        save_campaign_kb("cmp_abc", "Campaign product details here.")
        kb = get_campaign_kb("cmp_abc")
        assert "Campaign product" in kb

    def test_get_kb_missing_returns_empty(self, tmp_data_dir):
        from reply_mode import get_campaign_kb
        assert get_campaign_kb("cmp_nonexistent") == ""

    def test_delete_campaign_kb(self, tmp_data_dir):
        from reply_mode import save_campaign_kb, delete_campaign_kb, get_campaign_kb
        save_campaign_kb("cmp_abc", "Content here.")
        delete_campaign_kb("cmp_abc")
        assert get_campaign_kb("cmp_abc") == ""


class TestEffectiveModeResolution:
    def test_default_is_auto_ai(self, tmp_data_dir):
        from reply_mode import get_effective_reply_mode
        result = get_effective_reply_mode("new_contact")
        assert result["mode"] == "auto_ai"
        assert result["source"] == "default"

    def test_contact_override_wins(self, tmp_data_dir):
        from reply_mode import set_contact_reply_mode, get_effective_reply_mode
        set_contact_reply_mode("c1", "human_only")
        result = get_effective_reply_mode("c1")
        assert result["mode"] == "human_only"
        assert result["source"] == "contact"

    def test_auto_ai_contact_does_not_override(self, tmp_data_dir):
        """Setting auto_ai (default) shouldn't count as a contact override."""
        from reply_mode import set_contact_reply_mode, get_effective_reply_mode
        set_contact_reply_mode("c1", "auto_ai")
        result = get_effective_reply_mode("c1")
        # source should be 'default' not 'contact' since auto_ai is the default
        assert result["mode"] == "auto_ai"
