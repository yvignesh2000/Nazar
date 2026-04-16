"""
Nazar — AI Pipeline Stage Classifier

Automatically classifies contacts into pipeline stages based on
conversation history and signals. Called after every conversation turn.

Rules:
- Manual override flag (`manual_stage_override`) takes precedence — AI won't touch it.
- AI classification runs after conversation.py processes a message.
- Updates are logged to audit trail.
- WebSocket event is broadcast on stage changes.

Classification uses the LLM to analyze recent conversation context and
determine the appropriate pipeline stage.
"""

import json
import logging
from typing import Callable, Optional, List

logger = logging.getLogger("nazar")

PIPELINE_STAGES = ["New", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]

CLASSIFY_PROMPT = """You are a sales pipeline classifier for a WhatsApp sales bot. Based on the conversation history below, classify this contact into the correct pipeline stage.

## Pipeline Stages:
- **New**: First contact, no real conversation yet, just introductions
- **Qualified**: Contact has shown interest, asked questions about the product/service, shared their needs
- **Proposal**: A proposal, quote, pricing, or demo has been offered or discussed
- **Negotiation**: Active back-and-forth about terms, pricing, timelines, objections being handled
- **Won**: Contact confirmed purchase, signed up, made payment, or explicitly agreed to proceed
- **Lost**: Contact explicitly declined, went with a competitor, stopped responding for very long, or unsubscribed

## Rules:
1. Look at the FULL conversation context, not just the last message
2. Be conservative — only move forward when there's clear evidence
3. "Won" requires explicit confirmation from the customer (not just interest)
4. "Lost" requires explicit rejection or very prolonged silence (>14 days with no response after follow-up)
5. If unsure between two stages, pick the earlier (more conservative) one

Respond with EXACTLY one JSON object (no markdown, no explanation):
{"stage": "New|Qualified|Proposal|Negotiation|Won|Lost", "confidence": 0.0-1.0, "reason": "one-line explanation"}
"""


async def classify_contact_stage(
    contact: dict,
    recent_messages: List[dict],
    llm_call: Callable,
) -> Optional[dict]:
    """
    Use the LLM to classify a contact into a pipeline stage.

    Args:
        contact: Contact dict with current pipeline_stage, name, etc.
        recent_messages: List of recent message dicts (direction, content, timestamp).
        llm_call: Async function to call the LLM.

    Returns:
        {"stage": str, "confidence": float, "reason": str} or None on failure.
    """
    if not recent_messages:
        return None

    # Build conversation context
    current_stage = contact.get("pipeline_stage", "New")
    contact_name = contact.get("name", "Unknown")

    context_lines = []
    for msg in recent_messages[-15:]:  # Last 15 messages for context
        role = "Customer" if msg.get("direction") == "inbound" else "Sales Bot"
        content = msg.get("content", "")[:200]
        context_lines.append(f"{role}: {content}")

    conversation = "\n".join(context_lines)

    messages = [
        {"role": "system", "content": CLASSIFY_PROMPT},
        {"role": "user", "content": (
            f"Customer: {contact_name}\n"
            f"Current stage: {current_stage}\n"
            f"Deal value: ₹{contact.get('deal_value', 0):,.0f}\n"
            f"Lead score: {contact.get('lead_score', 0)}\n\n"
            f"Conversation:\n{conversation}"
        )},
    ]

    try:
        raw = await llm_call(messages)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)
        stage = result.get("stage", "")
        confidence = result.get("confidence", 0.0)
        reason = result.get("reason", "")

        if stage not in PIPELINE_STAGES:
            logger.warning("AI classifier returned invalid stage: %s", stage)
            return None

        if confidence < 0.6:
            logger.debug("AI classifier confidence too low (%.2f) for %s", confidence, contact_name)
            return None

        return {
            "stage": stage,
            "confidence": confidence,
            "reason": reason,
        }

    except json.JSONDecodeError:
        logger.warning("AI classifier returned invalid JSON: %s", raw[:100] if raw else "empty")
        return None
    except Exception as e:
        logger.warning("AI pipeline classification failed: %s", e)
        return None


def should_classify(contact: dict) -> bool:
    """
    Check if a contact should be auto-classified.

    Returns False if:
    - manual_stage_override is set (user manually moved the contact)
    - contact is in Won or Lost stage (terminal stages)
    """
    if contact.get("manual_stage_override"):
        return False
    if contact.get("pipeline_stage") in ("Won", "Lost"):
        return False
    return True
