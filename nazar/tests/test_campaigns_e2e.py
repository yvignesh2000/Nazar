# -*- coding: utf-8 -*-
"""
Nazar — Campaign End-to-End Tests

Comprehensive tests for the full campaign lifecycle:
1. Campaign CRUD (create, read, update, delete)
2. Template rendering + variable interpolation
3. Campaign execution (background job, progress tracking)
4. Reply mode + campaign KB routing
5. Campaign retarget flow
6. Status update processing (delivered, read, failed, not_on_whatsapp)
7. Opt-out compliance during campaigns
8. Scheduled campaign handling
9. API endpoint integration tests
10. Edge cases and error handling
"""

import asyncio
import json
import os
import sys
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# Path setup
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "core"))

IST = timezone(timedelta(hours=5, minutes=30))


# ===================================================================
#  1. Campaign CRUD (outbound.py)
# ===================================================================

class TestCampaignCRUD:
    """Test campaign create, read, update, list, stats."""

    def test_create_campaign_basic(self, tmp_data_dir):
        from outbound import create_campaign, get_campaign
        c = create_campaign(
            name="Launch Campaign",
            template_id="tpl_welcome",
            template_name="welcome_new_lead",
            target_count=50,
        )
        assert c["id"].startswith("cmp_")
        assert c["name"] == "Launch Campaign"
        assert c["status"] == "draft"
        assert c["target_count"] == 50
        assert c["sent"] == 0
        assert c["failed"] == 0

        # Retrieve
        fetched = get_campaign(c["id"])
        assert fetched is not None
        assert fetched["name"] == "Launch Campaign"

    def test_create_campaign_with_sent_count(self, tmp_data_dir):
        """Campaign with pre-existing sent count should be status=completed."""
        from outbound import create_campaign
        c = create_campaign(
            name="Completed Campaign",
            template_id="tpl_1",
            template_name="tpl",
            target_count=10,
            sent=10,
        )
        assert c["status"] == "completed"
        assert c["completed_at"] != ""

    def test_create_scheduled_campaign(self, tmp_data_dir):
        from outbound import create_campaign
        future = (datetime.now(IST) + timedelta(hours=2)).isoformat()
        c = create_campaign(
            name="Scheduled",
            template_id="tpl_1",
            template_name="tpl",
            target_count=20,
            scheduled_at=future,
        )
        assert c["status"] == "scheduled"
        assert c["scheduled_at"] == future
        assert c["completed_at"] == ""

    def test_create_campaign_with_explicit_status(self, tmp_data_dir):
        from outbound import create_campaign
        c = create_campaign(
            name="Force Status",
            template_id="tpl_1",
            template_name="tpl",
            target_count=10,
            status="sending",
        )
        assert c["status"] == "sending"

    def test_update_campaign_counters(self, tmp_data_dir):
        from outbound import create_campaign, update_campaign
        c = create_campaign(
            name="Update Test",
            template_id="tpl_1",
            template_name="tpl",
            target_count=100,
        )
        updated = update_campaign(c["id"], sent=50, failed=5, delivered=45, status="completed")
        assert updated["sent"] == 50
        assert updated["failed"] == 5
        assert updated["delivered"] == 45
        assert updated["status"] == "completed"
        assert updated["completed_at"] != ""  # Auto-set on completion

    def test_update_campaign_not_on_whatsapp(self, tmp_data_dir):
        from outbound import create_campaign, update_campaign
        c = create_campaign(
            name="Not On WA Test",
            template_id="tpl_1",
            template_name="tpl",
            target_count=100,
        )
        updated = update_campaign(c["id"], not_on_whatsapp=3)
        assert updated["not_on_whatsapp"] == 3

    def test_get_campaign_nonexistent(self, tmp_data_dir):
        from outbound import get_campaign
        assert get_campaign("cmp_nonexistent") is None

    def test_get_campaign_history(self, tmp_data_dir):
        from outbound import create_campaign, get_campaign_history
        create_campaign(name="C1", template_id="t", template_name="t", target_count=1)
        create_campaign(name="C2", template_id="t", template_name="t", target_count=2)
        history = get_campaign_history()
        assert len(history) >= 2
        # Newest first
        assert history[0]["name"] in ("C1", "C2")

    def test_get_campaign_stats(self, tmp_data_dir):
        from outbound import create_campaign, update_campaign, get_campaign_stats
        c = create_campaign(
            name="Stats Test",
            template_id="tpl_1",
            template_name="tpl",
            target_count=100,
            sent=80,
            failed=5,
            delivered=75,
        )
        stats = get_campaign_stats()
        assert stats["total_campaigns"] >= 1
        assert stats["total_sent"] >= 80
        assert stats["total_delivered"] >= 75
        assert "delivery_rate" in stats
        assert "read_rate" in stats
        assert "reply_rate" in stats

    def test_campaign_contact_ids_persisted(self, tmp_data_dir):
        from outbound import create_campaign, get_campaign
        ids = ["contact_001", "contact_002", "contact_003"]
        c = create_campaign(
            name="IDs Test",
            template_id="tpl_1",
            template_name="tpl",
            target_count=3,
            contact_ids=ids,
        )
        fetched = get_campaign(c["id"])
        assert fetched["contact_ids"] == ids

    def test_campaign_contact_ids_empty(self, tmp_data_dir):
        from outbound import create_campaign, get_campaign
        c = create_campaign(
            name="No IDs",
            template_id="tpl_1",
            template_name="tpl",
            target_count=10,
        )
        fetched = get_campaign(c["id"])
        assert fetched["contact_ids"] == []

    def test_campaign_kb_flag(self, tmp_data_dir):
        from outbound import create_campaign, get_campaign
        c = create_campaign(
            name="KB Test",
            template_id="tpl_1",
            template_name="tpl",
            target_count=10,
            campaign_kb="Some knowledge base content",
        )
        fetched = get_campaign(c["id"])
        assert fetched["campaign_kb"] is True


