"""
Nazar — SQLite Database Layer Tests

Tests schema creation, CRUD operations across all migrated modules,
data integrity, concurrent access safety, and migration scenarios.
"""

import json
import pytest
import threading
import time
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Database init & schema
# ──────────────────────────────────────────────────────────────────────────────

class TestDatabaseInit:
    def test_init_creates_tables(self, tmp_data_dir):
        """init_db should create all expected tables."""
        from database import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        names = {r["name"] for r in rows}
        expected = {
            "contacts", "messages", "campaigns", "handoff_states",
            "handoff_events", "reply_modes", "campaign_contacts",
            "ai_drafts", "optouts", "assignments", "segments",
            "webhooks", "audit_log",
        }
        assert expected.issubset(names), f"Missing tables: {expected - names}"

    def test_init_is_idempotent(self, tmp_data_dir):
        """Calling init_db multiple times should not error."""
        from database import init_db, DB_PATH
        init_db(DB_PATH)
        init_db(DB_PATH)  # Should not raise

    def test_wal_mode_enabled(self, tmp_data_dir):
        """WAL journal mode should be set for concurrent read safety."""
        from database import get_db
        with get_db() as conn:
            row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"


# ──────────────────────────────────────────────────────────────────────────────
# Contact Manager (SQLite)
# ──────────────────────────────────────────────────────────────────────────────

class TestContactManagerSQLite:
    def test_create_and_get(self, sample_contact):
        """Create a contact and retrieve it."""
        from contact_manager import get_contact
        c = get_contact(sample_contact["contact_id"])
        assert c["name"] == "Test User"
        assert c["phone"] == "+919876543210"
        assert c["pipeline_stage"] == "New"
        assert c["tags"] == ["enterprise"]

    def test_duplicate_phone_rejected(self, sample_contact):
        """Creating a contact with the same phone should raise ValueError."""
        from contact_manager import create_contact
        with pytest.raises(ValueError, match="already exists"):
            create_contact("Another User", "+919876543210")

    def test_update_contact(self, sample_contact):
        """Update should persist changes."""
        from contact_manager import update_contact, get_contact
        updated = update_contact(
            sample_contact["contact_id"],
            deal_value=50000,
            notes="Hot lead",
        )
        assert updated["deal_value"] == 50000
        fetched = get_contact(sample_contact["contact_id"])
        assert fetched["notes"] == "Hot lead"

    def test_move_stage(self, sample_contact):
        """Pipeline stage change should persist."""
        from contact_manager import move_stage
        moved = move_stage(sample_contact["contact_id"], "Qualified")
        assert moved["pipeline_stage"] == "Qualified"

    def test_invalid_stage_rejected(self, sample_contact):
        """Invalid pipeline stage should raise ValueError."""
        from contact_manager import move_stage
        with pytest.raises(ValueError):
            move_stage(sample_contact["contact_id"], "InvalidStage")

    def test_lead_score(self, sample_contact):
        """Lead score update should work and enforce 0-100 range."""
        from contact_manager import update_lead_score
        scored = update_lead_score(sample_contact["contact_id"], 75)
        assert scored["lead_score"] == 75

        with pytest.raises(ValueError):
            update_lead_score(sample_contact["contact_id"], 150)

    def test_tags(self, sample_contact):
        """Tag add/remove should work correctly."""
        from contact_manager import add_tag, remove_tag
        tagged = add_tag(sample_contact["contact_id"], "vip")
        assert "vip" in tagged["tags"]
        assert "enterprise" in tagged["tags"]

        untagged = remove_tag(sample_contact["contact_id"], "enterprise")
        assert "enterprise" not in untagged["tags"]
        assert "vip" in untagged["tags"]

    def test_list_contacts(self, sample_contact, sample_contact_2):
        """list_contacts should return all contacts, with filtering."""
        from contact_manager import list_contacts, move_stage
        all_c = list_contacts()
        assert len(all_c) == 2

        move_stage(sample_contact["contact_id"], "Qualified")
        qualified = list_contacts(stage="Qualified")
        assert len(qualified) == 1
        assert qualified[0]["contact_id"] == sample_contact["contact_id"]

    def test_list_contacts_by_tag(self, sample_contact, sample_contact_2):
        """Tag-based filtering should work."""
        from contact_manager import list_contacts
        enterprise = list_contacts(tag="enterprise")
        assert len(enterprise) == 1
        assert enterprise[0]["name"] == "Test User"

    def test_get_contact_by_phone(self, sample_contact):
        """Phone lookup should return the correct contact."""
        from contact_manager import get_contact_by_phone
        found = get_contact_by_phone("+919876543210")
        assert found is not None
        assert found["contact_id"] == sample_contact["contact_id"]

        not_found = get_contact_by_phone("+910000000000")
        assert not_found is None

    def test_delete_contact(self, sample_contact):
        """Deleting should remove contact and their messages."""
        from contact_manager import delete_contact, get_contact, save_message

        save_message(sample_contact["contact_id"], "inbound", "Hello")
        delete_contact(sample_contact["contact_id"])

        with pytest.raises(FileNotFoundError):
            get_contact(sample_contact["contact_id"])

    def test_pipeline_summary(self, sample_contact, sample_contact_2):
        """Pipeline summary should aggregate correctly."""
        from contact_manager import get_pipeline_summary, move_stage, update_contact
        move_stage(sample_contact["contact_id"], "Qualified")
        update_contact(sample_contact["contact_id"], deal_value=50000)

        summary = get_pipeline_summary()
        assert summary["Qualified"]["count"] == 1
        assert summary["Qualified"]["total_value"] == 50000
        assert summary["New"]["count"] == 1

    def test_contact_exists(self, sample_contact):
        """contact_exists should correctly report existence."""
        from contact_manager import contact_exists
        assert contact_exists("+919876543210") is True
        assert contact_exists("+910000000000") is False

    def test_csv_import(self, tmp_data_dir):
        """CSV import should create contacts and handle duplicates."""
        from contact_manager import import_contacts_csv, create_contact

        create_contact("Existing", "+919876543210")

        csv_data = """name,phone,company,tags,source
Amit Patel,+919876543212,Gamma Ltd,hot;enterprise,referral
Existing,+919876543210,Acme Corp,enterprise,website
,+919876543213,,,,
Neha Gupta,+919876543214,Delta Co,sme,cold-call
"""
        result = import_contacts_csv(csv_data)
        assert result["created"] == 2
        assert result["skipped"] == 1
        assert len(result["errors"]) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Messages
