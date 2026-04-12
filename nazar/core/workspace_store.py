"""
Workspace-scoped configuration and membership storage.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from db import (
    User,
    Workspace,
    WorkspaceConfigEntry,
    WorkspaceMembership,
    WorkspaceOnboardingState,
    default_workspace_slug,
    init_db,
    session_scope,
)
from auth_store import normalize_role, role_label

logger = logging.getLogger("nazar")

IST = timezone(timedelta(hours=5, minutes=30))
LEGACY_CONFIG_PATH = Path(__file__).parent.parent / "data" / "config.json"
VALID_ROLES = {"owner", "sales_lead", "sales_rep"}

DEFAULT_WORKSPACE_CONFIG = {
    "business_name": "SunMitra Solar Demo",
    "bot_enabled": True,
    "bot_persona": "professional",
    "welcome_message": "Hi! Welcome to SunMitra Solar. I can help you estimate savings, understand rooftop solar options, and book a consultation.",
    "handoff_message": "I’ll connect you with a solar advisor who can help with pricing, survey planning, or project-specific questions.",
    "memory_enabled": True,
    "signal_detection": True,
    "auto_lead_scoring": True,
    "smart_handoff": True,
}

_initialized = False


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _workspace(session) -> Workspace:
    workspace = session.execute(
        select(Workspace).where(Workspace.slug == default_workspace_slug())
    ).scalar_one_or_none()
    if workspace is None:
        workspace = session.execute(select(Workspace)).scalar_one()
    return workspace


def _normalize_role(role: Optional[str]) -> str:
    normalized = normalize_role(role, "sales_rep")
    return normalized if normalized in VALID_ROLES else "sales_rep"


def _serialize_membership(membership: WorkspaceMembership) -> dict:
    user = membership.user
    return {
        "id": user.id,
        "membership_id": membership.id,
        "name": user.name,
        "email": user.email,
        "role": _normalize_role(membership.role),
        "role_label": role_label(membership.role),
        "status": membership.status,
        "created_at": user.created_at.isoformat() if user.created_at else _now_iso(),
    }


def _load_legacy_config() -> dict:
    if not LEGACY_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Failed to load legacy config: {exc}")
        return {}


def _memberships(session, workspace_id: str) -> list[WorkspaceMembership]:
    return session.execute(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    ).scalars().all()


def initialize_workspace_store() -> None:
    global _initialized
    if _initialized:
        return
    init_db()

    legacy = _load_legacy_config()
    with session_scope() as session:
        workspace = _workspace(session)
        existing_entries = session.execute(
            select(WorkspaceConfigEntry).where(WorkspaceConfigEntry.workspace_id == workspace.id)
        ).scalars().all()
        if not existing_entries:
            seed = DEFAULT_WORKSPACE_CONFIG.copy()
            for key, value in legacy.items():
                if key != "team" and key in DEFAULT_WORKSPACE_CONFIG:
                    seed[key] = value
            for key, value in seed.items():
                session.add(
                    WorkspaceConfigEntry(
                        workspace_id=workspace.id,
                        key=key,
                        value_json=json.dumps(value, ensure_ascii=False),
                    )
                )

        existing_memberships = _memberships(session, workspace.id)
        if len(existing_memberships) <= 1 and legacy.get("team"):
            existing_names = {membership.user.name for membership in existing_memberships}
            for member in legacy.get("team", []):
                member_name = (member.get("name") or "").strip()
                if not member_name or member_name in existing_names:
                    continue
                user = User(
                    name=member_name,
                    email=member.get("email"),
                    status=member.get("status") or "active",
                )
                session.add(user)
                session.flush()
                session.add(
                    WorkspaceMembership(
                        workspace_id=workspace.id,
                        user_id=user.id,
                        role=_normalize_role(member.get("role")),
                        status=member.get("status") or "active",
                    )
                )
    _initialized = True


def get_workspace_config() -> dict:
    initialize_workspace_store()
    with session_scope() as session:
        workspace = _workspace(session)
        result = DEFAULT_WORKSPACE_CONFIG.copy()
        entries = session.execute(
            select(WorkspaceConfigEntry).where(WorkspaceConfigEntry.workspace_id == workspace.id)
        ).scalars().all()
        for entry in entries:
            result[entry.key] = json.loads(entry.value_json)
        result["team"] = list_team_members()
        return result


def update_workspace_config(updates: dict) -> dict:
    initialize_workspace_store()
    team_updates = updates.pop("team", None)

    with session_scope() as session:
        workspace = _workspace(session)
        for key, value in updates.items():
            entry = session.execute(
                select(WorkspaceConfigEntry).where(
                    WorkspaceConfigEntry.workspace_id == workspace.id,
                    WorkspaceConfigEntry.key == key,
                )
            ).scalar_one_or_none()
            if entry is None:
                entry = WorkspaceConfigEntry(
                    workspace_id=workspace.id,
                    key=key,
                    value_json=json.dumps(value, ensure_ascii=False),
                )
                session.add(entry)
            else:
                entry.value_json = json.dumps(value, ensure_ascii=False)
                entry.updated_at = datetime.now(IST)
        if "business_name" in updates and updates["business_name"]:
            workspace.name = str(updates["business_name"])

    if team_updates is not None:
        sync_team_members(team_updates)
    return get_workspace_config()


def list_team_members() -> list:
    initialize_workspace_store()
    with session_scope() as session:
        workspace = _workspace(session)
        memberships = _memberships(session, workspace.id)
        return [_serialize_membership(membership) for membership in memberships]


def get_onboarding_state() -> dict:
    initialize_workspace_store()
    with session_scope() as session:
        workspace = _workspace(session)
        onboarding = session.execute(
            select(WorkspaceOnboardingState).where(WorkspaceOnboardingState.workspace_id == workspace.id)
        ).scalar_one_or_none()
        if onboarding is None:
            onboarding = WorkspaceOnboardingState(workspace_id=workspace.id)
            session.add(onboarding)
            session.flush()
        return {
            "workspace_bootstrapped": onboarding.workspace_bootstrapped,
            "channel_connected": onboarding.channel_connected,
            "knowledge_ready": onboarding.knowledge_ready,
            "team_invited_or_skipped": onboarding.team_invited_or_skipped,
            "first_campaign_ready": onboarding.first_campaign_ready,
            "team_setup_skipped": onboarding.team_setup_skipped,
            "current_step": onboarding.current_step,
            "completed_at": onboarding.completed_at.isoformat() if onboarding.completed_at else None,
        }


def update_onboarding_state(updates: dict) -> dict:
    initialize_workspace_store()
    allowed = {
        "workspace_bootstrapped",
        "channel_connected",
        "knowledge_ready",
        "team_invited_or_skipped",
        "first_campaign_ready",
        "team_setup_skipped",
        "current_step",
    }
    with session_scope() as session:
        workspace = _workspace(session)
        onboarding = session.execute(
            select(WorkspaceOnboardingState).where(WorkspaceOnboardingState.workspace_id == workspace.id)
        ).scalar_one_or_none()
        if onboarding is None:
            onboarding = WorkspaceOnboardingState(workspace_id=workspace.id)
            session.add(onboarding)
            session.flush()
        for key, value in updates.items():
            if key in allowed:
                setattr(onboarding, key, value)
        onboarding.updated_at = datetime.now(IST)
        if (
            onboarding.workspace_bootstrapped
            and onboarding.channel_connected
            and onboarding.knowledge_ready
            and onboarding.team_invited_or_skipped
            and onboarding.first_campaign_ready
        ):
            onboarding.completed_at = datetime.now(IST)
            onboarding.current_step = "completed"
    return get_onboarding_state()


def get_membership_by_user_id(user_id: str, workspace_slug: Optional[str] = None) -> Optional[dict]:
    initialize_workspace_store()
    with session_scope() as session:
        if workspace_slug:
            workspace = session.execute(select(Workspace).where(Workspace.slug == workspace_slug)).scalar_one_or_none()
        else:
            workspace = _workspace(session)
        if workspace is None:
            return None
        membership = session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace.id, WorkspaceMembership.user_id == user_id)
        ).scalar_one_or_none()
        return _serialize_membership(membership) if membership else None


def sync_team_members(team_members: list) -> list:
    initialize_workspace_store()
    with session_scope() as session:
        workspace = _workspace(session)
        existing_memberships = _memberships(session, workspace.id)
        memberships_by_user_id = {membership.user_id: membership for membership in existing_memberships}
        keep_user_ids = set()

        for member in team_members or []:
            user_id = member.get("id")
            membership = memberships_by_user_id.get(user_id) if user_id else None
            if membership is None:
                name = (member.get("name") or "").strip()
                if not name:
                    continue
                user = User(
                    name=name,
                    email=member.get("email"),
                    status=member.get("status") or "active",
                )
                session.add(user)
                session.flush()
                membership = WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role=_normalize_role(member.get("role")),
                    status=member.get("status") or "active",
                )
                session.add(membership)
                session.flush()
            else:
                user = membership.user
                if member.get("name"):
                    user.name = member["name"]
                if "email" in member:
                    user.email = member.get("email")
                if member.get("status"):
                    user.status = member["status"]
                    membership.status = member["status"]
                if member.get("role"):
                    membership.role = _normalize_role(member.get("role"))
            keep_user_ids.add(membership.user_id)

        for membership in existing_memberships:
            if membership.role == "owner":
                keep_user_ids.add(membership.user_id)
                continue
            if membership.user_id not in keep_user_ids:
                session.delete(membership)

    return list_team_members()