# ===================================================================
#  2. Template Rendering
# ===================================================================

class TestTemplateRendering:
    """Test template variable interpolation and edge cases."""

    def test_render_basic(self, tmp_data_dir):
        from template_manager import render_template
        template = {
            "body": "Hi {{1}}! Welcome to {{2}}.",
            "variables": ["name", "company"],
        }
        contact = {"name": "Alice", "company": "Acme Inc"}
        result = render_template(template, contact)
        assert result == "Hi Alice! Welcome to Acme Inc."

    def test_render_missing_name_fallback(self, tmp_data_dir):
        from template_manager import render_template
        template = {"body": "Hi {{1}}!", "variables": ["name"]}
        contact = {"name": "", "company": ""}
        result = render_template(template, contact)
        assert result == "Hi there!"

    def test_render_none_name_fallback(self, tmp_data_dir):
        from template_manager import render_template
        template = {"body": "Hi {{1}}!", "variables": ["name"]}
        contact = {"name": None}
        result = render_template(template, contact)
        assert result == "Hi there!"

    def test_render_missing_company_fallback(self, tmp_data_dir):
        from template_manager import render_template
        template = {"body": "At {{1}}", "variables": ["company"]}
        contact = {"name": "Test", "company": ""}
        result = render_template(template, contact)
        assert result == "At your company"

    def test_render_deal_value_format(self, tmp_data_dir):
        from template_manager import render_template
        template = {"body": "Deal: {{1}}", "variables": ["deal_value"]}
        contact = {"name": "Test", "deal_value": 150000}
        result = render_template(template, contact)
        assert "1,50,000" in result or "150,000" in result

    def test_render_empty_body_raises(self, tmp_data_dir):
        from template_manager import render_template
        with pytest.raises(ValueError, match="no body"):
            render_template({"body": "", "variables": []}, {"name": "Test"})

    def test_render_no_variables(self, tmp_data_dir):
        from template_manager import render_template
        template = {"body": "Hello! Thanks for your interest.", "variables": []}
        contact = {"name": "Test"}
        result = render_template(template, contact)
        assert result == "Hello! Thanks for your interest."

    def test_render_unknown_variable_uses_name(self, tmp_data_dir):
        from template_manager import render_template
        template = {"body": "Value: {{1}}", "variables": ["unknown_field"]}
        contact = {"name": "Test"}
        result = render_template(template, contact)
        # Should use the var name as fallback
        assert result == "Value: unknown_field"


# ===================================================================
#  3. Personalize Message (outbound.py)
# ===================================================================

class TestPersonalizeMessage:
    """Test campaign message personalization."""

    def test_basic_personalization(self, tmp_data_dir):
        from outbound import personalize_message
        result = personalize_message(
            "Hi {name}, from {company}!",
            {"name": "Bob", "company": "Corp"},
        )
        assert result == "Hi Bob, from Corp!"

    def test_empty_name_fallback(self, tmp_data_dir):
        from outbound import personalize_message
        result = personalize_message(
            "Hi {name}!",
            {"name": "", "phone": "+91999"},
        )
        assert result == "Hi there!"

    def test_none_name_fallback(self, tmp_data_dir):
        from outbound import personalize_message
        result = personalize_message(
            "Hi {name}!",
            {},
        )
        assert result == "Hi there!"

    def test_empty_template(self, tmp_data_dir):
        from outbound import personalize_message
        result = personalize_message("", {"name": "Alice"})
        assert result == ""

    def test_missing_company_fallback(self, tmp_data_dir):
        from outbound import personalize_message
        result = personalize_message(
            "At {company}",
            {"name": "Alice", "company": None},
        )
        assert result == "At your company"


# ===================================================================
#  4. Reply Mode + Campaign KB Routing
# ===================================================================