# ──────────────────────────────────────────────────────────────────────────────

class TestMessages:
    def test_save_and_retrieve(self, sample_contact):
        """Save messages and retrieve them."""
        from contact_manager import save_message, get_today_conversation

        save_message(sample_contact["contact_id"], "outbound", "Hi there!", sent_by="bot")
        save_message(sample_contact["contact_id"], "inbound", "Hello!", sent_by="customer")

        msgs = get_today_conversation(sample_contact["contact_id"])
        assert len(msgs) == 2
        assert msgs[0]["direction"] == "outbound"
        assert msgs[1]["content"] == "Hello!"

    def test_conversation_history(self, sample_contact):
        """History should retrieve messages within the day range."""
        from contact_manager import save_message, get_conversation_history

        save_message(sample_contact["contact_id"], "inbound", "msg1")
        save_message(sample_contact["contact_id"], "outbound", "msg2")

        history = get_conversation_history(sample_contact["contact_id"], days=7)
        assert len(history) == 2
        # Should be sorted by timestamp ASC
        assert history[0]["content"] == "msg1"

    def test_message_updates_contact_stats(self, sample_contact):
        """Saving a message should increment total_messages on the contact."""
        from contact_manager import save_message, get_contact

        save_message(sample_contact["contact_id"], "inbound", "Hello")
        save_message(sample_contact["contact_id"], "outbound", "Hi back")

        c = get_contact(sample_contact["contact_id"])
        assert c["total_messages"] == 2
        assert c["last_replied_at"] is not None
        assert c["last_contacted_at"] is not None


