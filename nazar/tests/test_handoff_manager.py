"""
Unit tests for core/handoff_manager.py

Tests: keyword detection, AI handoff evaluation, state persistence,
       queue management, auto-resume, team notification.
"""

import json
import pytest


class TestKeywordDetection:
    def test_explicit_request(self):
        from handoff_manager import check_keyword_handoff
        result = check_keyword_handoff("I want to talk to a person")
        assert result is not None
        assert result["category"] == "explicit_request"

    def test_escalation_keyword(self):
        from handoff_manager import check_keyword_handoff
        result = check_keyword_handoff("I will sue you for this!")
        assert result is not None
        assert result["category"] == "escalation"

    def test_no_match_returns_none(self):
        from handoff_manager import check_keyword_handoff
        assert check_keyword_handoff("What are your pricing plans?") is None
        assert check_keyword_handoff("Hello, I'm interested in your product") is None

    def test_human_in_context_no_false_positive(self):
        from handoff_manager import check_keyword_handoff
        assert check_keyword_handoff("I'm only human, I make mistakes") is None

    def test_case_insensitive(self):
        from handoff_manager import check_keyword_handoff
        result = check_keyword_handoff("GET ME A MANAGER")
        assert result is not None

    def test_refund_is_escalation(self):
        from handoff_manager import check_keyword_handoff
        result = check_keyword_handoff("I want a refund immediately")
        assert result is not None


class TestHandoffState:
    def test_default_bot_active(self, tmp_data_dir):
        from handoff_manager import is_bot_active
        assert is_bot_active("unknown_contact") is True

    def test_trigger_handoff(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, is_bot_active
        entry = trigger_handoff("c1", "Test reason", contact_name="Alice")
        assert entry["bot_active"] is False
        assert is_bot_active("c1") is False

    def test_resume_bot(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, resume_bot, is_bot_active
        trigger_handoff("c1", "Test reason")
        resume_bot("c1", resumed_by="manual")
        assert is_bot_active("c1") is True

    def test_get_contact_handoff_state(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, get_contact_handoff_state
        trigger_handoff("c1", "Test", contact_name="Alice", contact_phone="+91999")
        state = get_contact_handoff_state("c1")
        assert state is not None
        assert state["reason"] == "Test"
        assert state["contact_name"] == "Alice"

    def test_handoff_state_none_if_never_triggered(self, tmp_data_dir):
        from handoff_manager import get_contact_handoff_state
        assert get_contact_handoff_state("never_triggered") is None

    def test_mark_human_responded(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, mark_human_responded, get_contact_handoff_state
        trigger_handoff("c1", "reason")
        mark_human_responded("c1")
        state = get_contact_handoff_state("c1")
        assert state["human_responded"] is True
        assert state["human_responded_at"] is not None


class TestHandoffQueue:
    def test_queue_shows_in_handoff(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, get_handoff_queue
        trigger_handoff("c1", "reason", contact_name="Alice")
        queue = get_handoff_queue()
        assert len(queue) == 1
        assert queue[0]["contact_id"] == "c1"

    def test_queue_empty_when_bot_on(self, tmp_data_dir):
        from handoff_manager import get_handoff_queue
        assert get_handoff_queue() == []

    def test_queue_clears_after_resume(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, resume_bot, get_handoff_queue
        trigger_handoff("c1", "reason")
        resume_bot("c1")
        assert len(get_handoff_queue()) == 0

    def test_queue_sorted_newest_first(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, get_handoff_queue
        trigger_handoff("c1", "first reason", contact_name="A")
        trigger_handoff("c2", "second reason", contact_name="B")
        queue = get_handoff_queue()
        assert queue[0]["contact_id"] == "c2"  # Newest first


class TestHandoffHistory:
    def test_history_records_trigger(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, get_handoff_history
        trigger_handoff("c1", "reason")
        history = get_handoff_history()
        events = [e for e in history if e["event"] == "handoff_triggered"]
        assert len(events) == 1

    def test_history_records_resume(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, resume_bot, get_handoff_history
        trigger_handoff("c1", "reason")
        resume_bot("c1")
        history = get_handoff_history()
        events = [e for e in history if e["event"] == "bot_resumed"]
        assert len(events) == 1

    def test_history_limit(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, get_handoff_history
        for i in range(5):
            trigger_handoff(f"c{i}", "reason")
        history = get_handoff_history(limit=3)
        assert len(history) <= 3


class TestHandoffStats:
    def test_stats_shape(self, tmp_data_dir):
        from handoff_manager import get_handoff_stats
        stats = get_handoff_stats()
        assert "total_handoffs" in stats
        assert "total_resumes" in stats
        assert "currently_in_queue" in stats

    def test_stats_count_correctly(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, resume_bot, get_handoff_stats
        trigger_handoff("c1", "reason1", detection_method="keyword")
        trigger_handoff("c2", "reason2", detection_method="ai_intent")
        resume_bot("c1")
        stats = get_handoff_stats()
        assert stats["total_handoffs"] == 2
        assert stats["total_resumes"] == 1
        assert stats["currently_in_queue"] == 1


class TestAIResponseHandoff:
    def test_ai_response_triggers_handoff(self):
        from handoff_manager import check_ai_response_handoff
        result = check_ai_response_handoff(
            "Let me connect you with someone from the team who can help."
        )
        assert result is not None
        assert "reason" in result

    def test_normal_response_no_handoff(self):
        from handoff_manager import check_ai_response_handoff
        result = check_ai_response_handoff(
            "Our starter plan is ₹1,999 per month. Would you like to sign up?"
        )
        assert result is None

    def test_team_member_phrase_triggers(self):
        from handoff_manager import check_ai_response_handoff
        result = check_ai_response_handoff("A team member will reach out to you shortly.")
        assert result is not None


class TestAutoResume:
    def test_auto_resume_disabled_by_default(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, check_auto_resume
        trigger_handoff("c1", "reason")
        resumed = check_auto_resume(auto_resume_hours=0)
        assert len(resumed) == 0

    def test_auto_resume_happens_when_threshold_reached(self, tmp_data_dir):
        from handoff_manager import trigger_handoff, check_auto_resume, is_bot_active
        from handoff_manager import _load_state, _save_state
        from datetime import datetime, timezone, timedelta

        trigger_handoff("c1", "reason")

        # Backdate the triggered_at to 5 hours ago
        state = _load_state()
        five_hours_ago = (datetime.now(timezone(timedelta(hours=5, minutes=30))) - timedelta(hours=5)).isoformat()
        state["c1"]["triggered_at"] = five_hours_ago
        _save_state(state)

        resumed = check_auto_resume(auto_resume_hours=4)
        assert "c1" in resumed
        assert is_bot_active("c1") is True


class TestTeamNotification:
    def test_notification_format(self):
        from handoff_manager import build_team_notification
        msg = build_team_notification("Alice", "+91999", "Customer frustrated", "This is terrible")
        assert "Alice" in msg
        assert "+91999" in msg
        assert "Handoff Alert" in msg
        assert "This is terrible" in msg

    def test_notification_with_empty_name(self):
        from handoff_manager import build_team_notification
        msg = build_team_notification("", "+91999", "reason", "msg")
        assert "Unknown" in msg  # Fallback for empty name