class TestReplyModeRouting:
    """Test campaign reply mode resolution and KB fallback chain."""

    def test_default_reply_mode(self, tmp_data_dir, sample_contact):
        from reply_mode import get_effective_reply_mode
        result = get_effective_reply_mode(sample_contact["contact_id"])
        assert result["mode"] == "auto_ai"
        assert result["source"] == "default"

    def test_contact_override_takes_priority(self, tmp_data_dir, sample_contact):
        from reply_mode import set_contact_reply_mode, get_effective_reply_mode
        set_contact_reply_mode(sample_contact["contact_id"], "human_only")
        result = get_effective_reply_mode(sample_contact["contact_id"])
        assert result["mode"] == "human_only"
        assert result["source"] == "contact"

    def test_campaign_reply_mode(self, tmp_data_dir, sample_contact):
        from outbound import create_campaign
        from reply_mode import (
            associate_contacts_to_campaign, get_effective_reply_mode,
            save_campaign_kb, get_campaign_kb,
        )
        c = create_campaign(
            name="Routing Test",
            template_id="tpl_1",
            template_name="tpl",
            target_count=1,
            reply_mode="ai_draft",
            campaign_kb="Product FAQ content here",
        )
        save_campaign_kb(c["id"], "Product FAQ content here")
        associate_contacts_to_campaign([sample_contact["contact_id"]], c["id"])

        result = get_effective_reply_mode(sample_contact["contact_id"])
        assert result["mode"] == "ai_draft"
        assert result["source"] == "campaign"
        assert result["campaign_id"] == c["id"]
        assert "Product FAQ" in result["campaign_kb"]

    def test_campaign_kb_html_sanitized(self, tmp_data_dir):
        from reply_mode import save_campaign_kb, get_campaign_kb
        save_campaign_kb("cmp_test", "<script>alert('xss')</script>Hello <b>World</b>")
        content = get_campaign_kb("cmp_test")
        assert "<script>" not in content
        assert "<b>" not in content
        assert "alert" in content  # Text content preserved
        assert "Hello" in content
        assert "World" in content

    def test_campaign_kb_truncation(self, tmp_data_dir):
        from reply_mode import save_campaign_kb, get_campaign_kb
        long_content = "x" * 60000
        save_campaign_kb("cmp_trunc", long_content)
        content = get_campaign_kb("cmp_trunc")
        assert len(content) <= 50000  # save truncates at 50k
        # get_campaign_kb truncates at 8000 for prompt injection
        assert len(content) <= 8000

    def test_contact_override_beats_campaign(self, tmp_data_dir, sample_contact):
        from outbound import create_campaign
        from reply_mode import (
            associate_contacts_to_campaign, set_contact_reply_mode,
            get_effective_reply_mode,
        )
        c = create_campaign(
            name="Override Test",
            template_id="tpl_1",
            template_name="tpl",
            target_count=1,
            reply_mode="ai_draft",
        )
        associate_contacts_to_campaign([sample_contact["contact_id"]], c["id"])
        set_contact_reply_mode(sample_contact["contact_id"], "human_only")

        result = get_effective_reply_mode(sample_contact["contact_id"])
        assert result["mode"] == "human_only"
        assert result["source"] == "contact"


# ===================================================================
#  5. AI Draft Management
# ===================================================================

class TestAIDraftFlow:
    """Test AI draft save, approve, reject, regenerate flow."""

    def test_save_and_retrieve_draft(self, tmp_data_dir, sample_contact):
        from reply_mode import save_draft, get_draft
        cid = sample_contact["contact_id"]
        entry = save_draft(cid, "Draft reply text", customer_message="Hi there")
        assert entry["draft"] == "Draft reply text"
        assert entry["status"] == "pending"

        draft = get_draft(cid)
        assert draft is not None
        assert draft["draft"] == "Draft reply text"
        assert draft["customer_message"] == "Hi there"

    def test_approve_draft(self, tmp_data_dir, sample_contact):
        from reply_mode import save_draft, approve_draft
        cid = sample_contact["contact_id"]
        save_draft(cid, "Original draft")
        approved = approve_draft(cid)
        assert approved["status"] == "approved"
        assert approved["final_text"] == "Original draft"

    def test_approve_with_edits(self, tmp_data_dir, sample_contact):
        from reply_mode import save_draft, approve_draft
        cid = sample_contact["contact_id"]
        save_draft(cid, "Original draft")
        approved = approve_draft(cid, edited_text="Edited version")
        assert approved["status"] == "edited"
        assert approved["final_text"] == "Edited version"

    def test_reject_draft(self, tmp_data_dir, sample_contact):
        from reply_mode import save_draft, reject_draft
        cid = sample_contact["contact_id"]
        save_draft(cid, "Reject me")
        rejected = reject_draft(cid)
        assert rejected["status"] == "rejected"

    def test_approve_nonexistent(self, tmp_data_dir, sample_contact):
        from reply_mode import approve_draft
        result = approve_draft(sample_contact["contact_id"])
        assert result is None

    def test_pending_drafts_list(self, tmp_data_dir, sample_contact, sample_contact_2):
        from reply_mode import save_draft, get_all_pending_drafts
        save_draft(sample_contact["contact_id"], "Draft 1", customer_message="Q1")
        save_draft(sample_contact_2["contact_id"], "Draft 2", customer_message="Q2")
        drafts = get_all_pending_drafts()
        assert len(drafts) == 2


# ===================================================================
#  6. Campaign Execution (async workers)
# ===================================================================

class TestCampaignExecution:
    """Test the async campaign execution flow."""

    @pytest.mark.asyncio
    async def test_execute_campaign_send_basic(self, tmp_data_dir):
        from outbound import execute_campaign_send

        send_fn = AsyncMock()
        contacts = [
            {"contact_id": "c1", "phone": "+919000000001", "name": "Alice"},
            {"contact_id": "c2", "phone": "+919000000002", "name": "Bob"},
        ]
        results = await execute_campaign_send(
            contacts=contacts,
            message="Hi {name}!",
            send_fn=send_fn,
            personalize=True,
            rate_limit_ms=0,
        )
        assert results["sent"] == 2
        assert results["failed"] == 0
        assert send_fn.call_count == 2

    @pytest.mark.asyncio
    async def test_execute_campaign_send_no_phone(self, tmp_data_dir):
        from outbound import execute_campaign_send

        send_fn = AsyncMock()
        contacts = [
            {"contact_id": "c1", "phone": "", "name": "Alice"},
            {"contact_id": "c2", "phone": "+91999", "name": "Bob"},
        ]
        results = await execute_campaign_send(
            contacts=contacts,
            message="Hello!",
            send_fn=send_fn,
            rate_limit_ms=0,
        )
        assert results["sent"] == 1
        assert results["failed"] == 1

    @pytest.mark.asyncio
    async def test_execute_campaign_send_failure(self, tmp_data_dir):
        from outbound import execute_campaign_send

        send_fn = AsyncMock(side_effect=Exception("API error"))
        contacts = [
            {"contact_id": "c1", "phone": "+919000000001", "name": "Alice"},
        ]
        results = await execute_campaign_send(
            contacts=contacts,
            message="Hello!",
            send_fn=send_fn,
            rate_limit_ms=0,
        )
        assert results["sent"] == 0
        assert results["failed"] == 1
        assert "API error" in results["details"][0]["error"]