# ──────────────────────────────────────────────────────────────────────────────
# Campaigns (SQLite)
# ──────────────────────────────────────────────────────────────────────────────

class TestCampaigns:
    def test_create_and_get(self, tmp_data_dir):
        """Create a campaign and retrieve it."""
        from outbound import create_campaign, get_campaign

        c = create_campaign(
            name="Summer Sale",
            template_id="tpl_1",
            template_name="summer_offer",
            target_count=100,
            sent=95,
            failed=5,
            delivered=90,
        )
        assert c["id"].startswith("cmp_")
        assert c["sent"] == 95

        fetched = get_campaign(c["id"])
        assert fetched["name"] == "Summer Sale"
        assert fetched["delivered"] == 90

    def test_campaign_history(self, tmp_data_dir):
        """Campaign history should be newest first."""
        from outbound import create_campaign, get_campaign_history
        import time

        create_campaign("First", "t1", "t1", 10, sent=10)
        time.sleep(0.01)
        create_campaign("Second", "t2", "t2", 20, sent=20)

        history = get_campaign_history(limit=10)
        assert len(history) == 2
        assert history[0]["name"] == "Second"

    def test_campaign_stats(self, tmp_data_dir):
        """Aggregate stats should sum correctly."""
        from outbound import create_campaign, get_campaign_stats

        create_campaign("A", "t1", "t1", 50, sent=45, failed=5, delivered=40)
        create_campaign("B", "t2", "t2", 100, sent=90, failed=10, delivered=80)

        stats = get_campaign_stats()
        assert stats["total_campaigns"] == 2
        assert stats["total_sent"] == 135
        assert stats["total_failed"] == 15

    def test_update_campaign(self, tmp_data_dir):
        """Campaign update should persist changes."""
        from outbound import create_campaign, update_campaign, get_campaign

        c = create_campaign(
            "Test", "t1", "t1", 50,
            scheduled_at="2099-01-01T10:00:00",  # Creates with status="scheduled"
        )
        assert c["status"] == "scheduled"

        update_campaign(c["id"], status="sending")

        fetched = get_campaign(c["id"])
        assert fetched["status"] == "sending"


# ──────────────────────────────────────────────────────────────────────────────
# Handoff Manager (SQLite)
# ──────────────────────────────────────────────────────────────────────────────

class TestHandoffSQLite:
    def test_trigger_and_check(self, sample_contact):
        """Triggering a handoff should turn off the bot."""
        from handoff_manager import trigger_handoff, is_bot_active

        assert is_bot_active(sample_contact["contact_id"]) is True

        trigger_handoff(
            sample_contact["contact_id"],
            reason="Customer requested human",
            contact_name="Test User",
        )
        assert is_bot_active(sample_contact["contact_id"]) is False

    def test_resume(self, sample_contact):
        """Resuming should turn the bot back on."""
        from handoff_manager import trigger_handoff, resume_bot, is_bot_active

        trigger_handoff(sample_contact["contact_id"], reason="test")
        assert is_bot_active(sample_contact["contact_id"]) is False

        resume_bot(sample_contact["contact_id"], resumed_by="manual")
        assert is_bot_active(sample_contact["contact_id"]) is True

    def test_handoff_queue(self, sample_contact, sample_contact_2):
        """Queue should only contain contacts with bot off."""
        from handoff_manager import trigger_handoff, get_handoff_queue

        trigger_handoff(sample_contact["contact_id"], reason="r1", contact_name="A")
        trigger_handoff(sample_contact_2["contact_id"], reason="r2", contact_name="B")

        queue = get_handoff_queue()
        assert len(queue) == 2

    def test_handoff_history(self, sample_contact):
        """History should record trigger and resume events."""
        from handoff_manager import trigger_handoff, resume_bot, get_handoff_history

        trigger_handoff(sample_contact["contact_id"], reason="test")
        resume_bot(sample_contact["contact_id"])

        history = get_handoff_history()
        events = [h["event"] for h in history]
        assert "handoff_triggered" in events
        assert "bot_resumed" in events

    def test_handoff_stats(self, sample_contact):
        """Stats should count correctly."""
        from handoff_manager import trigger_handoff, resume_bot, get_handoff_stats

        trigger_handoff(sample_contact["contact_id"], reason="test", detection_method="keyword")
        resume_bot(sample_contact["contact_id"])

        stats = get_handoff_stats()
        assert stats["total_handoffs"] >= 1
        assert stats["total_resumes"] >= 1


