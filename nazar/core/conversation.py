"""
Nazar — Conversation Engine

Handles inbound customer messages:
1. Loads contact profile + memory
2. Builds LLM prompt with SOUL + knowledge base + memory context
3. Generates AI reply
4. Extracts signals (buying, objections, intent)
5. Saves everything to contact history + vector store
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
SOUL_PATH = Path(__file__).parent.parent / "agent" / "SOUL.md"

# Cache SOUL.md in memory
_soul_cache = None


def _load_soul() -> str:
    """Load the bot persona from SOUL.md."""
    global _soul_cache
    if _soul_cache is None:
        if SOUL_PATH.exists():
            _soul_cache = SOUL_PATH.read_text(encoding="utf-8")
        else:
            _soul_cache = "You are a helpful sales assistant."
            logger.warning("SOUL.md not found, using default persona")
    return _soul_cache


def _build_system_prompt(
    contact: Optional[dict],
    memory_context: str,
    knowledge_base: str,
    config: dict,
) -> str:
    """Build the system prompt for the LLM."""
    soul = _load_soul()

    business_name = config.get("business_name", "our company")
    customer_name = contact.get("name", "there") if contact else "there"
    pipeline_stage = contact.get("pipeline_stage", "New") if contact else "New"
    tags = ", ".join(contact.get("tags", [])) if contact else ""

    # Replace template variables
    prompt = soul
    prompt = prompt.replace("{business_name}", business_name)
    prompt = prompt.replace("{customer_name}", customer_name)
    prompt = prompt.replace("{knowledge_base}", knowledge_base or "No knowledge base configured yet.")
    prompt = prompt.replace("{memory_context}", memory_context or "No previous interactions.")

    # Add contact context
    if contact:
        contact_context = f"""
## Current Customer Context
- Name: {customer_name}
- Pipeline Stage: {pipeline_stage}
- Deal Value: {contact.get('deal_value', 'Not set')}
- Lead Score: {contact.get('lead_score', 0)}/100
- Tags: {tags or 'None'}
- Total Messages: {contact.get('total_messages', 0)}
- Notes: {contact.get('notes', 'None')}
"""
        prompt += "\n" + contact_context

    return prompt


def _build_messages(
    system_prompt: str,
    recent_messages: list,
    current_message: str,
) -> list:
    """Build the message array for the LLM call."""
    messages = [{"role": "system", "content": system_prompt}]

    # Add recent conversation history (last 20 messages)
    for msg in recent_messages[-20:]:
        role = "user" if msg.get("direction") == "inbound" else "assistant"
        messages.append({"role": role, "content": msg["content"]})

    # Add current message
    messages.append({"role": "user", "content": current_message})

    return messages


async def handle_inbound(
    phone: str,
    message: str,
    llm_call: Callable,
    config: Optional[dict] = None,
) -> str:
    """
    Handle an inbound customer message end-to-end.

    Args:
        phone: Customer phone number (E.164)
        message: The message text
        llm_call: async callable that takes messages list, returns response string
        config: Bot configuration dict (business_name, etc.)

    Returns:
        AI-generated response string
    """
    from contact_manager import (
        get_contact_by_phone, create_contact, save_message,
        get_conversation_history, update_contact,
    )
    from customer_memory import (
        get_relevant_context, add_message as add_to_memory,
        extract_signals_from_message, add_signal,
    )

    if config is None:
        config = _load_config()

    now = datetime.now(IST).isoformat()

    # 1. Get or create contact
    contact = get_contact_by_phone(phone)
    if contact is None:
        contact = create_contact(name="", phone=phone, source="whatsapp_inbound")
        logger.info(f"New contact created for {phone}: {contact['contact_id']}")

    contact_id = contact["contact_id"]

    # 2. Save inbound message
    save_message(contact_id, "inbound", message)

    # 3. Get memory context
    memory_context = get_relevant_context(contact_id, message)

    # 4. Get recent conversation history
    recent = get_conversation_history(contact_id, days=7)

    # 5. Load knowledge base
    knowledge_base = _load_knowledge_base()

    # 6. Build prompt and call LLM
    system_prompt = _build_system_prompt(contact, memory_context, knowledge_base, config)
    messages = _build_messages(system_prompt, recent, message)

    response = await llm_call(messages)

    # 7. Save outbound response
    save_message(contact_id, "outbound", response, sent_by="bot")

    # 8. Add both messages to vector memory
    add_to_memory(contact_id, "inbound", message, timestamp=now)
    add_to_memory(contact_id, "outbound", response, timestamp=now)

    # 9. Extract and store signals
    signals = extract_signals_from_message(message, "inbound")
    for sig in signals:
        add_signal(contact_id, sig["type"], sig["content"], timestamp=now)

    # 10. Update contact stats
    update_contact(
        contact_id,
        total_messages=contact.get("total_messages", 0) + 2,
        last_replied_at=now,
    )

    # 11. Auto-update lead score based on signals
    if signals:
        _auto_score(contact_id, contact, signals)

    logger.info(f"[{phone}] Handled inbound, response: {response[:60]}...")
    return response


def _auto_score(contact_id: str, contact: dict, signals: list):
    """Automatically adjust lead score based on detected signals."""
    from contact_manager import update_lead_score

    current_score = contact.get("lead_score", 0)
    delta = 0

    for sig in signals:
        if sig["type"] == "buying_signal":
            delta += 10
        elif sig["type"] == "intent":
            delta += 15
        elif sig["type"] == "objection":
            delta -= 5
        elif sig["type"] == "price_sensitivity":
            delta += 5  # They're thinking about price = interested

    new_score = max(0, min(100, current_score + delta))
    if new_score != current_score:
        update_lead_score(contact_id, new_score)


def _load_knowledge_base() -> str:
    """Load the business knowledge base."""
    kb_path = Path(__file__).parent.parent / "data" / "knowledge_base.txt"
    if kb_path.exists():
        return kb_path.read_text(encoding="utf-8")[:8000]  # Cap at 8K chars
    return ""


def _load_config() -> dict:
    """Load bot configuration."""
    import json
    config_path = Path(__file__).parent.parent / "data" / "config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"business_name": "our company", "bot_enabled": True}


async def generate_ai_reply(
    contact_id: str,
    message: str,
    config: Optional[dict] = None,
) -> str:
    """
    Generate an AI reply without the full inbound pipeline.
    Used for dashboard-initiated AI suggestions.
    """
    from contact_manager import get_contact, get_conversation_history
    from customer_memory import get_relevant_context

    if config is None:
        config = _load_config()

    contact = get_contact(contact_id)
    if not contact:
        return "Contact not found."

    memory_context = get_relevant_context(contact_id, message)
    recent = get_conversation_history(contact_id, days=7)
    knowledge_base = _load_knowledge_base()

    system_prompt = _build_system_prompt(contact, memory_context, knowledge_base, config)
    messages = _build_messages(system_prompt, recent, message)

    from llm_router import call_llm_safe
    return await call_llm_safe(messages, tier="sonnet")


def should_handoff(message: str) -> bool:
    """
    Legacy keyword-based handoff check.
    Kept for backward compatibility but the real logic lives in
    handoff_manager.evaluate_handoff() which is called from server.py.
    """
    from handoff_manager import check_keyword_handoff
    return check_keyword_handoff(message) is not None