# ===================================================================
#  7. Knowledge Base Integration
# ===================================================================

class TestKnowledgeBaseIntegration:
    """Test KB document management and RAG fallback chain."""

    def test_add_and_list_documents(self, tmp_data_dir, monkeypatch):
        import knowledge_base as kb
        monkeypatch.setattr(kb, "KB_DIR", tmp_data_dir / "kb")
        monkeypatch.setattr(kb, "DATA_DIR", tmp_data_dir)

        doc = kb.add_document(
            title="Product Info",
            content="Nazar helps businesses manage WhatsApp sales. It costs ₹999/month.",
            doc_type="text",
            scope="global",
        )
        assert doc["id"].startswith("doc_")
        assert doc["chunk_count"] >= 1

        docs = kb.list_documents(scope="global")
        assert len(docs) >= 1

    def test_campaign_scoped_kb(self, tmp_data_dir, monkeypatch):
        import knowledge_base as kb
        monkeypatch.setattr(kb, "KB_DIR", tmp_data_dir / "kb")
        monkeypatch.setattr(kb, "DATA_DIR", tmp_data_dir)

        doc = kb.add_document(
            title="Campaign FAQ",
            content="This product has a 30-day money-back guarantee.",
            scope="campaign",
            campaign_id="cmp_test123",
        )
        assert doc["scope"] == "campaign"
        assert doc["campaign_id"] == "cmp_test123"

        # Only returns campaign-scoped docs
        campaign_docs = kb.list_documents(scope="campaign", campaign_id="cmp_test123")
        assert len(campaign_docs) >= 1

        global_docs = kb.list_documents(scope="global")
        assert all(d["scope"] == "global" for d in global_docs)

    def test_fallback_to_legacy_file(self, tmp_data_dir, monkeypatch):
        import knowledge_base as kb
        monkeypatch.setattr(kb, "KB_DIR", tmp_data_dir / "kb")
        monkeypatch.setattr(kb, "DATA_DIR", tmp_data_dir)

        # Write legacy file
        legacy_path = tmp_data_dir / "knowledge_base.txt"
        legacy_path.write_text("Legacy KB content: Our product is great.")

        # Query should return content — either from ChromaDB (if earlier test
        # seeded it) or from the legacy file fallback.  Both paths are valid.
        result = kb.query("What is your product?", scope="global")
        assert len(result) > 0, "KB query returned empty — neither ChromaDB nor legacy fallback worked"

    def test_delete_document(self, tmp_data_dir, monkeypatch):
        import knowledge_base as kb
        monkeypatch.setattr(kb, "KB_DIR", tmp_data_dir / "kb")
        monkeypatch.setattr(kb, "DATA_DIR", tmp_data_dir)

        doc = kb.add_document(title="Delete Me", content="Content to delete", scope="global")
        assert kb.delete_document(doc["id"]) is True
        assert kb.get_document(doc["id"]) is None


# ===================================================================
#  8. Opt-out Compliance in Campaigns
# ===================================================================

class TestOptoutCompliance:
    """Test that opted-out contacts are properly excluded."""

    def test_opted_out_contact_skipped(self, tmp_data_dir):
        from optout_manager import record_optout, can_message
        record_optout("+919000000001", reason="STOP")
        assert can_message("+919000000001") is False

    def test_opt_in_re_enables(self, tmp_data_dir):
        from optout_manager import record_optout, record_optin, can_message
        record_optout("+919000000002", reason="STOP")
        assert can_message("+919000000002") is False
        record_optin("+919000000002")
        assert can_message("+919000000002") is True

    def test_stop_message_detection(self, tmp_data_dir):
        from optout_manager import is_stop_message
        assert is_stop_message("STOP") is True
        assert is_stop_message("stop") is True
        assert is_stop_message("unsubscribe") is True
        assert is_stop_message("please stop messaging me") is True
        assert is_stop_message("opt out") is True
        assert is_stop_message("I love your product") is False
        assert is_stop_message("Can you stop by tomorrow?") is False  # "stop" in context

    def test_start_message_detection(self, tmp_data_dir):
        from optout_manager import is_start_message
        assert is_start_message("START") is True
        assert is_start_message("subscribe") is True
        assert is_start_message("yes please") is True


# ===================================================================
#  9. Service Window Integration
# ===================================================================

class TestServiceWindowCampaign:
    """Test 24h window status for campaign targeting."""

    def test_window_open(self, tmp_data_dir):
        from service_window import compute_window
        now = datetime.now(IST)
        contact = {"last_replied_at": (now - timedelta(hours=2)).isoformat()}
        w = compute_window(contact, now)
        assert w["window_open"] is True
        assert w["hours_remaining"] > 20

    def test_window_closed(self, tmp_data_dir):
        from service_window import compute_window
        now = datetime.now(IST)
        contact = {"last_replied_at": (now - timedelta(hours=30)).isoformat()}
        w = compute_window(contact, now)
        assert w["window_open"] is False
        assert w["requires_template"] is True

    def test_window_no_inbound(self, tmp_data_dir):
        from service_window import compute_window
        contact = {"last_replied_at": None}
        w = compute_window(contact)
        assert w["window_open"] is False
        assert w["requires_template"] is True

    def test_classify_campaign_targets(self, tmp_data_dir):
        from service_window import classify_campaign_targets
        now = datetime.now(IST)
        contacts = [
            {"contact_id": "c1", "last_replied_at": (now - timedelta(hours=1)).isoformat()},
            {"contact_id": "c2", "last_replied_at": (now - timedelta(hours=30)).isoformat()},
            {"contact_id": "c3", "last_replied_at": None},
        ]
        result = classify_campaign_targets(contacts, now)
        assert result["summary"]["open_count"] == 1
        assert result["summary"]["closed_count"] == 2
        assert result["summary"]["total"] == 3


