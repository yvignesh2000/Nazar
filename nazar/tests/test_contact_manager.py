"""
Unit tests for core/contact_manager.py

Tests: CRUD, pipeline, scoring, tags, phone normalization,
       CSV import, conversation logging, duplicate prevention.
"""

import json
import pytest
import shutil
from pathlib import Path


# ---------------------------------------------------------------------------
# Phone normalization
# ---------------------------------------------------------------------------

class TestPhoneNormalization:
    def test_adds_plus_prefix(self):
        from contact_manager import normalize_phone
        assert normalize_phone("919876543210") == "+919876543210"

    def test_preserves_plus_prefix(self):
        from contact_manager import normalize_phone
        assert normalize_phone("+919876543210") == "+919876543210"

    def test_strips_spaces(self):
        from contact_manager import normalize_phone
        assert normalize_phone("+91 98765 43210") == "+919876543210"

    def test_strips_dashes(self):
        from contact_manager import normalize_phone
        assert normalize_phone("+91-9876-543210") == "+919876543210"

    def test_strips_parentheses(self):
        from contact_manager import normalize_phone
        assert normalize_phone("+91(9876)543210") == "+919876543210"


# ---------------------------------------------------------------------------
# Contact CRUD
# ---------------------------------------------------------------------------

class TestContactCRUD:
    def test_create_contact(self, tmp_data_dir):
        from contact_manager import create_contact
        c = create_contact("Raj Kumar", "+919876543210", company="Acme")
        assert c["contact_id"]
        assert c["name"] == "Raj Kumar"
        assert c["phone"] == "+919876543210"
        assert c["pipeline_stage"] == "New"
        assert c["company"] == "Acme"

    def test_create_contact_with_tags(self, tmp_data_dir):
        from contact_manager import create_contact
        c = create_contact("Raj", "+919876543210", tags=["enterprise", "vip"])
        assert "enterprise" in c["tags"]
        assert "vip" in c["tags"]

    def test_get_contact(self, tmp_data_dir, sample_contact):
        from contact_manager import get_contact
        fetched = get_contact(sample_contact["contact_id"])
        assert fetched["name"] == sample_contact["name"]
        assert fetched["phone"] == sample_contact["phone"]

    def test_get_contact_not_found(self, tmp_data_dir):
        from contact_manager import get_contact
        with pytest.raises(FileNotFoundError):
            get_contact("nonexistent_id")

    def test_update_contact(self, tmp_data_dir, sample_contact):
        from contact_manager import update_contact
        updated = update_contact(
            sample_contact["contact_id"],
            deal_value=100000.0,
            notes="Hot lead"
        )
        assert updated["deal_value"] == 100000.0
        assert updated["notes"] == "Hot lead"

    def test_update_contact_invalid_stage(self, tmp_data_dir, sample_contact):
        from contact_manager import update_contact
        with pytest.raises(ValueError):
            update_contact(sample_contact["contact_id"], pipeline_stage="InvalidStage")

    def test_delete_contact(self, tmp_data_dir, sample_contact):
        from contact_manager import delete_contact, get_contact
        delete_contact(sample_contact["contact_id"])
        with pytest.raises(FileNotFoundError):
            get_contact(sample_contact["contact_id"])

    def test_duplicate_phone_rejected(self, tmp_data_dir, sample_contact):
        from contact_manager import create_contact
        with pytest.raises(ValueError, match="already exists"):
            create_contact("Duplicate", "+919876543210")

    def test_contact_exists(self, tmp_data_dir, sample_contact):
        from contact_manager import contact_exists
        assert contact_exists("+919876543210") is True
        assert contact_exists("+910000000000") is False

    def test_get_contact_by_phone(self, tmp_data_dir, sample_contact):
        from contact_manager import get_contact_by_phone
        found = get_contact_by_phone("+919876543210")
        assert found is not None
        assert found["contact_id"] == sample_contact["contact_id"]

    def test_get_contact_by_phone_normalizes(self, tmp_data_dir, sample_contact):
        from contact_manager import get_contact_by_phone
        found = get_contact_by_phone("919876543210")  # No +
        assert found is not None

    def test_get_contact_by_phone_not_found(self, tmp_data_dir):
        from contact_manager import get_contact_by_phone
        assert get_contact_by_phone("+910000000000") is None


# ---------------------------------------------------------------------------
# Pipeline management
# ---------------------------------------------------------------------------