# ──────────────────────────────────────────────────────────────────────────────
# Reply Mode (SQLite)
# ──────────────────────────────────────────────────────────────────────────────

class TestReplyModeSQLite:
    def test_set_and_get(self, sample_contact):
        """Setting a reply mode should persist."""
        from reply_mode import set_contact_reply_mode, get_contact_reply_mode

        set_contact_reply_mode(sample_contact["contact_id"], "ai_draft")
        mode = get_contact_reply_mode(sample_contact["contact_id"])
        assert mode == "ai_draft"

    def test_clear(self, sample_contact):
        """Clearing should revert to default."""
        from reply_mode import set_contact_reply_mode, clear_contact_reply_mode, get_contact_reply_mode

        set_contact_reply_mode(sample_contact["contact_id"], "human_only")
        clear_contact_reply_mode(sample_contact["contact_id"])
        mode = get_contact_reply_mode(sample_contact["contact_id"])
        assert mode == "auto_ai"

    def test_effective_mode_default(self, sample_contact):
        """Default effective mode should be auto_ai."""
        from reply_mode import get_effective_reply_mode

        result = get_effective_reply_mode(sample_contact["contact_id"])
        assert result["mode"] == "auto_ai"
        assert result["source"] == "default"

    def test_effective_mode_contact_override(self, sample_contact):
        """Contact override should take priority."""
        from reply_mode import set_contact_reply_mode, get_effective_reply_mode

        set_contact_reply_mode(sample_contact["contact_id"], "human_only")
        result = get_effective_reply_mode(sample_contact["contact_id"])
        assert result["mode"] == "human_only"
        assert result["source"] == "contact"

    def test_drafts(self, sample_contact):
        """AI draft CRUD should work."""
        from reply_mode import save_draft, get_draft, approve_draft, get_all_pending_drafts

        save_draft(
            sample_contact["contact_id"],
            "Here is a draft reply",
            customer_message="What's the price?",
        )

        draft = get_draft(sample_contact["contact_id"])
        assert draft is not None
        assert draft["draft"] == "Here is a draft reply"

        pending = get_all_pending_drafts()
        assert len(pending) == 1

        approved = approve_draft(sample_contact["contact_id"])
        assert approved["status"] == "approved"
        assert approved["final_text"] == "Here is a draft reply"

        # After approval, get_draft should return None (not pending)
        assert get_draft(sample_contact["contact_id"]) is None

    def test_draft_reject(self, sample_contact):
        """Rejecting a draft should update status."""
        from reply_mode import save_draft, reject_draft

        save_draft(sample_contact["contact_id"], "Draft text")
        rejected = reject_draft(sample_contact["contact_id"])
        assert rejected["status"] == "rejected"


# ──────────────────────────────────────────────────────────────────────────────
# Opt-out (SQLite)
# ──────────────────────────────────────────────────────────────────────────────