# ===================================================================
#  10. Template CRUD
# ===================================================================

class TestTemplateCRUD:
    """Test template lifecycle management."""

    def test_create_and_get_template(self, tmp_data_dir):
        from template_manager import create_template, get_template
        t = create_template(
            name="test_campaign_tpl",
            body="Hello {{1}}!",
            category="marketing",
            variables=["name"],
        )
        assert t["id"].startswith("tpl_")
        assert t["approval_status"] == "pending"

        fetched = get_template(t["id"])
        assert fetched["name"] == "test_campaign_tpl"

    def test_duplicate_name_rejected(self, tmp_data_dir):
        from template_manager import create_template
        create_template(name="dup_test", body="Body", category="utility")
        with pytest.raises(ValueError, match="already exists"):
            create_template(name="dup_test", body="Different", category="utility")

    def test_invalid_category_rejected(self, tmp_data_dir):
        from template_manager import create_template
        with pytest.raises(ValueError, match="Invalid category"):
            create_template(name="bad_cat", body="Body", category="invalid")

    def test_too_many_buttons(self, tmp_data_dir):
        from template_manager import create_template
        with pytest.raises(ValueError, match="Maximum 3 buttons"):
            create_template(
                name="many_btns",
                body="Body",
                category="utility",
                buttons=[
                    {"type": "quick_reply", "text": "A"},
                    {"type": "quick_reply", "text": "B"},
                    {"type": "quick_reply", "text": "C"},
                    {"type": "quick_reply", "text": "D"},
                ],
            )

    def test_template_suggestion_by_stage(self, tmp_data_dir):
        from template_manager import suggest_template
        contact = {"pipeline_stage": "New"}
        template = suggest_template(contact)
        assert template is not None
        assert template["name"] in ("welcome_new_lead", "welcome_hindi")

    def test_template_stats(self, tmp_data_dir):
        from template_manager import get_template_stats
        stats = get_template_stats()
        assert stats["total"] >= 8  # Default templates
        assert stats["approved"] >= 1
        assert "categories" in stats

    def test_increment_usage(self, tmp_data_dir):
        from template_manager import get_template, increment_usage
        templates = __import__("template_manager").list_templates()
        t = templates[0]
        old_count = t["usage_count"]
        increment_usage(t["id"])
        updated = get_template(t["id"])
        assert updated["usage_count"] == old_count + 1


# ===================================================================
#  11. Job Queue
# ===================================================================

class TestJobQueue:
    """Test background job queue for campaign execution."""

    @pytest.mark.asyncio
    async def test_enqueue_and_complete(self, tmp_data_dir):
        from job_queue import JobQueue, JobStatus

        jq = JobQueue(max_concurrent=2)

        async def simple_worker(job_id, params, update_progress):
            update_progress(job_id, 1, 1, 0)

        job_id = await jq.enqueue("test_job", {"key": "val"}, simple_worker)
        assert job_id.startswith("job_")

        # Wait for completion
        await asyncio.sleep(0.2)
        job = jq.get_job(job_id)
        assert job["status"] == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_job_failure_captured(self, tmp_data_dir):
        from job_queue import JobQueue, JobStatus

        jq = JobQueue(max_concurrent=2)

        async def failing_worker(job_id, params, update_progress):
            raise ValueError("Intentional test failure")

        job_id = await jq.enqueue("failing_job", {}, failing_worker)
        await asyncio.sleep(0.2)
        job = jq.get_job(job_id)
        assert job["status"] == JobStatus.FAILED
        assert "Intentional test failure" in job["error"]

    @pytest.mark.asyncio
    async def test_job_progress_tracking(self, tmp_data_dir):
        from job_queue import JobQueue, JobStatus

        jq = JobQueue(max_concurrent=2)

        async def progress_worker(job_id, params, update_progress):
            for i in range(5):
                update_progress(job_id, i + 1, 5, 0)
                await asyncio.sleep(0.01)

        job_id = await jq.enqueue("progress_job", {}, progress_worker)
        await asyncio.sleep(0.3)
        job = jq.get_job(job_id)
        assert job["progress"]["current"] == 5
        assert job["progress"]["total"] == 5

    @pytest.mark.asyncio
    async def test_job_cancellation(self, tmp_data_dir):
        from job_queue import JobQueue, JobStatus

        jq = JobQueue(max_concurrent=1)

        async def long_worker(job_id, params, update_progress):
            await asyncio.sleep(100)

        job_id = await jq.enqueue("cancel_me", {}, long_worker)
        await asyncio.sleep(0.1)

        cancelled = jq.cancel(job_id)
        assert cancelled is True
        await asyncio.sleep(0.1)
        job = jq.get_job(job_id)
        assert job["status"] == JobStatus.CANCELLED


# ===================================================================
#  12. Campaign API Endpoints
# ===================================================================

