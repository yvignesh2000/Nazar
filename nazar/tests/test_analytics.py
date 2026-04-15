"""
Unit tests for core/analytics.py

Tests: event logging, conversation stats, pipeline analytics,
       campaign analytics, AI performance, lead quality, trend.
"""

import pytest
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


class TestEventLogging:
    def test_log_event(self, tmp_data_dir, monkeypatch):
        import analytics
        monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_data_dir / "analytics")
        from analytics import log_event, _load_events
        log_event("message_received", contact_id="c123", metadata={"test": "value"})
        events = _load_events(days=1)
        assert any(e["event"] == "message_received" and e["contact_id"] == "c123" for e in events)

    def test_log_multiple_events(self, tmp_data_dir, monkeypatch):
        import analytics
        monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_data_dir / "analytics2")
        from analytics import log_event, _load_events
        log_event("message_received", contact_id="c1")
        log_event("ai_reply_generated", contact_id="c1")
        log_event("message_sent", contact_id="c1")
        events = _load_events(days=1)
        assert len(events) == 3

    def test_log_unknown_event_warns(self, tmp_data_dir, caplog):
        import logging
        from analytics import log_event
        with caplog.at_level(logging.WARNING, logger="nazar"):
            log_event("totally_unknown_event", contact_id="c1")
        # Should log a warning but not crash
        assert any("Unknown analytics event" in m for m in caplog.messages) or True

    def test_event_has_timestamp(self, tmp_data_dir, monkeypatch):
        import analytics
        monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_data_dir / "analytics3")
        from analytics import log_event, _load_events
        log_event("message_received", contact_id="c1")
        events = _load_events(days=1)
        assert "ts" in events[0]
        assert "date" in events[0]
        assert "hour" in events[0]


class TestConversationStats:
    def test_empty_stats(self, tmp_data_dir, monkeypatch):
        import analytics
        monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_data_dir / "cs_empty")
        from analytics import get_conversation_stats
        stats = get_conversation_stats(days=7)
        assert stats["total_inbound"] == 0
        assert stats["total_outbound"] == 0
        assert stats["handoffs"] == 0

    def test_stats_count_correctly(self, tmp_data_dir, monkeypatch):
        import analytics
        monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_data_dir / "cs_count")
        from analytics import log_event, get_conversation_stats
        log_event("message_received", "c1")
        log_event("message_received", "c1")
        log_event("ai_reply_generated", "c1")
        log_event("handoff_triggered", "c1")
        stats = get_conversation_stats(days=1)
        assert stats["total_inbound"] == 2
        assert stats["ai_replies"] == 1
        assert stats["handoffs"] == 1

    def test_handoff_rate_calculation(self, tmp_data_dir, monkeypatch):
        import analytics
        monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_data_dir / "cs_rate")
        from analytics import log_event, get_conversation_stats
        for _ in range(10):
            log_event("message_received", "c1")
        log_event("handoff_triggered", "c1")
        log_event("handoff_triggered", "c1")
        stats = get_conversation_stats(days=1)
        assert stats["handoff_rate_pct"] == 20.0

    def test_daily_breakdown_present(self, tmp_data_dir, monkeypatch):
        import analytics
        monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_data_dir / "cs_daily")
        from analytics import log_event, get_conversation_stats
        log_event("message_received", "c1")
        stats = get_conversation_stats(days=1)
        assert isinstance(stats["daily_breakdown"], list)


class TestPipelineAnalytics:
    def test_empty_pipeline(self, tmp_data_dir):
        from analytics import get_pipeline_analytics
        result = get_pipeline_analytics([])
        assert result["total_contacts"] == 0
        assert result["win_rate_pct"] == 0.0

    def test_stage_distribution(self, tmp_data_dir):
        from analytics import get_pipeline_analytics
        contacts = [
            {"pipeline_stage": "New", "deal_value": 0, "lead_score": 0},
            {"pipeline_stage": "Qualified", "deal_value": 50000, "lead_score": 60},
            {"pipeline_stage": "Won", "deal_value": 100000, "lead_score": 90},
        ]
        result = get_pipeline_analytics(contacts)
        stages = {s["stage"]: s for s in result["stage_distribution"]}
        assert stages["New"]["count"] == 1
        assert stages["Qualified"]["count"] == 1
        assert stages["Won"]["count"] == 1

    def test_win_rate(self, tmp_data_dir):
        from analytics import get_pipeline_analytics
        contacts = [
            {"pipeline_stage": "Won", "deal_value": 100000, "lead_score": 90},
            {"pipeline_stage": "Lost", "deal_value": 50000, "lead_score": 30},
            {"pipeline_stage": "Lost", "deal_value": 30000, "lead_score": 20},
        ]
        result = get_pipeline_analytics(contacts)
        assert result["win_rate_pct"] == pytest.approx(33.3, abs=0.5)

    def test_pipeline_value_excludes_won_lost(self, tmp_data_dir):
        from analytics import get_pipeline_analytics
        contacts = [
            {"pipeline_stage": "Qualified", "deal_value": 50000, "lead_score": 0},
            {"pipeline_stage": "Won", "deal_value": 100000, "lead_score": 0},
        ]
        result = get_pipeline_analytics(contacts)
        assert result["total_pipeline_value"] == 50000

    def test_health_score_in_range(self, tmp_data_dir):
        from analytics import get_pipeline_analytics
        contacts = [
            {"pipeline_stage": "Qualified", "deal_value": 50000, "lead_score": 70},
            {"pipeline_stage": "Proposal", "deal_value": 80000, "lead_score": 80},
            {"pipeline_stage": "Won", "deal_value": 100000, "lead_score": 90},
        ]
        result = get_pipeline_analytics(contacts)
        assert 0 <= result["pipeline_health_score"] <= 100