class TestOptoutSQLite:
    def test_optout_flow(self, tmp_data_dir):
        """Opt-out should block messaging, opt-in should re-enable."""
        from optout_manager import record_optout, record_optin, is_opted_out, can_message

        assert can_message("+919876543210") is True

        record_optout("+919876543210", reason="STOP", message="STOP")
        assert is_opted_out("+919876543210") is True
        assert can_message("+919876543210") is False

        record_optin("+919876543210")
        assert is_opted_out("+919876543210") is False
        assert can_message("+919876543210") is True

    def test_list_optouts(self, tmp_data_dir):
        """list_optouts should return all opted-out contacts."""
        from optout_manager import record_optout, list_optouts, get_optout_count

        record_optout("+911111111111")
        record_optout("+912222222222")

        optouts = list_optouts()
        assert len(optouts) == 2
        assert get_optout_count() == 2

    def test_keyword_detection(self, tmp_data_dir):
        """Stop/start message detection should be accurate."""
        from optout_manager import is_stop_message, is_start_message

        assert is_stop_message("STOP") is True
        assert is_stop_message("unsubscribe") is True
        assert is_stop_message("please stop messaging me") is True
        assert is_stop_message("What is your price?") is False

        assert is_start_message("START") is True
        assert is_start_message("subscribe") is True
        assert is_start_message("hello") is False


# ──────────────────────────────────────────────────────────────────────────────
# Assignment Manager (SQLite)
# ──────────────────────────────────────────────────────────────────────────────

class TestAssignmentSQLite:
    def test_manual_assign(self, sample_contact):
        """Manual assignment should work."""
        from assignment_manager import manual_assign, get_assignment

        record = manual_assign(
            sample_contact["contact_id"], "agent_1", assigned_by="admin"
        )
        assert record["assigned_to"] == "agent_1"

        fetched = get_assignment(sample_contact["contact_id"])
        assert fetched["assigned_to"] == "agent_1"

    def test_transfer(self, sample_contact):
        """Transfer should update assignment and log it."""
        from assignment_manager import manual_assign, transfer_conversation

        manual_assign(sample_contact["contact_id"], "agent_1", "admin")
        result = transfer_conversation(
            sample_contact["contact_id"], "agent_1", "agent_2", reason="vacation"
        )
        assert result["assigned_to"] == "agent_2"
        assert len(result["transfer_log"]) == 1
        assert result["transfer_log"][0]["reason"] == "vacation"

    def test_workload(self, sample_contact, sample_contact_2):
        """Workload should reflect assignments."""
        from assignment_manager import manual_assign, get_agent_workload

        manual_assign(sample_contact["contact_id"], "agent_1", "admin")
        manual_assign(sample_contact_2["contact_id"], "agent_1", "admin")

        workload = get_agent_workload()
        assert workload.get("agent_1") == 2

    def test_unassigned_queue(self, sample_contact):
        """Unassigned queue should show conversations without agents."""
        from assignment_manager import _create_record, get_unassigned_queue

        _create_record(sample_contact["contact_id"], assigned_to=None, assigned_by="auto")
        queue = get_unassigned_queue()
        assert len(queue) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Segmentation (SQLite saved segments)
# ──────────────────────────────────────────────────────────────────────────────

class TestSegmentationSQLite:
    def test_save_and_list(self, tmp_data_dir):
        """Saved segments should persist."""
        from segmentation import save_segment, list_segments, get_segment

        seg = save_segment("Hot Leads", {
            "conditions": [
                {"field": "lead_score", "operator": "gte", "value": 70},
            ],
            "logic": "AND",
        })
        assert seg["id"].startswith("seg_")

        all_segs = list_segments()
        assert len(all_segs) == 1

        fetched = get_segment(seg["id"])
        assert fetched["name"] == "Hot Leads"

    def test_delete_segment(self, tmp_data_dir):
        """Deleting a segment should remove it."""
        from segmentation import save_segment, delete_segment, list_segments

        seg = save_segment("Temp", {"conditions": [], "logic": "AND"})
        assert delete_segment(seg["id"]) is True
        assert len(list_segments()) == 0

    def test_evaluate_segment(self, sample_contact, sample_contact_2):
        """Segment evaluation should filter contacts correctly."""
        from segmentation import evaluate_segment
        from contact_manager import update_lead_score

        update_lead_score(sample_contact["contact_id"], 80)

        contacts = [sample_contact, sample_contact_2]
        # Refresh sample_contact to have updated score
        from contact_manager import get_contact
        contacts[0] = get_contact(sample_contact["contact_id"])

        segment = {
            "conditions": [
                {"field": "lead_score", "operator": "gte", "value": 70},
            ],
            "logic": "AND",
        }
        matched = evaluate_segment(contacts, segment)
        assert len(matched) == 1
        assert matched[0]["contact_id"] == sample_contact["contact_id"]