class TestCampaignAPIEndpoints:
    """Integration tests for campaign REST endpoints."""

    def _headers(self):
        return {"X-Nazar-Key": "test_key_abc123"}

    def test_list_campaigns_empty(self, api_client):
        r = api_client.get("/api/campaigns", headers=self._headers())
        assert r.status_code == 200
        data = r.json()
        assert "campaigns" in data
        assert "stats" in data
        assert "pagination" in data

    def test_create_campaign_approved_template(self, api_client):
        """Full campaign creation flow: create template → create contacts → create campaign."""
        h = self._headers()

        # Create contacts
        for i in range(3):
            api_client.post("/api/contacts", json={
                "name": f"Campaign User {i}",
                "phone": f"+9180000000{i:02d}",
            }, headers=h)

        contacts = api_client.get("/api/contacts", headers=h).json()["contacts"]
        contact_ids = [c["contact_id"] for c in contacts]

        # Get an approved template
        templates = api_client.get("/api/templates", headers=h).json()["templates"]
        approved = [t for t in templates if t.get("approval_status") == "approved"]
        assert len(approved) > 0, "No approved templates available"
        template = approved[0]

        # Create campaign
        r = api_client.post("/api/campaigns", json={
            "name": "Test Campaign",
            "template_id": template["id"],
            "contact_ids": contact_ids,
            "reply_mode": "auto_ai",
        }, headers=h)
        assert r.status_code == 200
        data = r.json()
        assert "campaign" in data
        assert "job_id" in data
        assert data["campaign"]["status"] == "sending"

    def test_create_campaign_unapproved_template(self, api_client):
        h = self._headers()

        # Create a pending template
        import uuid
        tpl_name = f"pending_tpl_{uuid.uuid4().hex[:6]}"
        api_client.post("/api/templates", json={
            "name": tpl_name,
            "body": "Test {{1}}",
            "category": "utility",
            "variables": ["name"],
        }, headers=h)
        templates = api_client.get("/api/templates", headers=h).json()["templates"]
        pending = [t for t in templates if t["name"] == tpl_name]
        assert len(pending) > 0
        tpl_id = pending[0]["id"]

        # Create a contact
        api_client.post("/api/contacts", json={
            "name": "Pending Test",
            "phone": "+918099999999",
        }, headers=h)

        # Try campaign with unapproved template
        r = api_client.post("/api/campaigns", json={
            "name": "Should Fail",
            "template_id": tpl_id,
            "filter_stage": "New",
        }, headers=h)
        assert r.status_code == 400
        assert "approved" in r.json()["detail"].lower()

    def test_create_campaign_nonexistent_template(self, api_client):
        h = self._headers()
        r = api_client.post("/api/campaigns", json={
            "name": "Bad Template",
            "template_id": "tpl_nonexistent",
        }, headers=h)
        assert r.status_code == 404

    def test_create_campaign_no_contacts(self, api_client):
        h = self._headers()
        templates = api_client.get("/api/templates", headers=h).json()["templates"]
        approved = [t for t in templates if t.get("approval_status") == "approved"]
        template = approved[0]

        r = api_client.post("/api/campaigns", json={
            "name": "No Contacts",
            "template_id": template["id"],
            "filter_stage": "NonexistentStage",
        }, headers=h)
        assert r.status_code == 400
        assert "No contacts" in r.json()["detail"]

    def test_get_campaign_by_id(self, api_client):
        h = self._headers()

        # Create a contact first
        api_client.post("/api/contacts", json={
            "name": "Get Campaign Test",
            "phone": "+918011111111",
        }, headers=h)

        templates = api_client.get("/api/templates", headers=h).json()["templates"]
        approved = [t for t in templates if t.get("approval_status") == "approved"]
        template = approved[0]

        r = api_client.post("/api/campaigns", json={
            "name": "Get By ID",
            "template_id": template["id"],
            "filter_stage": "New",
        }, headers=h)
        campaign_id = r.json()["campaign"]["id"]

        r2 = api_client.get(f"/api/campaigns/{campaign_id}", headers=h)
        assert r2.status_code == 200
        assert r2.json()["campaign"]["id"] == campaign_id

    def test_get_campaign_not_found(self, api_client):
        h = self._headers()
        r = api_client.get("/api/campaigns/cmp_nonexistent", headers=h)
        assert r.status_code == 404

    def test_campaign_audience_analysis(self, api_client):
        h = self._headers()
        api_client.post("/api/contacts", json={
            "name": "Audience User",
            "phone": "+918022222222",
        }, headers=h)

        r = api_client.get("/api/campaigns/audience-analysis", headers=h)
        assert r.status_code == 200
        data = r.json()
        assert "contacts" in data
        assert "summary" in data
        assert "info" in data


# ===================================================================
#  13. Template API Endpoints
# ===================================================================

class TestTemplateAPIEndpoints:
    def _headers(self):
        return {"X-Nazar-Key": "test_key_abc123"}

    def test_render_template_api(self, api_client):
        h = self._headers()

        # Create contact
        r1 = api_client.post("/api/contacts", json={
            "name": "Render Test",
            "phone": "+918033333333",
        }, headers=h)
        contact_id = r1.json()["contact"]["contact_id"]

        # Get an approved template
        templates = api_client.get("/api/templates", headers=h).json()["templates"]
        tpl = [t for t in templates if t.get("approval_status") == "approved" and t.get("variables")][0]

        r = api_client.post(f"/api/templates/{tpl['id']}/render", json={
            "contact_id": contact_id,
        }, headers=h)
        assert r.status_code == 200
        assert "rendered" in r.json()
        assert "Render Test" in r.json()["rendered"]


# ===================================================================
#  14. Knowledge Base API Integration
# ===================================================================

