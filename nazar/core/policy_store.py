"""
Reply ownership policies by use case.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from db import ReplyPolicy, RoutingRule, Workspace, default_workspace_slug, init_db, session_scope

IST = timezone(timedelta(hours=5, minutes=30))
VALID_REPLY_MODES = {"bot_first", "human_first", "manual_only", "bot_assist"}
VALID_SCOPE_TYPES = {"default", "campaign", "pipeline_stage"}

DEFAULT_REPLY_POLICIES = [
    {
        "use_case_key": "default_inbound",
        "display_name": "General Inbound",
        "description": "Default policy for normal inbound WhatsApp leads and conversations.",
        "reply_mode": "bot_first",
        "fallback_queue": "sales",
        "force_human_keywords": ["human", "agent", "manager", "complaint", "refund"],
    },
    {
        "use_case_key": "broadcast_reply",
        "display_name": "Broadcast Replies",
        "description": "Replies that come from campaigns and broadcast sends.",
        "reply_mode": "bot_first",
        "fallback_queue": "campaigns",
        "force_human_keywords": ["unsubscribe", "refund", "complaint", "manager"],
    },
    {
        "use_case_key": "pricing_negotiation",
        "display_name": "Pricing Negotiation",
        "description": "Conversations where pricing, deals, or negotiation need a human owner.",
        "reply_mode": "human_first",
        "fallback_queue": "sales",
        "force_human_keywords": ["discount", "quote", "pricing", "budget"],
    },
    {
        "use_case_key": "support_escalation",
        "display_name": "Support Escalation",
        "description": "Escalations, complaints, or sensitive issues that should go to humans first.",
        "reply_mode": "manual_only",
        "fallback_queue": "support",
        "force_human_keywords": ["complaint", "refund", "legal", "cancel", "angry"],
    },
]

DEFAULT_ROUTING_RULES = [
    {
        "scope_type": "default",
        "scope_key": "default",
        "display_name": "Default Inbound",
        "policy_use_case_key": "default_inbound",
    },
    {
        "scope_type": "pipeline_stage",
        "scope_key": "Negotiation",
        "display_name": "Negotiation Stage",
        "policy_use_case_key": "pricing_negotiation",
    },
    {
        "scope_type": "pipeline_stage",
        "scope_key": "Proposal",
        "display_name": "Proposal Stage",
        "policy_use_case_key": "pricing_negotiation",
    },
    {
        "scope_type": "campaign",
        "scope_key": "broadcast_reply",
        "display_name": "Broadcast Campaign Replies",
        "policy_use_case_key": "broadcast_reply",
    },
]


def _now() -> datetime:
    return datetime.now(IST)


def _workspace(session) -> Workspace:
    workspace = session.execute(
        select(Workspace).where(Workspace.slug == default_workspace_slug())
    ).scalar_one_or_none()
    if workspace is None:
        workspace = session.execute(select(Workspace)).scalar_one()
    return workspace


def _serialize(record: ReplyPolicy) -> dict:
    return {
        "id": record.id,
        "use_case_key": record.use_case_key,
        "display_name": record.display_name,
        "description": record.description or "",
        "reply_mode": record.reply_mode,
        "fallback_queue": record.fallback_queue,
        "force_human_keywords": json.loads(record.force_human_keywords_json or "[]"),
        "active": bool(record.active),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _serialize_routing_rule(record: RoutingRule) -> dict:
    return {
        "id": record.id,
        "scope_type": record.scope_type,
        "scope_key": record.scope_key,
        "display_name": record.display_name,
        "policy_use_case_key": record.policy_use_case_key,
        "active": bool(record.active),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _normalize_mode(reply_mode: Optional[str]) -> str:
    mode = (reply_mode or "bot_first").strip().lower()
    return mode if mode in VALID_REPLY_MODES else "bot_first"


def _normalize_scope_type(scope_type: Optional[str]) -> str:
    value = (scope_type or "default").strip().lower()
    return value if value in VALID_SCOPE_TYPES else "default"


def initialize_reply_policies() -> None:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session)
        existing = session.execute(
            select(ReplyPolicy).where(ReplyPolicy.workspace_id == workspace.id)
        ).scalars().all()
        existing_keys = {policy.use_case_key for policy in existing}
        for seed in DEFAULT_REPLY_POLICIES:
            if seed["use_case_key"] in existing_keys:
                continue
            session.add(
                ReplyPolicy(
                    workspace_id=workspace.id,
                    use_case_key=seed["use_case_key"],
                    display_name=seed["display_name"],
                    description=seed.get("description", ""),
                    reply_mode=_normalize_mode(seed.get("reply_mode")),
                    fallback_queue=(seed.get("fallback_queue") or "sales").strip() or "sales",
                    force_human_keywords_json=json.dumps(seed.get("force_human_keywords", []), ensure_ascii=False),
                    active=True,
                    created_at=_now(),
                    updated_at=_now(),
                )
            )

        existing_rules = session.execute(
            select(RoutingRule).where(RoutingRule.workspace_id == workspace.id)
        ).scalars().all()
        existing_rule_keys = {(rule.scope_type, rule.scope_key) for rule in existing_rules}
        for seed in DEFAULT_ROUTING_RULES:
            key = (seed["scope_type"], seed["scope_key"])
            if key in existing_rule_keys:
                continue
            session.add(
                RoutingRule(
                    workspace_id=workspace.id,
                    scope_type=_normalize_scope_type(seed["scope_type"]),
                    scope_key=seed["scope_key"],
                    display_name=seed["display_name"],
                    policy_use_case_key=seed["policy_use_case_key"],
                    active=True,
                    created_at=_now(),
                    updated_at=_now(),
                )
            )


def list_reply_policies() -> list[dict]:
    initialize_reply_policies()
    with session_scope() as session:
        workspace = _workspace(session)
        policies = session.execute(
            select(ReplyPolicy)
            .where(ReplyPolicy.workspace_id == workspace.id)
            .order_by(ReplyPolicy.display_name.asc(), ReplyPolicy.use_case_key.asc())
        ).scalars().all()
        return [_serialize(policy) for policy in policies]


def get_reply_policy(use_case_key: str) -> Optional[dict]:
    initialize_reply_policies()
    with session_scope() as session:
        workspace = _workspace(session)
        policy = session.execute(
            select(ReplyPolicy).where(
                ReplyPolicy.workspace_id == workspace.id,
                ReplyPolicy.use_case_key == use_case_key,
            )
        ).scalar_one_or_none()
        return _serialize(policy) if policy else None


def upsert_reply_policy(use_case_key: str, updates: dict) -> dict:
    initialize_reply_policies()
    normalized_key = (use_case_key or "").strip() or "default_inbound"
    with session_scope() as session:
        workspace = _workspace(session)
        policy = session.execute(
            select(ReplyPolicy).where(
                ReplyPolicy.workspace_id == workspace.id,
                ReplyPolicy.use_case_key == normalized_key,
            )
        ).scalar_one_or_none()
        if policy is None:
            policy = ReplyPolicy(
                workspace_id=workspace.id,
                use_case_key=normalized_key,
                display_name=updates.get("display_name") or normalized_key.replace("_", " ").title(),
                description=updates.get("description") or "",
                reply_mode=_normalize_mode(updates.get("reply_mode")),
                fallback_queue=(updates.get("fallback_queue") or "sales").strip() or "sales",
                force_human_keywords_json=json.dumps(updates.get("force_human_keywords") or [], ensure_ascii=False),
                active=bool(updates.get("active", True)),
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(policy)
        else:
            if "display_name" in updates:
                policy.display_name = updates.get("display_name") or policy.display_name
            if "description" in updates:
                policy.description = updates.get("description") or ""
            if "reply_mode" in updates:
                policy.reply_mode = _normalize_mode(updates.get("reply_mode"))
            if "fallback_queue" in updates:
                policy.fallback_queue = (updates.get("fallback_queue") or "sales").strip() or "sales"
            if "force_human_keywords" in updates:
                keywords = [str(item).strip().lower() for item in (updates.get("force_human_keywords") or []) if str(item).strip()]
                policy.force_human_keywords_json = json.dumps(sorted(set(keywords)), ensure_ascii=False)
            if "active" in updates:
                policy.active = bool(updates.get("active"))
            policy.updated_at = _now()
        session.flush()
        return _serialize(policy)


def resolve_reply_policy(use_case_key: Optional[str]) -> dict:
    requested_key = (use_case_key or "").strip() or "default_inbound"
    policy = get_reply_policy(requested_key)
    if policy and policy.get("active", True):
        return policy
    fallback = get_reply_policy("default_inbound")
    return fallback or {
        "use_case_key": "default_inbound",
        "display_name": "General Inbound",
        "description": "",
        "reply_mode": "bot_first",
        "fallback_queue": "sales",
        "force_human_keywords": ["human", "agent"],
        "active": True,
    }


def list_routing_rules(scope_type: Optional[str] = None) -> list[dict]:
    initialize_reply_policies()
    with session_scope() as session:
        workspace = _workspace(session)
        query = select(RoutingRule).where(RoutingRule.workspace_id == workspace.id)
        if scope_type:
            query = query.where(RoutingRule.scope_type == _normalize_scope_type(scope_type))
        rules = session.execute(
            query.order_by(RoutingRule.scope_type.asc(), RoutingRule.display_name.asc(), RoutingRule.scope_key.asc())
        ).scalars().all()
        return [_serialize_routing_rule(rule) for rule in rules]


def get_routing_rule(scope_type: str, scope_key: str) -> Optional[dict]:
    initialize_reply_policies()
    with session_scope() as session:
        workspace = _workspace(session)
        rule = session.execute(
            select(RoutingRule).where(
                RoutingRule.workspace_id == workspace.id,
                RoutingRule.scope_type == _normalize_scope_type(scope_type),
                RoutingRule.scope_key == scope_key,
            )
        ).scalar_one_or_none()
        return _serialize_routing_rule(rule) if rule else None


def upsert_routing_rule(scope_type: str, scope_key: str, updates: dict) -> dict:
    initialize_reply_policies()
    normalized_scope_type = _normalize_scope_type(scope_type)
    normalized_scope_key = (scope_key or "").strip() or "default"
    with session_scope() as session:
        workspace = _workspace(session)
        rule = session.execute(
            select(RoutingRule).where(
                RoutingRule.workspace_id == workspace.id,
                RoutingRule.scope_type == normalized_scope_type,
                RoutingRule.scope_key == normalized_scope_key,
            )
        ).scalar_one_or_none()
        if rule is None:
            rule = RoutingRule(
                workspace_id=workspace.id,
                scope_type=normalized_scope_type,
                scope_key=normalized_scope_key,
                display_name=updates.get("display_name") or normalized_scope_key,
                policy_use_case_key=updates.get("policy_use_case_key") or "default_inbound",
                active=bool(updates.get("active", True)),
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(rule)
        else:
            if "display_name" in updates:
                rule.display_name = updates.get("display_name") or rule.display_name
            if "policy_use_case_key" in updates:
                rule.policy_use_case_key = updates.get("policy_use_case_key") or rule.policy_use_case_key
            if "active" in updates:
                rule.active = bool(updates.get("active"))
            rule.updated_at = _now()
        session.flush()
        return _serialize_routing_rule(rule)


def resolve_policy_for_context(
    pipeline_stage: Optional[str] = None,
    campaign_key: Optional[str] = None,
    explicit_policy_key: Optional[str] = None,
) -> dict:
    if explicit_policy_key:
        policy = resolve_reply_policy(explicit_policy_key)
        return {"policy": policy, "scope_type": "conversation", "scope_key": explicit_policy_key}

    if campaign_key:
        campaign_rule = get_routing_rule("campaign", campaign_key)
        if campaign_rule and campaign_rule.get("active", True):
            policy = resolve_reply_policy(campaign_rule["policy_use_case_key"])
            return {"policy": policy, "scope_type": "campaign", "scope_key": campaign_key}

    if pipeline_stage:
        stage_rule = get_routing_rule("pipeline_stage", pipeline_stage)
        if stage_rule and stage_rule.get("active", True):
            policy = resolve_reply_policy(stage_rule["policy_use_case_key"])
            return {"policy": policy, "scope_type": "pipeline_stage", "scope_key": pipeline_stage}

    default_rule = get_routing_rule("default", "default")
    if default_rule and default_rule.get("active", True):
        policy = resolve_reply_policy(default_rule["policy_use_case_key"])
        return {"policy": policy, "scope_type": "default", "scope_key": "default"}

    fallback_policy = resolve_reply_policy("default_inbound")
    return {"policy": fallback_policy, "scope_type": "default", "scope_key": "default"}


def apply_ai_ownership_recommendation(routing: dict, ownership_recommendation: Optional[str]) -> dict:
    recommendation = _normalize_mode(ownership_recommendation)
    if not recommendation:
        return routing
    if (routing.get("scope_type") or "default") != "default":
        return routing
    policy = dict(routing.get("policy") or {})
    if not policy:
        return routing
    if _normalize_mode(policy.get("reply_mode")) == recommendation:
        return routing
    policy["reply_mode"] = recommendation
    policy["ownership_source"] = "ai_classifier"
    return {
        **routing,
        "policy": policy,
        "effective_reply_mode": recommendation,
        "reply_mode_source": "ai_classifier",
    }


def should_force_human(policy: dict, message: str) -> bool:
    text = (message or "").lower()
    keywords = [str(item).lower() for item in (policy.get("force_human_keywords") or [])]
    return any(keyword and keyword in text for keyword in keywords)