# ──────────────────────────────────────────────────────────────────────────────
# Webhook Dispatcher (SQLite)
# ──────────────────────────────────────────────────────────────────────────────

class TestWebhookSQLite:
    def test_register_and_list(self, tmp_data_dir):
        """Webhook registration should persist."""
        from webhook_dispatcher import register_webhook, list_webhooks

        hook = register_webhook(
            url="https://example.com/hook",
            events=["contact.created"],
            secret="my_secret",
            name="Test Hook",
        )
        assert hook["id"].startswith("wh_")

        hooks = list_webhooks()
        assert len(hooks) == 1
        assert hooks[0]["url"] == "https://example.com/hook"

    def test_delete_webhook(self, tmp_data_dir):
        """Deleting a webhook should remove it."""
        from webhook_dispatcher import register_webhook, delete_webhook, list_webhooks

        hook = register_webhook(url="https://example.com/hook")
        assert delete_webhook(hook["id"]) is True
        assert len(list_webhooks()) == 0

    def test_invalid_url_rejected(self, tmp_data_dir):
        """Non-HTTP URLs should be rejected."""
        from webhook_dispatcher import register_webhook
        with pytest.raises(ValueError, match="http"):
            register_webhook(url="ftp://invalid")


# ──────────────────────────────────────────────────────────────────────────────
# Audit Log (SQLite)
# ──────────────────────────────────────────────────────────────────────────────

class TestAuditSQLite:
    def test_log_and_retrieve(self, tmp_data_dir):
        """Audit entries should persist and be retrievable."""
        from audit import log_audit, get_audit_log

        log_audit("contact.created", "contact", "c_001", actor_id="user_1",
                  details={"source": "import"})
        log_audit("campaign.sent", "campaign", "cmp_001", actor_id="user_1")

        entries = get_audit_log(days=1)
        assert len(entries) == 2

    def test_filter_by_action(self, tmp_data_dir):
        """Action prefix filtering should work."""
        from audit import log_audit, get_audit_log

        log_audit("contact.created", "contact")
        log_audit("contact.updated", "contact")
        log_audit("campaign.sent", "campaign")

        contact_entries = get_audit_log(days=1, action="contact")
        assert len(contact_entries) == 2

    def test_audit_stats(self, tmp_data_dir):
        """Stats should aggregate correctly."""
        from audit import log_audit, get_audit_stats

        for _ in range(3):
            log_audit("contact.created", "contact")
        log_audit("campaign.sent", "campaign")

        stats = get_audit_stats(days=1)
        assert stats["total_entries"] == 4
        assert stats["by_action"]["contact.created"] == 3


# ──────────────────────────────────────────────────────────────────────────────
# Concurrent access
# ──────────────────────────────────────────────────────────────────────────────

class TestConcurrentAccess:
    def test_concurrent_contact_creation(self, tmp_data_dir):
        """Multiple threads creating contacts simultaneously should not corrupt data."""
        from database import init_db, DB_PATH
        import contact_manager

        errors = []
        results = []

        def create_one(idx):
            try:
                # Each thread needs its own connection
                import database
                database._local.connection = None
                c = contact_manager.create_contact(
                    name=f"Thread User {idx}",
                    phone=f"+91987654{idx:04d}",
                )
                results.append(c)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=create_one, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent creation: {errors}"
        assert len(results) == 10

        all_contacts = contact_manager.list_contacts()
        assert len(all_contacts) == 10