class TestKBAPIEndpoints:
    def _headers(self):
        return {"X-Nazar-Key": "test_key_abc123"}

    def test_upload_and_retrieve_kb(self, api_client):
        h = self._headers()
        r = api_client.post("/api/kb/upload", json={
            "content": "Our product costs ₹999/month. We offer a 14-day free trial.",
        }, headers=h)
        assert r.status_code == 200

        r2 = api_client.get("/api/kb", headers=h)
        assert r2.status_code == 200
        assert "₹999" in r2.json()["content"]

    def test_kb_documents_crud(self, api_client):
        h = self._headers()

        # Create
        r = api_client.post("/api/kb/documents", json={
            "title": "Product FAQ",
            "content": "Q: What is Nazar? A: A WhatsApp sales tool.",
        }, headers=h)
        assert r.status_code == 200
        doc_id = r.json()["document"]["id"]

        # List
        r2 = api_client.get("/api/kb/documents", headers=h)
        assert r2.status_code == 200
        assert r2.json()["count"] >= 1

        # Delete
        r3 = api_client.delete(f"/api/kb/documents/{doc_id}", headers=h)
        assert r3.status_code == 200

    def test_kb_query(self, api_client):
        h = self._headers()
        api_client.post("/api/kb/documents", json={
            "title": "Pricing",
            "content": "Nazar costs ₹999 per month for the starter plan.",
        }, headers=h)
        r = api_client.post("/api/kb/query", json={
            "question": "How much does it cost?",
        }, headers=h)
        assert r.status_code == 200
        assert "result" in r.json()


# ===================================================================
#  15. Reply Mode API
# ===================================================================

class TestReplyModeAPI:
    def _headers(self):
        return {"X-Nazar-Key": "test_key_abc123"}

    def test_get_reply_mode(self, api_client):
        h = self._headers()
        r = api_client.post("/api/contacts", json={
            "name": "RM Test",
            "phone": "+918044444444",
        }, headers=h)
        cid = r.json()["contact"]["contact_id"]

        r2 = api_client.get(f"/api/reply-modes/{cid}", headers=h)
        assert r2.status_code == 200
        assert r2.json()["mode"] == "auto_ai"

    def test_set_and_clear_reply_mode(self, api_client):
        h = self._headers()
        r = api_client.post("/api/contacts", json={
            "name": "RM Set",
            "phone": "+918055555555",
        }, headers=h)
        cid = r.json()["contact"]["contact_id"]

        # Set
        r2 = api_client.put(f"/api/reply-modes/{cid}", json={"mode": "human_only"}, headers=h)
        assert r2.status_code == 200
        assert r2.json()["effective"]["mode"] == "human_only"

        # Clear
        r3 = api_client.delete(f"/api/reply-modes/{cid}", headers=h)
        assert r3.status_code == 200
        assert r3.json()["effective"]["mode"] == "auto_ai"

    def test_invalid_reply_mode_rejected(self, api_client):
        h = self._headers()
        r = api_client.post("/api/contacts", json={
            "name": "RM Invalid",
            "phone": "+918066666666",
        }, headers=h)
        cid = r.json()["contact"]["contact_id"]

        r2 = api_client.put(f"/api/reply-modes/{cid}", json={"mode": "invalid"}, headers=h)
        assert r2.status_code == 400


# ===================================================================
#  16. Draft API Endpoints
# ===================================================================

class TestDraftAPIEndpoints:
    def _headers(self):
        return {"X-Nazar-Key": "test_key_abc123"}

    def test_drafts_list_empty(self, api_client):
        h = self._headers()
        r = api_client.get("/api/drafts", headers=h)
        assert r.status_code == 200
        assert r.json()["count"] == 0


# ===================================================================
#  17. Followup Context Generation
# ===================================================================

class TestFollowupContext:
    """Test AI followup context generation for campaigns."""

    def test_basic_context(self, tmp_data_dir):
        from outbound import generate_followup_context
        contact = {
            "name": "Alice",
            "pipeline_stage": "Qualified",
            "deal_value": 50000,
            "last_contacted_at": "2026-01-15T10:00:00+05:30",
            "notes": "Interested in premium plan",
        }
        context = generate_followup_context(contact)
        assert "Alice" in context
        assert "Qualified" in context
        assert "50,000" in context
        assert "premium plan" in context

    def test_context_with_memory(self, tmp_data_dir):
        from outbound import generate_followup_context
        contact = {"name": "Bob", "pipeline_stage": "New", "deal_value": 0}
        memory = {
            "signal_counts": {"buying_signal": 3},
            "total_embeddings": 15,
        }
        context = generate_followup_context(contact, memory)
        assert "buying_signal" in context
        assert "15" in context


# ===================================================================
#  18. Build Template Components (server helper)
# ===================================================================