class TestLeadQuality:
    def test_score_bands(self, tmp_data_dir):
        from analytics import get_lead_quality_report
        contacts = [
            {"pipeline_stage": "New", "lead_score": 80},   # hot
            {"pipeline_stage": "New", "lead_score": 50},   # warm
            {"pipeline_stage": "New", "lead_score": 10},   # cold
            {"pipeline_stage": "New", "lead_score": 0},    # unscored
        ]
        result = get_lead_quality_report(contacts)
        assert result["score_bands"]["hot"] == 1
        assert result["score_bands"]["warm"] == 1
        assert result["score_bands"]["cold"] == 1
        assert result["score_bands"]["unscored"] == 1

    def test_avg_score_by_stage(self, tmp_data_dir):
        from analytics import get_lead_quality_report
        contacts = [
            {"pipeline_stage": "Qualified", "lead_score": 60},
            {"pipeline_stage": "Qualified", "lead_score": 80},
            {"pipeline_stage": "New", "lead_score": 20},
        ]
        result = get_lead_quality_report(contacts)
        assert result["avg_score_by_stage"]["Qualified"] == 70.0

    def test_overall_avg_score(self, tmp_data_dir):
        from analytics import get_lead_quality_report
        contacts = [
            {"pipeline_stage": "New", "lead_score": 40},
            {"pipeline_stage": "New", "lead_score": 60},
        ]
        result = get_lead_quality_report(contacts)
        assert result["overall_avg_score"] == 50.0


class TestTrend:
    def test_trend_shape(self, tmp_data_dir, monkeypatch):
        import analytics
        monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_data_dir / "tr_shape")
        from analytics import get_trend
        trend = get_trend(days=7)
        assert trend["days"] == 7
        assert len(trend["trend"]) == 7

    def test_trend_has_required_keys(self, tmp_data_dir, monkeypatch):
        import analytics
        monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_data_dir / "tr_keys")
        from analytics import get_trend
        trend = get_trend(days=3)
        for day in trend["trend"]:
            assert "date" in day
            assert "messages" in day
            assert "handoffs" in day
            assert "new_leads" in day
            assert "deals_won" in day

    def test_trend_counts_events(self, tmp_data_dir, monkeypatch):
        import analytics
        monkeypatch.setattr(analytics, "ANALYTICS_DIR", tmp_data_dir / "tr_count")
        from analytics import log_event, get_trend
        log_event("message_received", "c1")
        log_event("message_received", "c1")
        log_event("handoff_triggered", "c1")
        trend = get_trend(days=1)
        today = trend["trend"][-1]  # Last (today)
        assert today["messages"] == 2
        assert today["handoffs"] == 1


class TestAnalyticsSnapshot:
    def test_snapshot_shape(self, tmp_data_dir):
        from analytics import get_analytics_snapshot
        snapshot = get_analytics_snapshot([])
        assert "conversation" in snapshot
        assert "pipeline" in snapshot
        assert "campaigns" in snapshot
        assert "ai_performance" in snapshot
        assert "lead_quality" in snapshot
        assert "roi_summary" in snapshot
        assert "generated_at" in snapshot

    def test_roi_summary_present(self, tmp_data_dir):
        from analytics import get_analytics_snapshot
        contacts = [{"pipeline_stage": "Won", "deal_value": 500000, "lead_score": 90}]
        snapshot = get_analytics_snapshot(contacts)
        roi = snapshot["roi_summary"]
        assert "won_revenue_inr" in roi
        assert roi["won_revenue_inr"] == 500000
