"""
Nazar product simulator.

Lets operators test inbox and broadcast product flows without WhatsApp.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from conversation import generate_reply_for_contact
from contact_manager import (
    create_contact,
    get_contact,
    get_contact_by_phone,
    get_conversation_record,
    list_contacts,
    mark_conversation_handoff_required,
    save_message,
    set_conversation_ai_assist,
    set_conversation_status,
    set_conversation_use_case,
    update_contact,
    update_message_status_by_wa_id,
    PIPELINE_STAGES,
)
from llm_router import call_llm_safe
from ai_classifier import classify_and_apply
from outbound import log_broadcast, personalize_message
from policy_store import apply_ai_ownership_recommendation, resolve_policy_for_context, should_force_human, upsert_reply_policy
from template_manager import get_template_by_name, render_template
from workspace_store import get_workspace_config

HANDOFF_MESSAGE = "Thanks for the message. I've routed this to a human teammate so they can take it forward."
logger = logging.getLogger("nazar.simulator")

SIMULATOR_SCENARIOS = {
    "new_lead": {
        "display_name": "New inbound lead",
        "default_message": "Hi, I’m exploring rooftop solar for my home and want to understand pricing and savings.",
        "pipeline_stage": "New",
        "source_type": "direct_inbound",
        "source_ref": None,
        "explicit_policy_key": None,
    },
    "pricing_question": {
        "display_name": "Pricing negotiation",
        "default_message": "Can you send a quote for a 5kW rooftop solar setup and let me know if there is any subsidy or discount?",
        "pipeline_stage": "Negotiation",
        "source_type": "direct_inbound",
        "source_ref": None,
        "explicit_policy_key": None,
    },
    "support_escalation": {
        "display_name": "Support escalation",
        "default_message": "I need help urgently and want to speak with a human about my issue.",
        "pipeline_stage": "Qualified",
        "source_type": "conversation_override",
        "source_ref": "support_escalation",
        "explicit_policy_key": "support_escalation",
    },
    "campaign_reply": {
        "display_name": "Campaign reply",
        "default_message": "I saw your free solar savings audit campaign. Can someone share the details and next steps?",
        "pipeline_stage": "Qualified",
        "source_type": "campaign",
        "source_ref": "broadcast_reply",
        "explicit_policy_key": None,
    },
    "ai_assist": {
        "display_name": "Human queue with AI draft",
        "default_message": "Can someone explain financing options, installation timeline, and how net metering works before I decide?",
        "pipeline_stage": "Qualified",
        "source_type": "conversation_override",
        "source_ref": "demo_ai_assist",
        "explicit_policy_key": "demo_ai_assist",
    },
}

_SAMPLE_CONTACTS = [
    ("Aarav Mehta", "Nova Retail"),
    ("Maya Reddy", "BluePeak Labs"),
    ("Rohan Shah", "Orbit Health"),
    ("Anika Iyer", "Atlas Motors"),
    ("Kabir Sethi", "LimeCart"),
    ("Diya Nair", "CloudMint"),
    ("Ishaan Verma", "PulseWorks"),
    ("Sara Khan", "BrightNest"),
    ("Neel Jain", "FleetPilot"),
    ("Tara Menon", "EchoGrid"),
]

_CAMPAIGN_REPLY_MESSAGES = [
    "This looks useful. Can you share estimated pricing for my roof size?",
    "Can someone explain how subsidy and financing work?",
    "I want to book a free site survey this week.",
    "Who from your team can help me evaluate savings for my building?",
    "Interested. Can you tell me the expected monthly bill reduction?",
]


def _ensure_demo_policy() -> None:
    upsert_reply_policy(
        "demo_ai_assist",
        {
            "display_name": "Demo AI Assist",
            "description": "Routes the conversation to a human queue with an AI draft ready to review.",
            "reply_mode": "bot_assist",
            "fallback_queue": "sales",
            "force_human_keywords": [],
            "active": True,
        },
    )


def _fake_phone(index_hint: int = 0) -> str:
    seed = uuid.uuid4().int % 1000000
    return f"+1555{(index_hint % 1000):03d}{seed:06d}"[:13]


def _fake_wa_id(prefix: str) -> str:
    return f"sim_{prefix}_{uuid.uuid4().hex[:14]}"


def _default_name(index_hint: int = 0) -> tuple[str, str]:
    name, company = _SAMPLE_CONTACTS[index_hint % len(_SAMPLE_CONTACTS)]
    return name, company


def _ensure_stage(contact_id: str, pipeline_stage: Optional[str]) -> dict:
    if pipeline_stage and pipeline_stage in PIPELINE_STAGES:
        return update_contact(contact_id, pipeline_stage=pipeline_stage)
    return get_contact(contact_id)


def _ensure_contact(
    *,
    contact_id: Optional[str] = None,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    company: Optional[str] = None,
    pipeline_stage: Optional[str] = None,
    source: str = "simulator",
    index_hint: int = 0,
) -> dict:
    if contact_id:
        existing = get_contact(contact_id)
        if existing:
            if pipeline_stage or company:
                updates = {}
                if pipeline_stage:
                    updates["pipeline_stage"] = pipeline_stage
                if company:
                    updates["company"] = company
                existing = update_contact(contact_id, **updates)
            return existing

    lookup_phone = (phone or "").strip()
    if lookup_phone:
        existing = get_contact_by_phone(lookup_phone)
        if existing:
            updates = {}
            if pipeline_stage and existing.get("pipeline_stage") != pipeline_stage:
                updates["pipeline_stage"] = pipeline_stage
            if company and existing.get("company") != company:
                updates["company"] = company
            if updates:
                existing = update_contact(existing["contact_id"], **updates)
            return existing

    fallback_name, fallback_company = _default_name(index_hint)
    created = create_contact(
        name=(name or fallback_name).strip(),
        phone=lookup_phone or _fake_phone(index_hint),
        company=(company or fallback_company).strip(),
        source=source,
        tags=["simulated"],
    )
    return _ensure_stage(created["contact_id"], pipeline_stage)


def _conversation_routing(
    contact: dict,
    conversation: dict,
    *,
    source_type: Optional[str] = None,
    source_ref: Optional[str] = None,
    explicit_policy_key: Optional[str] = None,
    ownership_recommendation: Optional[str] = None,
) -> tuple[dict, dict]:
    active_source_type = source_type if source_type is not None else (conversation.get("source_type") or "direct_inbound")
    active_source_ref = source_ref if source_ref is not None else conversation.get("source_ref")
    explicit = explicit_policy_key
    if explicit is None and active_source_type == "conversation_override":
        explicit = conversation.get("use_case_key")
    routing = resolve_policy_for_context(
        pipeline_stage=contact.get("pipeline_stage"),
        campaign_key=active_source_ref if active_source_type == "campaign" else None,
        explicit_policy_key=explicit,
    )
    routing = apply_ai_ownership_recommendation(routing, ownership_recommendation)
    updated = set_conversation_use_case(
        conversation["conversation_id"],
        routing["policy"]["use_case_key"],
        source_type=active_source_type,
        source_ref=active_source_ref,
        active_reply_policy_key=routing["policy"]["use_case_key"],
        human_queue=routing["policy"].get("fallback_queue"),
    )
    return updated, routing


def _simulated_bot_reply(contact: dict, inbound_message: str, policy: dict) -> str:
    config = get_workspace_config()
    business_name = config.get("business_name") or "our team"
    first_name = (contact.get("name") or "there").split(" ")[0]
    short_msg = (inbound_message or "").strip()
    if len(short_msg) > 96:
        short_msg = short_msg[:93] + "..."
    if policy.get("use_case_key") == "broadcast_reply":
        return (
            f"Hi {first_name}, thanks for replying to the campaign from {business_name}. "
            f"We can help you estimate rooftop solar savings, suggest the right system size, and arrange a free site survey. "
            f"If helpful, I can also route this to a human advisor."
        )
    return (
        f"Hi {first_name}, thanks for reaching out. "
        f"I picked up your message: \"{short_msg}\". "
        f"{business_name} can help with rooftop solar sizing, subsidy guidance, financing options, and installation planning."
    )


def _simulated_ai_draft(contact: dict, inbound_message: str) -> str:
    config = get_workspace_config()
    business_name = config.get("business_name") or "our team"
    first_name = (contact.get("name") or "there").split(" ")[0]
    short_msg = (inbound_message or "").strip()
    if len(short_msg) > 110:
        short_msg = short_msg[:107] + "..."
    return (
        f"Hi {first_name}, thanks for the context. "
        f"Based on your message about \"{short_msg}\", I'd suggest we walk you through roof suitability, expected savings, financing, and installation timeline from {business_name}. "
        f"Would a 15-minute consultation later today work?"
    )


async def _generate_ai_text(contact: dict, inbound_message: str, *, fallback_builder) -> str:
    config = get_workspace_config()
    try:
        return await generate_reply_for_contact(
            contact["contact_id"],
            inbound_message,
            lambda messages: call_llm_safe(messages, tier="sonnet", phone=contact.get("phone", "")),
            config=config,
            include_current_message=False,
        )
    except Exception as exc:
        logger.warning("Simulator AI generation failed, using fallback copy: %s", exc)
        return fallback_builder(contact, inbound_message)


async def simulate_inbound_event_async(
    *,
    scenario_key: str = "new_lead",
    message: Optional[str] = None,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    company: Optional[str] = None,
    pipeline_stage: Optional[str] = None,
    source_type: Optional[str] = None,
    source_ref: Optional[str] = None,
    explicit_policy_key: Optional[str] = None,
    contact_id: Optional[str] = None,
    index_hint: int = 0,
) -> dict:
    _ensure_demo_policy()
    scenario = SIMULATOR_SCENARIOS.get(scenario_key, SIMULATOR_SCENARIOS["new_lead"])
    selected_stage = pipeline_stage or scenario.get("pipeline_stage") or "New"
    contact = _ensure_contact(
        contact_id=contact_id,
        name=name,
        phone=phone,
        company=company,
        pipeline_stage=selected_stage,
        index_hint=index_hint,
    )
    inbound_text = (message or scenario["default_message"]).strip()
    inbound = save_message(
        contact["contact_id"],
        "inbound",
        inbound_text,
        sent_by="customer",
        wa_message_id=_fake_wa_id("in"),
    )
    classification = await classify_and_apply(contact["contact_id"], inbound_text)
    contact = classification["contact"]
    conversation = get_conversation_record(inbound["conversation_id"])
    conversation, routing = _conversation_routing(
        contact,
        conversation,
        source_type=source_type if source_type is not None else scenario.get("source_type"),
        source_ref=source_ref if source_ref is not None else scenario.get("source_ref"),
        explicit_policy_key=explicit_policy_key if explicit_policy_key is not None else scenario.get("explicit_policy_key"),
        ownership_recommendation=classification.get("ownership_recommendation"),
    )
    policy = routing["policy"]
    reply_mode = routing.get("effective_reply_mode") or policy.get("reply_mode") or "bot_first"

    result = {
        "scenario_key": scenario_key,
        "contact": contact,
        "conversation": conversation,
        "routing": routing,
        "policy": policy,
        "classification": classification,
        "inbound_message": inbound_text,
        "action": "queued_for_human",
    }

    if reply_mode == "bot_assist":
        conversation = mark_conversation_handoff_required(conversation["conversation_id"], True)
        draft = await _generate_ai_text(contact, inbound_text, fallback_builder=_simulated_ai_draft)
        conversation = set_conversation_ai_assist(conversation["conversation_id"], draft, status="available")
        result.update({
            "action": "ai_assist_ready",
            "ai_assist_draft": draft,
            "conversation": conversation,
        })
        return result

    if reply_mode in {"human_first", "manual_only"} or should_force_human(policy, inbound_text):
        conversation = mark_conversation_handoff_required(conversation["conversation_id"], True)
        outbound_message = None
        if reply_mode != "manual_only":
            outbound_message = HANDOFF_MESSAGE
            outbound = save_message(
                conversation["conversation_id"],
                "outbound",
                outbound_message,
                sent_by="bot",
                wa_message_id=_fake_wa_id("handoff"),
            )
            update_message_status_by_wa_id(outbound["wa_message_id"], "delivered", recipient=contact["phone"])
        conversation = set_conversation_status(conversation["conversation_id"], "needs_reply")
        result.update({
            "action": "human_queue",
            "outbound_message": outbound_message,
            "conversation": conversation,
        })
        return result

    bot_reply = await _generate_ai_text(
        contact,
        inbound_text,
        fallback_builder=lambda c, m: _simulated_bot_reply(c, m, policy),
    )
    outbound = save_message(
        conversation["conversation_id"],
        "outbound",
        bot_reply,
        sent_by="bot",
        wa_message_id=_fake_wa_id("bot"),
    )
    update_message_status_by_wa_id(outbound["wa_message_id"], "delivered", recipient=contact["phone"])
    conversation = get_conversation_record(conversation["conversation_id"])
    result.update({
        "action": "bot_reply_sent",
        "outbound_message": bot_reply,
        "conversation": conversation,
    })
    return result


def simulate_inbound_event(**kwargs) -> dict:
    import asyncio
    return asyncio.run(simulate_inbound_event_async(**kwargs))


def _ensure_sample_targets(target_count: int, target_stage: str) -> list[dict]:
    current = list_contacts(stage=target_stage)
    while len(current) < target_count:
        current.append(
            _ensure_contact(
                name=None,
                phone=None,
                company=None,
                pipeline_stage=target_stage,
                index_hint=len(current),
            )
        )
        current = list_contacts(stage=target_stage)
    return current[:target_count]


async def simulate_broadcast_run_async(
    *,
    message: str = "",
    template_name: str = "",
    objective: Optional[str] = None,
    target_stage: Optional[str] = None,
    target_count: int = 5,
    campaign_key: str = "simulated_campaign",
    reply_use_case_key: Optional[str] = None,
    simulate_reply_count: int = 0,
) -> dict:
    _ensure_demo_policy()
    if not message and not template_name:
        raise ValueError("Campaign simulation requires message or template")
    selected_stage = target_stage if target_stage in PIPELINE_STAGES else "Qualified"
    target_count = max(1, min(int(target_count or 1), 50))
    simulate_reply_count = max(0, min(int(simulate_reply_count or 0), target_count))
    routing = resolve_policy_for_context(
        pipeline_stage=selected_stage,
        campaign_key=campaign_key,
        explicit_policy_key=reply_use_case_key,
    )
    policy = routing["policy"]
    targets = _ensure_sample_targets(target_count, selected_stage)
    template = get_template_by_name(template_name) if template_name else None
    if template_name and not template:
        raise ValueError(f"Template '{template_name}' not found")

    details = []
    for idx, contact in enumerate(targets):
        personalized = render_template(template, contact) if template else personalize_message(message, contact)
        outbound = save_message(
            contact["contact_id"],
            "outbound",
            personalized,
            sent_by="broadcast",
            wa_message_id=_fake_wa_id("broadcast"),
        )
        update_message_status_by_wa_id(outbound["wa_message_id"], "delivered", recipient=contact["phone"])
        set_conversation_use_case(
            outbound["conversation_id"],
            policy["use_case_key"],
            source_type="campaign",
            source_ref=campaign_key,
            active_reply_policy_key=policy["use_case_key"],
            human_queue=policy.get("fallback_queue"),
        )
        details.append(
            {
                "contact_id": contact["contact_id"],
                "conversation_id": outbound["conversation_id"],
                "name": contact.get("name"),
                "phone": contact.get("phone"),
                "message": personalized,
                "status": "sent",
            }
        )

    broadcast_record = log_broadcast(
        message=message,
        template_name=template_name,
        objective=objective,
        target_count=len(targets),
        sent=len(targets),
        failed=0,
        filter_stage=selected_stage,
        filter_tag="simulated",
        campaign_key=campaign_key,
    )

    replies = []
    for idx, target in enumerate(targets[:simulate_reply_count]):
        reply_message = _CAMPAIGN_REPLY_MESSAGES[idx % len(_CAMPAIGN_REPLY_MESSAGES)]
        replies.append(
            await simulate_inbound_event_async(
                scenario_key="campaign_reply",
                message=reply_message,
                contact_id=target["contact_id"],
                pipeline_stage=selected_stage,
                source_type="campaign",
                source_ref=campaign_key,
                explicit_policy_key=reply_use_case_key,
                index_hint=idx,
            )
        )

    return {
        "campaign_key": campaign_key,
        "policy": policy,
        "routing": routing,
        "target_stage": selected_stage,
        "target_count": len(targets),
        "simulate_reply_count": simulate_reply_count,
        "broadcast": broadcast_record,
        "details": details,
        "reply_results": replies,
        "content_source": "template" if template else "custom",
    }


def simulate_broadcast_run(**kwargs) -> dict:
    import asyncio
    return asyncio.run(simulate_broadcast_run_async(**kwargs))