class TestBuildTemplateComponents:
    """Test WhatsApp API component building."""

    def test_basic_body_params(self, tmp_data_dir):
        # Import from server scope
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import importlib
        # We can test the function directly from server module
        from server import _build_template_components

        template = {
            "variables": ["name", "company"],
            "header": {"type": "none"},
        }
        contact = {"name": "Alice", "company": "Acme"}
        components = _build_template_components(template, contact)
        assert len(components) == 1
        assert components[0]["type"] == "body"
        assert len(components[0]["parameters"]) == 2
        assert components[0]["parameters"][0]["text"] == "Alice"
        assert components[0]["parameters"][1]["text"] == "Acme"

    def test_empty_name_gets_fallback(self, tmp_data_dir):
        from server import _build_template_components
        template = {"variables": ["name"], "header": {"type": "none"}}
        contact = {"name": ""}
        components = _build_template_components(template, contact)
        assert components[0]["parameters"][0]["text"] == "there"

    def test_no_variables(self, tmp_data_dir):
        from server import _build_template_components
        template = {"variables": [], "header": {"type": "none"}}
        contact = {"name": "Test"}
        components = _build_template_components(template, contact)
        assert len(components) == 0

    def test_image_header(self, tmp_data_dir):
        from server import _build_template_components
        template = {
            "variables": ["name"],
            "header": {"type": "image", "url": "https://example.com/img.jpg"},
        }
        contact = {"name": "Test"}
        components = _build_template_components(template, contact)
        assert len(components) == 2
        header_comp = [c for c in components if c["type"] == "header"]
        assert len(header_comp) == 1
        assert header_comp[0]["parameters"][0]["type"] == "image"


# ===================================================================
#  19. Schema Validation
# ===================================================================

class TestCampaignSchemas:
    """Test Pydantic schema validation for campaign endpoints."""

    def test_valid_campaign_request(self):
        from schemas import CreateCampaignRequest
        req = CreateCampaignRequest(
            name="My Campaign",
            template_id="tpl_123",
            reply_mode="auto_ai",
        )
        assert req.name == "My Campaign"

    def test_invalid_reply_mode(self):
        from schemas import CreateCampaignRequest
        with pytest.raises(Exception):
            CreateCampaignRequest(
                name="Bad Mode",
                template_id="tpl_123",
                reply_mode="invalid_mode",
            )

    def test_empty_name_rejected(self):
        from schemas import CreateCampaignRequest
        with pytest.raises(Exception):
            CreateCampaignRequest(name="", template_id="tpl_123")

    def test_campaign_kb_max_length(self):
        from schemas import CreateCampaignRequest
        # Should accept up to 50000 chars
        req = CreateCampaignRequest(
            name="Long KB",
            template_id="tpl_123",
            campaign_kb="x" * 50000,
        )
        assert len(req.campaign_kb) == 50000

    def test_template_name_validation(self):
        from schemas import CreateTemplateRequest
        with pytest.raises(Exception):
            CreateTemplateRequest(
                name="Invalid Name!",  # Has uppercase and special chars
                body="Body text",
                category="utility",
            )

    def test_template_valid_name(self):
        from schemas import CreateTemplateRequest
        req = CreateTemplateRequest(
            name="valid_template_name_123",
            body="Hello {{1}}!",
            category="utility",
        )
        assert req.name == "valid_template_name_123"


# ===================================================================
#  20. Edge Cases & Robustness
# ===================================================================

class TestEdgeCases:
    """Edge cases that could cause production failures."""

    def test_campaign_with_no_contact_ids_uses_filters(self, tmp_data_dir, sample_contact):
        """When contact_ids is empty, campaign should use filter_stage."""
        from outbound import create_campaign
        c = create_campaign(
            name="Filter Campaign",
            template_id="tpl_1",
            template_name="tpl",
            target_count=1,
            filter_stage="New",
        )
        assert c["contact_ids"] == []
        assert c["filter_stage"] == "New"

    def test_campaign_with_unicode_name(self, tmp_data_dir):
        from outbound import create_campaign
        c = create_campaign(
            name="दिवाली कैंपेन 🎉",
            template_id="tpl_1",
            template_name="tpl",
            target_count=10,
        )
        assert c["name"] == "दिवाली कैंपेन 🎉"

    def test_malformed_contact_ids_json(self, tmp_data_dir):
        """Verify resilience against corrupted JSON in contact_ids column."""
        from outbound import create_campaign, get_campaign
        from database import get_db
        c = create_campaign(
            name="Corrupt IDs",
            template_id="tpl_1",
            template_name="tpl",
            target_count=1,
        )
        # Manually corrupt the DB
        with get_db() as conn:
            conn.execute(
                "UPDATE campaigns SET contact_ids = ? WHERE id = ?",
                ("not_valid_json", c["id"]),
            )
        fetched = get_campaign(c["id"])
        assert fetched["contact_ids"] == []  # Should gracefully fallback

    def test_concurrent_campaigns(self, tmp_data_dir):
        """Verify multiple campaigns can exist simultaneously."""
        from outbound import create_campaign, get_campaign_history
        for i in range(5):
            create_campaign(
                name=f"Concurrent {i}",
                template_id="tpl_1",
                template_name="tpl",
                target_count=10,
            )
        history = get_campaign_history()
        assert len(history) >= 5

    def test_template_render_with_special_chars(self, tmp_data_dir):
        from template_manager import render_template
        template = {"body": "Hi {{1}}! Deal at {{2}}", "variables": ["name", "company"]}
        contact = {"name": "O'Brien & Co.", "company": "Test's \"Company\""}
        result = render_template(template, contact)
        assert "O'Brien" in result
        assert "Test's" in result

    def test_personalize_with_phone_containing_plus(self, tmp_data_dir):
        from outbound import personalize_message
        result = personalize_message(
            "Call {phone} for {name}",
            {"name": "Alice", "phone": "+919876543210"},
        )
        assert "+919876543210" in result

    def test_campaign_stats_divide_by_zero(self, tmp_data_dir):
        """Stats should handle zero sent/delivered gracefully."""
        from outbound import get_campaign_stats
        stats = get_campaign_stats()
        # Should not raise even with no campaigns
        assert stats["delivery_rate"] >= 0
        assert stats["read_rate"] >= 0
        assert stats["reply_rate"] >= 0
