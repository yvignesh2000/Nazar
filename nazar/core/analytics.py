"""
Nazar — Analytics Engine

Provides business intelligence for the sales team and buyers:
- Conversation analytics (reply rates, response times, session lengths)
- Campaign performance (delivery, open/reply rates)
- Pipeline velocity (time in stage, conversion rates)
- AI performance (handoff rates, fallback rates, model usage)
- Revenue metrics (deals closed, pipeline value over time)
- Lead scoring distribution and movement
- Daily / weekly / monthly trend reports

Storage: data/analytics/ (event log JSONL + computed snapshots)
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"
ANALYTICS_DIR = DATA_DIR / "analytics"


# ---------------------------------------------------------------------------
# Event logging (append-only audit log of business events)
# ---------------------------------------------------------------------------

EVENT_TYPES = {
    # Conversation events
    "message_received",
    "message_sent",
    "ai_reply_generated",
    "handoff_triggered",
    "bot_resumed",
    # Lead / pipeline events
    "contact_created",
    "stage_changed",
    "lead_score_updated",
    "deal_value_set",
    # Campaign events
    "campaign_sent",
    "campaign_delivered",
    "campaign_replied",
    # Revenue events
    "deal_won",
    "deal_lost",
    # System events
    "llm_fallback",
    "llm_error",
    "whatsapp_error",
}


def log_event(
    event_type: str,
    contact_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
):
    """
    Append a business event to the analytics event log.

    Args:
        event_type: One of EVENT_TYPES.
        contact_id: Associated contact (empty for system events).
        metadata: Any additional structured data.
    """
    if event_type not in EVENT_TYPES:
        logger.warning(f"Unknown analytics event type: {event_type}")

    now = datetime.now(IST)
    entry = {
        "ts": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "hour": now.hour,
        "event": event_type,
        "contact_id": contact_id,
        **(metadata or {}),
    }

    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = ANALYTICS_DIR / f"{now.strftime('%Y-%m-%d')}.jsonl"

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Analytics log write failed: {e}")


def _load_events(days: int = 30) -> List[dict]:
    """Load analytics events from the last N days."""
    events = []
    now = datetime.now(IST)
    for i in range(days):
        date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        path = ANALYTICS_DIR / f"{date}.jsonl"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            events.append(json.loads(line))
            except Exception as e:
                logger.warning(f"Analytics read failed for {date}: {e}")
    return events


# ---------------------------------------------------------------------------
# Conversation analytics
# ---------------------------------------------------------------------------

def get_conversation_stats(days: int = 7) -> dict:
    """
    Compute conversation-level metrics for the last N days.

    Returns:
        total_messages, inbound, outbound, ai_replies,
        avg_response_time_minutes (estimated), handoff_rate,
        daily_breakdown list
    """
    events = _load_events(days)

    total_inbound = sum(1 for e in events if e.get("event") == "message_received")
    total_outbound = sum(1 for e in events if e.get("event") == "message_sent")
    ai_replies = sum(1 for e in events if e.get("event") == "ai_reply_generated")
    handoffs = sum(1 for e in events if e.get("event") == "handoff_triggered")

    # Group by day
    by_day: Dict[str, dict] = {}
    for e in events:
        d = e.get("date", "")
        if not d:
            continue
        if d not in by_day:
            by_day[d] = {"date": d, "inbound": 0, "outbound": 0, "ai_replies": 0, "handoffs": 0}
        evt = e.get("event", "")
        if evt == "message_received":
            by_day[d]["inbound"] += 1
        elif evt == "message_sent":
            by_day[d]["outbound"] += 1
        elif evt == "ai_reply_generated":
            by_day[d]["ai_replies"] += 1
        elif evt == "handoff_triggered":
            by_day[d]["handoffs"] += 1

    daily = sorted(by_day.values(), key=lambda x: x["date"])

    handoff_rate = round(handoffs / max(total_inbound, 1) * 100, 1)
    ai_reply_rate = round(ai_replies / max(total_inbound, 1) * 100, 1)

    return {
        "period_days": days,
        "total_inbound": total_inbound,
        "total_outbound": total_outbound,
        "ai_replies": ai_replies,
        "handoffs": handoffs,
        "handoff_rate_pct": handoff_rate,
        "ai_reply_rate_pct": ai_reply_rate,
        "daily_breakdown": daily,
    }


# ---------------------------------------------------------------------------
# Pipeline analytics
# ---------------------------------------------------------------------------

def get_pipeline_analytics(contacts: list) -> dict:
    """
    Compute pipeline velocity and conversion metrics from contact data.

    Args:
        contacts: List of contact profile dicts (from contact_manager).

    Returns:
        stage_distribution, conversion_rates, avg_deal_value,
        win_rate, pipeline_health_score
    """
    from contact_manager import PIPELINE_STAGES

    stage_counts: Dict[str, int] = {s: 0 for s in PIPELINE_STAGES}
    stage_values: Dict[str, float] = {s: 0.0 for s in PIPELINE_STAGES}

    for c in contacts:
        stage = c.get("pipeline_stage", "New")
        value = float(c.get("deal_value") or 0)
        if stage in stage_counts:
            stage_counts[stage] += 1
            stage_values[stage] += value

    total = len(contacts)
    won = stage_counts.get("Won", 0)
    lost = stage_counts.get("Lost", 0)
    closed = won + lost

    win_rate = round(won / max(closed, 1) * 100, 1)
    total_pipeline_value = sum(
        v for s, v in stage_values.items() if s not in ("Won", "Lost")
    )
    avg_deal = round(
        sum(float(c.get("deal_value") or 0) for c in contacts) / max(total, 1), 0
    )

    # Pipeline health score (0-100)
    # Penalise: too many in New, none in Negotiation, empty pipeline
    health = 50
    if stage_counts.get("Qualified", 0) > 0:
        health += 15
    if stage_counts.get("Proposal", 0) > 0:
        health += 10
    if stage_counts.get("Negotiation", 0) > 0:
        health += 10
    if win_rate > 20:
        health += 15
    if stage_counts.get("New", 0) > total * 0.7 and total > 5:
        health -= 20  # Most leads stuck in New = bad
    health = max(0, min(100, health))

    stage_distribution = [
        {
            "stage": s,
            "count": stage_counts[s],
            "value": round(stage_values[s], 0),
            "pct": round(stage_counts[s] / max(total, 1) * 100, 1),
        }
        for s in PIPELINE_STAGES
    ]

    return {
        "total_contacts": total,
        "stage_distribution": stage_distribution,
        "win_rate_pct": win_rate,
        "total_pipeline_value": round(total_pipeline_value, 0),
        "total_won_value": round(stage_values.get("Won", 0), 0),
        "avg_deal_value": avg_deal,
        "pipeline_health_score": health,
        "won": won,
        "lost": lost,
        "active": total - closed,
    }


# ---------------------------------------------------------------------------
# Campaign analytics
# ---------------------------------------------------------------------------

def get_campaign_analytics(days: int = 30) -> dict:
    """
    Return campaign performance metrics.

    Reads from the analytics event log and campaign history.
    """
    events = _load_events(days)
    campaign_events = [e for e in events if e.get("event") == "campaign_sent"]

    total_campaigns = len(campaign_events)
    total_sent = sum(e.get("sent", 0) for e in campaign_events)
    total_failed = sum(e.get("failed", 0) for e in campaign_events)
    total_targeted = sum(e.get("targeted", 0) for e in campaign_events)

    delivery_rate = round(total_sent / max(total_targeted, 1) * 100, 1)

    # Also load from campaigns history file
    campaigns_path = DATA_DIR / "campaigns.json"
    campaign_history = []
    if campaigns_path.exists():
        try:
            campaign_history = json.loads(campaigns_path.read_text())
        except Exception:
            pass

    recent_campaigns = [
        c for c in campaign_history
        if (c.get("created_at") or "")[:10] >= (
            datetime.now(IST) - timedelta(days=days)
        ).strftime("%Y-%m-%d")
    ]

    return {
        "period_days": days,
        "total_campaigns": max(total_campaigns, len(recent_campaigns)),
        "total_messages_sent": total_sent or sum(c.get("sent", 0) for c in recent_campaigns),
        "total_failed": total_failed or sum(c.get("failed", 0) for c in recent_campaigns),
        "delivery_rate_pct": delivery_rate,
        "recent_campaigns": recent_campaigns[:10],
    }


# ---------------------------------------------------------------------------
# AI performance analytics
# ---------------------------------------------------------------------------

def get_ai_performance(days: int = 7) -> dict:
    """
    LLM performance metrics: fallback rates, model usage, cost.

    Combines analytics event log with the usage tracker.
    """
    from usage_tracker import get_daily_usage
    now = datetime.now(IST)

    daily_usage = []
    total_calls = 0
    total_cost = 0.0
    total_tokens = 0
    by_model: Dict[str, int] = {}

    for i in range(days):
        date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        u = get_daily_usage(date)
        daily_usage.append(u)
        total_calls += u.get("total_calls", 0)
        total_cost += u.get("total_cost_usd", 0)
        total_tokens += u.get("total_tokens", 0)
        for provider, stats in u.get("by_provider", {}).items():
            by_model[provider] = by_model.get(provider, 0) + stats.get("calls", 0)

    events = _load_events(days)
    fallbacks = sum(1 for e in events if e.get("event") == "llm_fallback")
    errors = sum(1 for e in events if e.get("event") == "llm_error")

    return {
        "period_days": days,
        "total_llm_calls": total_calls,
        "total_cost_usd": round(total_cost, 4),
        "total_tokens": total_tokens,
        "avg_cost_per_call_usd": round(total_cost / max(total_calls, 1), 6),
        "fallback_events": fallbacks,
        "error_events": errors,
        "calls_by_provider": by_model,
        "daily_usage": list(reversed(daily_usage)),  # oldest first
    }


# ---------------------------------------------------------------------------
# Lead scoring analytics
# ---------------------------------------------------------------------------

def get_lead_quality_report(contacts: list) -> dict:
    """
    Analyse lead quality distribution and scoring.

    Returns score bands, avg score by stage, signal distribution.
    """
    score_bands = {"hot": 0, "warm": 0, "cold": 0, "unscored": 0}
    by_stage: Dict[str, list] = {}

    for c in contacts:
        score = c.get("lead_score", 0)
        stage = c.get("pipeline_stage", "New")

        if score >= 70:
            score_bands["hot"] += 1
        elif score >= 40:
            score_bands["warm"] += 1
        elif score > 0:
            score_bands["cold"] += 1
        else:
            score_bands["unscored"] += 1

        if stage not in by_stage:
            by_stage[stage] = []
        by_stage[stage].append(score)

    avg_by_stage = {
        s: round(sum(scores) / len(scores), 1)
        for s, scores in by_stage.items()
        if scores
    }

    total = len(contacts)
    return {
        "total_contacts": total,
        "score_bands": score_bands,
        "score_band_pcts": {
            k: round(v / max(total, 1) * 100, 1)
            for k, v in score_bands.items()
        },
        "avg_score_by_stage": avg_by_stage,
        "overall_avg_score": round(
            sum(c.get("lead_score", 0) for c in contacts) / max(total, 1), 1
        ),
    }


# ---------------------------------------------------------------------------
# Full analytics dashboard snapshot
# ---------------------------------------------------------------------------

def get_analytics_snapshot(contacts: list) -> dict:
    """
    Generate a complete analytics snapshot for the dashboard.

    Aggregates all analytics modules into one response.
    Suitable for the /api/analytics endpoint.
    """
    conversation = get_conversation_stats(days=7)
    pipeline = get_pipeline_analytics(contacts)
    campaigns = get_campaign_analytics(days=30)
    ai_perf = get_ai_performance(days=7)
    lead_quality = get_lead_quality_report(contacts)

    # Compute a top-level ROI summary
    won_value = pipeline.get("total_won_value", 0)
    ai_cost = ai_perf.get("total_cost_usd", 0)
    roi_multiple = round(won_value / max(ai_cost * 82, 1), 1)  # rough USD→INR at 82

    return {
        "generated_at": datetime.now(IST).isoformat(),
        "conversation": conversation,
        "pipeline": pipeline,
        "campaigns": campaigns,
        "ai_performance": ai_perf,
        "lead_quality": lead_quality,
        "roi_summary": {
            "won_revenue_inr": won_value,
            "ai_cost_usd": ai_cost,
            "estimated_roi_multiple": roi_multiple,
        },
    }


# ---------------------------------------------------------------------------
# Trend helpers
# ---------------------------------------------------------------------------

def get_trend(days: int = 14) -> dict:
    """
    Return a day-by-day trend of key metrics for charts.

    Suitable for sparkline / area chart rendering on the dashboard.
    """
    now = datetime.now(IST)
    trend = []

    for i in range(days - 1, -1, -1):
        date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        path = ANALYTICS_DIR / f"{date}.jsonl"
        day_events = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            day_events.append(json.loads(line))
            except Exception:
                pass

        trend.append({
            "date": date,
            "messages": sum(
                1 for e in day_events if e.get("event") == "message_received"
            ),
            "ai_replies": sum(
                1 for e in day_events if e.get("event") == "ai_reply_generated"
            ),
            "handoffs": sum(
                1 for e in day_events if e.get("event") == "handoff_triggered"
            ),
            "new_leads": sum(
                1 for e in day_events if e.get("event") == "contact_created"
            ),
            "deals_won": sum(
                1 for e in day_events if e.get("event") == "deal_won"
            ),
        })

    return {"days": days, "trend": trend}