class TestPipeline:
    def test_move_stage(self, tmp_data_dir, sample_contact):
        from contact_manager import move_stage
        moved = move_stage(sample_contact["contact_id"], "Qualified")
        assert moved["pipeline_stage"] == "Qualified"

    def test_move_invalid_stage(self, tmp_data_dir, sample_contact):
        from contact_manager import move_stage
        with pytest.raises(ValueError):
            move_stage(sample_contact["contact_id"], "Garbage")

    def test_pipeline_stages_valid(self):
        from contact_manager import PIPELINE_STAGES
        assert "New" in PIPELINE_STAGES
        assert "Won" in PIPELINE_STAGES
        assert "Lost" in PIPELINE_STAGES

    def test_lead_score(self, tmp_data_dir, sample_contact):
        from contact_manager import update_lead_score
        scored = update_lead_score(sample_contact["contact_id"], 80)
        assert scored["lead_score"] == 80

    def test_lead_score_out_of_range(self, tmp_data_dir, sample_contact):
        from contact_manager import update_lead_score
        with pytest.raises(ValueError):
            update_lead_score(sample_contact["contact_id"], 150)

    def test_pipeline_summary(self, tmp_data_dir, sample_contact, sample_contact_2):
        from contact_manager import move_stage, update_contact, get_pipeline_summary
        move_stage(sample_contact["contact_id"], "Qualified")
        update_contact(sample_contact["contact_id"], deal_value=50000)
        summary = get_pipeline_summary()
        assert summary["Qualified"]["count"] == 1
        assert summary["Qualified"]["total_value"] == 50000.0


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TestTags:
    def test_add_tag(self, tmp_data_dir, sample_contact):
        from contact_manager import add_tag
        tagged = add_tag(sample_contact["contact_id"], "vip")
        assert "vip" in tagged["tags"]

    def test_add_duplicate_tag(self, tmp_data_dir, sample_contact):
        from contact_manager import add_tag
        add_tag(sample_contact["contact_id"], "vip")
        tagged = add_tag(sample_contact["contact_id"], "vip")
        assert tagged["tags"].count("vip") == 1

    def test_remove_tag(self, tmp_data_dir, sample_contact):
        from contact_manager import add_tag, remove_tag
        add_tag(sample_contact["contact_id"], "vip")
        untagged = remove_tag(sample_contact["contact_id"], "vip")
        assert "vip" not in untagged["tags"]

    def test_remove_nonexistent_tag(self, tmp_data_dir, sample_contact):
        from contact_manager import remove_tag
        result = remove_tag(sample_contact["contact_id"], "nonexistent")
        assert result is not None  # Should not raise


# ---------------------------------------------------------------------------
# Contact listing and filtering
# ---------------------------------------------------------------------------

class TestContactListing:
    def test_list_all(self, tmp_data_dir, sample_contact, sample_contact_2):
        from contact_manager import list_contacts
        contacts = list_contacts()
        assert len(contacts) == 2

    def test_filter_by_stage(self, tmp_data_dir, sample_contact, sample_contact_2):
        from contact_manager import list_contacts, move_stage
        move_stage(sample_contact["contact_id"], "Qualified")
        qualified = list_contacts(stage="Qualified")
        assert len(qualified) == 1
        assert qualified[0]["contact_id"] == sample_contact["contact_id"]

    def test_filter_by_tag(self, tmp_data_dir, sample_contact, sample_contact_2):
        from contact_manager import list_contacts
        enterprise = list_contacts(tag="enterprise")
        assert len(enterprise) == 1

    def test_list_empty(self, tmp_data_dir):
        from contact_manager import list_contacts
        contacts = list_contacts()
        assert contacts == []


# ---------------------------------------------------------------------------
# Conversation logging
# ---------------------------------------------------------------------------

class TestConversationLogging:
    def test_save_inbound_message(self, tmp_data_dir, sample_contact):
        from contact_manager import save_message, get_today_conversation
        msg = save_message(sample_contact["contact_id"], "inbound", "Hello!")
        assert msg["direction"] == "inbound"
        assert msg["content"] == "Hello!"

    def test_save_outbound_message(self, tmp_data_dir, sample_contact):
        from contact_manager import save_message, get_today_conversation
        save_message(sample_contact["contact_id"], "outbound", "Hi there!", sent_by="bot")
        today = get_today_conversation(sample_contact["contact_id"])
        assert len(today) == 1
        assert today[0]["sent_by"] == "bot"

    def test_get_conversation_history(self, tmp_data_dir, sample_contact):
        from contact_manager import save_message, get_conversation_history
        save_message(sample_contact["contact_id"], "inbound", "Msg 1")
        save_message(sample_contact["contact_id"], "outbound", "Reply 1")
        history = get_conversation_history(sample_contact["contact_id"], days=7)
        assert len(history) == 2

    def test_message_updates_contact_stats(self, tmp_data_dir, sample_contact):
        from contact_manager import save_message, get_contact
        save_message(sample_contact["contact_id"], "inbound", "Test msg")
        updated = get_contact(sample_contact["contact_id"])
        assert updated["last_replied_at"] is not None
        assert updated["total_messages"] >= 1


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

class TestCSVImport:
    def test_basic_import(self, tmp_data_dir):
        from contact_manager import import_contacts_csv
        csv_data = "name,phone\nAlice,+911111111111\nBob,+912222222222"
        result = import_contacts_csv(csv_data)
        assert result["created"] == 2
        assert result["skipped"] == 0
        assert len(result["errors"]) == 0

    def test_import_with_tags(self, tmp_data_dir):
        from contact_manager import import_contacts_csv, list_contacts
        csv_data = "name,phone,tags\nAlice,+911111111111,vip;enterprise"
        import_contacts_csv(csv_data)
        contacts = list_contacts()
        alice = contacts[0]
        assert "vip" in alice["tags"]
        assert "enterprise" in alice["tags"]

    def test_import_skips_duplicates(self, tmp_data_dir, sample_contact):
        from contact_manager import import_contacts_csv
        csv_data = "name,phone\nDupe,+919876543210"
        result = import_contacts_csv(csv_data)
        assert result["created"] == 0
        assert result["skipped"] == 1

    def test_import_missing_required_fields(self, tmp_data_dir):
        from contact_manager import import_contacts_csv
        csv_data = "name,phone\n,+911111111111\n"
        result = import_contacts_csv(csv_data)
        assert len(result["errors"]) >= 1

    def test_import_missing_headers(self, tmp_data_dir):
        from contact_manager import import_contacts_csv
        csv_data = "email,age\nalice@test.com,25"
        result = import_contacts_csv(csv_data)
        assert len(result["errors"]) >= 1
