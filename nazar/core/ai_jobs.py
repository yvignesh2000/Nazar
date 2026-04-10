"""
Async AI helpers that return artifacts suitable for background jobs.
"""

from __future__ import annotations

from conversation import generate_ai_reply
from customer_memory import add_memory_note, get_customer_summary
from llm_router import call_llm_safe
from outbound import generate_followup_context
from workspace_store import get_workspace_config


async def generate_followup_draft(contact: dict) -> str:
    memory_summary = get_customer_summary(contact["contact_id"])
    context = generate_followup_context(contact, memory_summary)
    messages = [
        {
            "role": "system",
            "content": (
                "You write concise WhatsApp follow-up drafts for sales reps. "
                "Keep it practical, natural, and conversion-oriented. "
                "Do not use markdown. Keep it under 90 words."
            ),
        },
        {"role": "user", "content": context},
    ]
    return await call_llm_safe(messages, tier="sonnet", phone=contact.get("phone"))


async def refresh_contact_summary(contact: dict, recent_messages: list[dict]) -> dict:
    memory_summary = get_customer_summary(contact["contact_id"])
    recent_text = "\n".join(
        f"{msg.get('direction', 'unknown')}: {msg.get('content', '')[:240]}"
        for msg in recent_messages[-12:]
    ) or "No recent messages."
    messages = [
        {
            "role": "system",
            "content": (
                "Summarize the customer for a sales team. "
                "Return plain text with current intent, objections, urgency, and next best action. "
                "Keep it under 140 words."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Customer: {contact.get('name') or contact.get('phone')}\n"
                f"Stage: {contact.get('pipeline_stage')}\n"
                f"Lead score: {contact.get('lead_score')}\n"
                f"Memory signals: {memory_summary.get('signal_counts', {})}\n"
                f"Recent messages:\n{recent_text}"
            ),
        },
    ]
    summary = await call_llm_safe(messages, tier="sonnet", phone=contact.get("phone"))
    add_memory_note(contact["contact_id"], summary)
    return {"summary": summary, "memory_summary": memory_summary}


async def generate_reply_suggestion(contact_id: str, message: str) -> dict:
    suggestion = await generate_ai_reply(contact_id, message, config=get_workspace_config())
    return {"suggested_reply": suggestion}
