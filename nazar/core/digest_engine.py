"""
Nazar — Digest Engine

Generates scheduled reports, follow-up reminders, and
AI-powered insights for the sales team.

Features:
1. Daily digest — pipeline summary, follow-ups due, key activity
2. Follow-up prioritization — score contacts by urgency
3. AI insight generation — surface patterns from memory data
4. Scheduled reports — configurable frequency

This module is stateless — it queries the contact manager
and memory system on demand.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Follow-up prioritization
# ---------------------------------------------------------------------------

def get_followup_queue(
    contacts: list,
    min_days: int = 2,
    include_won: bool = False,
) -> list:
    """
    Generate a prioritized follow-up queue.

    Contacts are scored based on:
    - Days since last contact (higher = more urgent)
    - Deal value (higher value = higher priority)
    - Pipeline stage (Negotiation > Proposal > Qualified > New)
    - Lead score (higher = more priority)

    Args:
        contacts: List of contact profile dicts.
        min_days: Minimum days since last contact to include.
        include_won: Whether to include Won/Lost contacts.

    Returns:
        List of followup dicts sorted by priority score (highest first).
    """
    now = datetime.now(IST)
    followups = []

    stage_weights = {
        "Negotiation": 50,
        "Proposal": 40,
        "Qualified": 30,
        "New": 10,
        "Won": 5,
        "Lost": 0,
    }

    for contact in contacts:
        stage = contact.get("pipeline_stage", "New")
        if not include_won and stage in ("Won", "Lost"):
            continue

        # Calculate days since last contact
        last_contact = (
            contact.get("last_contacted_at")
            or contact.get("last_replied_at")
            or contact.get("created_at")
            or ""
        )
        if not last_contact:
            continue

        try:
            last_dt = datetime.fromisoformat(last_contact)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=IST)
            days_since = (now - last_dt).days
        except Exception:
            days_since = 999

        if days_since < min_days:
            continue

        # Calculate priority score (0-100)
        days_score = min(days_since * 5, 30)  # max 30 from days
        value_score = min(contact.get("deal_value", 0) / 20000, 25)  # max 25 from value
        stage_score = stage_weights.get(stage, 10)  # max 50 from stage
        lead_score_bonus = contact.get("lead_score", 0) * 0.1  # max 10 from lead score

        priority_score = round(days_score + value_score + stage_score + lead_score_bonus, 1)
        priority_score = min(priority_score, 100)

        # Classify priority
        if priority_score >= 60 or days_since >= 7:
            priority = "high"
        elif priority_score >= 35 or days_since >= 4:
            priority = "medium"
        else:
            priority = "low"

        followups.append({
            "contact_id": contact["contact_id"],
            "name": contact.get("name", "Unknown"),
            "phone": contact.get("phone", ""),
            "company": contact.get("company", ""),
            "stage": stage,
            "deal_value": contact.get("deal_value", 0),
            "lead_score": contact.get("lead_score", 0),
            "days_since_contact": days_since,
            "last_contacted_at": last_contact,
            "priority": priority,
            "priority_score": priority_score,
            "tags": contact.get("tags", []),
        })

    # Sort by priority score descending
    followups.sort(key=lambda f: f["priority_score"], reverse=True)
    return followups


# ---------------------------------------------------------------------------
# Daily digest generation
# ---------------------------------------------------------------------------

def generate_daily_digest(contacts: list, pipeline_summary: dict) -> dict:
    """
    Generate a daily sales digest.

    Args:
        contacts: List of all contact dicts.
        pipeline_summary: Pipeline summary from contact_manager.

    Returns:
        Digest dict with:
        - summary: text summary
        - stats: key metrics
        - followups: prioritized follow-up list
        - insights: AI-generated insights
        - at_risk: deals at risk of going cold
    """
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")

    # Basic stats
    total_contacts = len(contacts)
    active_deals = [
        c for c in contacts
        if c.get("pipeline_stage") not in ("Won", "Lost")
    ]
    pipeline_value = sum(c.get("deal_value", 0) for c in active_deals)
    won_deals = [c for c in contacts if c.get("pipeline_stage") == "Won"]
    revenue = sum(c.get("deal_value", 0) for c in won_deals)

    # Follow-ups
    followups = get_followup_queue(contacts, min_days=2)
    high_priority = [f for f in followups if f["priority"] == "high"]

    # At-risk deals (high value + no contact in 5+ days)
    at_risk = [
        f for f in followups
        if f["days_since_contact"] >= 5 and f["deal_value"] >= 100000
    ]
    at_risk_value = sum(f["deal_value"] for f in at_risk)

    # New contacts today
    new_today = [
        c for c in contacts
        if (c.get("created_at") or "")[:10] == today
    ]

    # Generate insights
    insights = _generate_insights(contacts, followups, pipeline_summary)

    # Build text summary
    summary_parts = [
        f"📊 Daily Sales Digest — {now.strftime('%B %d, %Y')}",
        f"",
        f"Pipeline: {len(active_deals)} active deals worth ₹{pipeline_value:,.0f}",
        f"Revenue: ₹{revenue:,.0f} from {len(won_deals)} closed deals",
        f"New today: {len(new_today)} contacts",
        f"",
        f"⚠️ {len(high_priority)} high-priority follow-ups pending",
    ]

    if at_risk:
        summary_parts.append(
            f"🔴 {len(at_risk)} deals at risk (₹{at_risk_value:,.0f}) — no contact in 5+ days"
        )

    return {
        "date": today,
        "summary": "\n".join(summary_parts),
        "stats": {
            "total_contacts": total_contacts,
            "active_deals": len(active_deals),
            "pipeline_value": pipeline_value,
            "revenue": revenue,
            "won_deals": len(won_deals),
            "new_today": len(new_today),
            "followups_due": len(followups),
            "high_priority": len(high_priority),
            "at_risk_count": len(at_risk),
            "at_risk_value": at_risk_value,
        },
        "followups": followups[:20],  # Top 20
        "at_risk": at_risk,
        "insights": insights,
        "generated_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# AI insight generation
# ---------------------------------------------------------------------------

def _generate_insights(
    contacts: list,
    followups: list,
    pipeline_summary: dict,
) -> list:
    """
    Generate rule-based insights from pipeline data.

    In the future, these can be powered by LLM analysis.
    For now, they're pattern-based.
    """
    insights = []
    now = datetime.now(IST)

    # Insight 1: Follow-up urgency
    high_prio = [f for f in followups if f["priority"] == "high"]
    if high_prio:
        total_value = sum(f["deal_value"] for f in high_prio)
        insights.append({
            "type": "urgency",
            "icon": "🔴",
            "text": (
                f"{len(high_prio)} deals haven't been followed up in 5+ days — "
                f"₹{total_value:,.0f} at risk"
            ),
            "action": "View follow-ups",
            "screen": "followups",
        })

    # Insight 2: Pipeline health
    active = [
        c for c in contacts
        if c.get("pipeline_stage") not in ("Won", "Lost")
    ]
    if active:
        stages = {}
        for c in active:
            s = c.get("pipeline_stage", "New")
            stages[s] = stages.get(s, 0) + 1

        # Check for pipeline imbalance
        new_count = stages.get("New", 0)
        qualified_count = stages.get("Qualified", 0)
        if new_count > 0 and qualified_count == 0:
            insights.append({
                "type": "pipeline",
                "icon": "📈",
                "text": (
                    f"You have {new_count} leads in 'New' but none in 'Qualified'. "
                    f"Consider qualifying your leads to keep the pipeline flowing."
                ),
                "action": "Open pipeline",
                "screen": "pipeline",
            })

    # Insight 3: High-value deals
    high_value = [
        c for c in contacts
        if c.get("deal_value", 0) >= 500000
        and c.get("pipeline_stage") not in ("Won", "Lost")
    ]
    if high_value:
        names = ", ".join(c.get("name", "Unknown") for c in high_value[:3])
        insights.append({
            "type": "opportunity",
            "icon": "💎",
            "text": (
                f"{len(high_value)} high-value deals (₹5L+) in pipeline: {names}"
            ),
            "action": "View deals",
            "screen": "pipeline",
        })

    # Insight 4: Bot performance (if any contacts have messages)
    contacts_with_msgs = [c for c in contacts if c.get("total_messages", 0) > 0]
    if contacts_with_msgs:
        avg_msgs = sum(
            c.get("total_messages", 0) for c in contacts_with_msgs
        ) / len(contacts_with_msgs)
        insights.append({
            "type": "performance",
            "icon": "🤖",
            "text": (
                f"Bot has handled conversations with {len(contacts_with_msgs)} contacts. "
                f"Average {avg_msgs:.0f} messages per conversation."
            ),
            "action": "View conversations",
            "screen": "conversations",
        })

    # Insight 5: Tip when pipeline is empty
    if not active:
        insights.append({
            "type": "tip",
            "icon": "💡",
            "text": "Your pipeline is empty. Add contacts manually or connect WhatsApp to start receiving leads.",
            "action": "Add contact",
            "screen": "pipeline",
        })

    return insights


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_digest_for_whatsapp(digest: dict) -> str:
    """
    Format a daily digest as a WhatsApp message.

    Can be sent to the business owner's WhatsApp as a daily report.
    """
    stats = digest["stats"]
    lines = [
        "🧿 *Nazar Daily Digest*",
        f"📅 {digest['date']}",
        "",
        f"📊 *Pipeline*",
        f"  Active deals: {stats['active_deals']}",
        f"  Pipeline value: ₹{stats['pipeline_value']:,.0f}",
        f"  Revenue won: ₹{stats['revenue']:,.0f}",
        "",
    ]

    if stats["followups_due"] > 0:
        lines.append(f"🔔 *Follow-ups Due:* {stats['followups_due']}")
        if stats["high_priority"] > 0:
            lines.append(f"  ⚠️ {stats['high_priority']} high priority")

    if stats["at_risk_count"] > 0:
        lines.append(
            f"\n🔴 *At Risk:* {stats['at_risk_count']} deals "
            f"(₹{stats['at_risk_value']:,.0f})"
        )

    # Top 3 follow-ups
    followups = digest.get("followups", [])[:3]
    if followups:
        lines.append("\n📋 *Top Follow-ups:*")
        for f in followups:
            lines.append(
                f"  • {f['name']} — {f['stage']} — "
                f"₹{f['deal_value']:,.0f} — {f['days_since_contact']}d ago"
            )

    # Insights
    insights = digest.get("insights", [])[:3]
    if insights:
        lines.append("\n💡 *Insights:*")
        for i in insights:
            lines.append(f"  {i['icon']} {i['text']}")

    lines.append("\n_Sent by Nazar AI_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Digest history
# ---------------------------------------------------------------------------

def save_digest(digest: dict):
    """Save a generated digest for history."""
    path = DATA_DIR / "digests.json"
    history = []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass

    history.insert(0, digest)
    history = history[:30]  # Keep last 30 digests
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def get_digest_history(limit: int = 10) -> list:
    """Get digest history."""
    path = DATA_DIR / "digests.json"
    if not path.exists():
        return []
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
        return history[:limit]
    except Exception:
        return []
