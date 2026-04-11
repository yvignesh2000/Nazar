"""
Structured inbound classification for lead stage, score, and ownership.

Uses a heuristic-first classifier with optional LLM enrichment.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from contact_manager import PIPELINE_STAGES, get_contact, update_contact
from customer_memory import add_memory_note, extract_signals_from_message
from llm_router import call_llm
from workspace_store import get_workspace_config

VALID_OWNERSHIP = {"bot_first", "human_first", "bot_assist", "manual_only"}
VALID_INTENTS = {
    "general_info",
    "pricing_quote",
    "discount_negotiation",
    "site_survey_booking",
    "commercial_project",
    "support_issue",
    "complaint_escalation",
    "financing_subsidy",
    "purchase_ready",
}


def _bounded_score(value: int) -> int:
    return max(0, min(100, int(value)))


def _contains_any(text: str, phrases: list[str]) -> bool:
    lower = (text or "").lower()
    return any(phrase in lower for phrase in phrases)


def _normalize_stage(stage: Optional[str], fallback: str = "New") -> str:
    stage = (stage or fallback).strip().title()
    return stage if stage in PIPELINE_STAGES else fallback


def _normalize_ownership(value: Optional[str], fallback: str = "bot_first") -> str:
    normalized = (value or fallback).strip().lower()
    return normalized if normalized in VALID_OWNERSHIP else fallback


def _normalize_intent(value: Optional[str], fallback: str = "general_info") -> str:
    normalized = (value or fallback).strip().lower()
    return normalized if normalized in VALID_INTENTS else fallback


def _normalize_confidence(value, fallback: str = "medium") -> str:
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric >= 0.8:
            return "high"
        if numeric >= 0.45:
            return "medium"
        return "low"
    normalized = str(value or fallback).strip().lower()
    return normalized if normalized in {"low", "medium", "high"} else fallback


def heuristic_inbound_classification(contact: Optional[dict], message: str) -> dict:
    message = (message or "").strip()
    lower = message.lower()
    current_stage = (contact or {}).get("pipeline_stage") or "New"
    current_score = int((contact or {}).get("lead_score") or 0)
    signals = extract_signals_from_message(message, "inbound")
    signal_types = {sig["type"] for sig in signals}
    reasons = []

    intent = "general_info"
    suggested_stage = current_stage if current_stage in PIPELINE_STAGES else "New"
    ownership = "bot_first"

    if _contains_any(lower, ["complaint", "angry", "manager", "refund", "issue", "support", "not working"]):
        intent = "complaint_escalation" if _contains_any(lower, ["complaint", "angry", "manager", "refund"]) else "support_issue"
        suggested_stage = suggested_stage if suggested_stage not in {"New"} else "Qualified"
        ownership = "manual_only" if intent == "complaint_escalation" else "human_first"
        reasons.append("Sensitive support or escalation language detected")
    elif _contains_any(lower, ["factory", "warehouse", "school", "clinic", "apartment", "society", "commercial", "office"]):
        intent = "commercial_project"
        suggested_stage = "Qualified"
        ownership = "human_first"
        reasons.append("Commercial or larger project keywords detected")
    elif _contains_any(lower, ["discount", "quote", "pricing", "budget", "cheaper", "deal"]):
        intent = "discount_negotiation" if _contains_any(lower, ["discount", "cheaper", "deal"]) else "pricing_quote"
        suggested_stage = "Negotiation"
        ownership = "human_first"
        reasons.append("Pricing or negotiation intent detected")
    elif _contains_any(lower, ["emi", "finance", "loan", "subsidy", "net metering"]):
        intent = "financing_subsidy"
        suggested_stage = "Qualified"
        ownership = "bot_assist"
        reasons.append("Financing or subsidy questions detected")
    elif _contains_any(lower, ["site survey", "visit", "inspection", "book", "appointment", "consultation", "demo"]):
        intent = "site_survey_booking"
        suggested_stage = "Qualified"
        ownership = "bot_assist"
        reasons.append("Customer is asking for the next operational step")
    elif _contains_any(lower, ["go ahead", "proceed", "sign up", "move forward", "install", "start"]):
        intent = "purchase_ready"
        suggested_stage = "Proposal"
        ownership = "human_first"
        reasons.append("Purchase-ready language detected")
    else:
        reasons.append("General information request detected")

    delta = 0
    if "buying_signal" in signal_types:
        delta += 12
    if "intent" in signal_types:
        delta += 18
    if "price_sensitivity" in signal_types:
        delta += 6
    if "objection" in signal_types:
        delta -= 4

    if intent in {"pricing_quote", "discount_negotiation"}:
        delta += 12
    elif intent == "commercial_project":
        delta += 18
    elif intent in {"site_survey_booking", "purchase_ready"}:
        delta += 15
    elif intent in {"support_issue", "complaint_escalation"}:
        delta += 2
    else:
        delta += 6

    suggested_score = _bounded_score(max(current_score, 10) + delta)

    return {
        "intent": intent,
        "suggested_stage": _normalize_stage(suggested_stage, fallback=current_stage or "New"),
        "suggested_lead_score": suggested_score,
        "ownership_recommendation": _normalize_ownership(ownership),
        "reasons": reasons,
        "signals": signals,
        "confidence": "medium",
        "source": "heuristic",
    }


def _extract_json_block(raw: str) -> Optional[dict]:
    text = (raw or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


async def llm_inbound_classification(contact: Optional[dict], message: str, heuristic: dict) -> Optional[dict]:
    config = get_workspace_config()
    business_name = config.get("business_name") or "the business"
    prompt = {
        "contact_name": (contact or {}).get("name") or "",
        "current_stage": (contact or {}).get("pipeline_stage") or "New",
        "current_lead_score": int((contact or {}).get("lead_score") or 0),
        "message": message,
        "heuristic": {
            "intent": heuristic["intent"],
            "suggested_stage": heuristic["suggested_stage"],
            "suggested_lead_score": heuristic["suggested_lead_score"],
            "ownership_recommendation": heuristic["ownership_recommendation"],
            "reasons": heuristic["reasons"],
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                f"You classify inbound WhatsApp sales messages for {business_name}. "
                "Return strict JSON only with keys: intent, suggested_stage, suggested_lead_score, "
                "ownership_recommendation, confidence, reasons. "
                f"Valid stages: {', '.join(PIPELINE_STAGES)}. "
                "Valid ownership_recommendation: bot_first, human_first, bot_assist, manual_only. "
                "Keep reasons to 1-3 short strings."
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    try:
        raw = await call_llm(messages, tier="sonnet", timeout=20, phone=(contact or {}).get("phone", ""))
    except Exception:
        return None
    parsed = _extract_json_block(raw)
    if not parsed:
        return None
    return {
        "intent": _normalize_intent(parsed.get("intent"), heuristic["intent"]),
        "suggested_stage": _normalize_stage(parsed.get("suggested_stage"), heuristic["suggested_stage"]),
        "suggested_lead_score": _bounded_score(parsed.get("suggested_lead_score", heuristic["suggested_lead_score"])),
        "ownership_recommendation": _normalize_ownership(parsed.get("ownership_recommendation"), heuristic["ownership_recommendation"]),
        "reasons": [str(item).strip() for item in (parsed.get("reasons") or heuristic["reasons"]) if str(item).strip()],
        "confidence": _normalize_confidence(parsed.get("confidence"), heuristic["confidence"]),
        "source": "llm",
    }


async def classify_inbound_message(contact: Optional[dict], message: str) -> dict:
    heuristic = heuristic_inbound_classification(contact, message)
    llm = await llm_inbound_classification(contact, message, heuristic)
    merged = heuristic.copy()
    if llm:
        merged.update(llm)
        merged["signals"] = heuristic["signals"]
    return merged


async def classify_and_apply(contact_id: str, message: str) -> dict:
    contact = get_contact(contact_id)
    if not contact:
        raise ValueError(f"Contact {contact_id} not found")
    classification = await classify_inbound_message(contact, message)
    updates = {}
    if classification["suggested_stage"] != contact.get("pipeline_stage"):
        updates["pipeline_stage"] = classification["suggested_stage"]
    if classification["suggested_lead_score"] != contact.get("lead_score"):
        updates["lead_score"] = classification["suggested_lead_score"]
    updated_contact = update_contact(contact_id, **updates) if updates else contact
    note = (
        f"AI classification — intent: {classification['intent']}; "
        f"stage: {classification['suggested_stage']}; "
        f"lead score: {classification['suggested_lead_score']}; "
        f"owner: {classification['ownership_recommendation']}; "
        f"reasons: {', '.join(classification.get('reasons') or [])}"
    )
    add_memory_note(contact_id, note)
    classification["contact"] = updated_contact
    return classification
