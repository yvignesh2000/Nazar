"""
Workspace auth, invite, and session storage.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from db import (
    AuthMagicLink,
    Conversation,
    User,
    UserSession,
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
    WorkspaceOnboardingState,
    default_workspace_slug,
    init_db,
    session_scope,
)
from mailer import send_magic_link_email, send_workspace_invite_email

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_TTL_DAYS = 14
MAGIC_LINK_TTL_MINUTES = 30
INVITE_TTL_DAYS = 7
ROLE_LEVEL = {"sales_rep": 1, "sales_lead": 2, "owner": 3}
LEGACY_ROLE_MAP = {"agent": "sales_rep", "admin": "sales_lead", "owner": "owner"}
ROLE_LABELS = {"owner": "Owner", "sales_lead": "Sales Lead", "sales_rep": "Sales Rep"}


def _with_tz(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=IST)


def _now() -> datetime:
    return datetime.now(IST)


def _workspace(session, workspace_slug: Optional[str] = None) -> Workspace:
    slug = (workspace_slug or default_workspace_slug()).strip() or default_workspace_slug()
    workspace = session.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none()
    if workspace is None:
        workspace = session.execute(select(Workspace)).scalar_one()
    return workspace


def normalize_role(role: Optional[str], fallback: str = "sales_rep") -> str:
    normalized = (role or fallback).strip().lower().replace(" ", "_")
    normalized = LEGACY_ROLE_MAP.get(normalized, normalized)
    return normalized if normalized in ROLE_LEVEL else fallback


def role_label(role: Optional[str]) -> str:
    return ROLE_LABELS.get(normalize_role(role), "Sales Rep")


def _membership(session, workspace_id: str, user_id: str) -> Optional[WorkspaceMembership]:
    membership = session.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    ).scalar_one_or_none()
    if membership and membership.role in LEGACY_ROLE_MAP:
        membership.role = normalize_role(membership.role)
    return membership


def _serialize_workspace(workspace: Workspace) -> dict:
    return {
        "id": workspace.id,
        "slug": workspace.slug,
        "name": workspace.name,
    }


def _serialize_user(user: User, membership: WorkspaceMembership) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": normalize_role(membership.role),
        "role_label": role_label(membership.role),
        "status": membership.status,
    }


def _serialize_session(session_row: Optional[UserSession], user: User, workspace: Workspace, membership: WorkspaceMembership) -> dict:
    return {
        "token": session_row.token if session_row else None,
        "expires_at": session_row.expires_at.isoformat() if session_row else None,
        "user": _serialize_user(user, membership),
        "workspace": _serialize_workspace(workspace),
    }


def role_allowed(actual_role: str, allowed_roles: set[str]) -> bool:
    actual = normalize_role(actual_role)
    normalized_allowed = {normalize_role(role) for role in allowed_roles}
    return ROLE_LEVEL.get(actual, 0) >= min(ROLE_LEVEL.get(role, 0) for role in normalized_allowed)


def _create_user_session(session, workspace: Workspace, user: User, membership: WorkspaceMembership) -> dict:
    expires_at = _now() + timedelta(days=SESSION_TTL_DAYS)
    session_row = UserSession(
        workspace_id=workspace.id,
        user_id=user.id,
        token=secrets.token_urlsafe(32),
        expires_at=expires_at,
    )
    session.add(session_row)
    session.flush()
    return _serialize_session(session_row, user, workspace, membership)


def _find_user_by_email(session, email: str) -> Optional[User]:
    return session.execute(select(User).where(User.email == email)).scalar_one_or_none()


def _ensure_workspace_onboarding(session, workspace_id: str) -> WorkspaceOnboardingState:
    onboarding = session.execute(
        select(WorkspaceOnboardingState).where(WorkspaceOnboardingState.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if onboarding is None:
        onboarding = WorkspaceOnboardingState(workspace_id=workspace_id)
        session.add(onboarding)
        session.flush()
    return onboarding


def _ensure_membership(session, workspace: Workspace, user: User, role: str, status: str = "active") -> WorkspaceMembership:
    membership = _membership(session, workspace.id, user.id)
    if membership is None:
        membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=user.id,
            role=normalize_role(role),
            status=status,
        )
        session.add(membership)
        session.flush()
    else:
        membership.role = normalize_role(role, membership.role)
        membership.status = status or membership.status
    return membership


def create_session(api_key: str) -> dict:
    init_db()
    expected_api_key = os.environ.get("NAZAR_API_KEY", "nazar_dev_key")
    if api_key != expected_api_key:
        raise ValueError("Invalid API key")

    with session_scope() as session:
        workspace = _workspace(session)
        membership = session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace.id, WorkspaceMembership.status == "active")
            .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
        ).scalars().first()
        if membership is None:
            raise ValueError("No workspace membership available")
        membership.role = normalize_role(membership.role)
        user = session.execute(select(User).where(User.id == membership.user_id)).scalar_one()
        return _create_user_session(session, workspace, user, membership)


def get_default_owner_context() -> Optional[dict]:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session)
        membership = session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace.id, WorkspaceMembership.status == "active")
            .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
        ).scalars().first()
        if membership is None:
            return None
        user = session.execute(select(User).where(User.id == membership.user_id)).scalar_one_or_none()
        if user is None:
            return None
        membership.role = normalize_role(membership.role)
        return _serialize_session(None, user, workspace, membership)


def get_session(token: str) -> Optional[dict]:
    if not token:
        return None
    init_db()
    with session_scope() as session:
        session_row = session.execute(select(UserSession).where(UserSession.token == token)).scalar_one_or_none()
        if session_row is None or session_row.revoked_at is not None:
            return None
        if _with_tz(session_row.expires_at) < _now():
            return None
        user = session.execute(select(User).where(User.id == session_row.user_id)).scalar_one_or_none()
        workspace = session.execute(select(Workspace).where(Workspace.id == session_row.workspace_id)).scalar_one_or_none()
        if user is None or workspace is None:
            return None
        membership = _membership(session, workspace.id, user.id)
        if membership is None or membership.status != "active":
            return None
        return _serialize_session(session_row, user, workspace, membership)


def revoke_session(token: str) -> bool:
    if not token:
        return False
    init_db()
    with session_scope() as session:
        session_row = session.execute(select(UserSession).where(UserSession.token == token)).scalar_one_or_none()
        if session_row is None:
            return False
        session_row.revoked_at = _now()
        return True


def bootstrap_workspace_owner(*, workspace_name: str, business_type: str, timezone_name: str, owner_name: str, owner_email: str) -> dict:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session)
        onboarding = _ensure_workspace_onboarding(session, workspace.id)
        if onboarding.workspace_bootstrapped:
            raise ValueError("Workspace is already bootstrapped")
        if workspace_name.strip():
            workspace.name = workspace_name.strip()

        user = _find_user_by_email(session, owner_email.strip().lower()) if owner_email.strip() else None
        if user is None:
            user = User(name=owner_name.strip() or "Owner", email=owner_email.strip().lower() or None, status="active")
            session.add(user)
            session.flush()
        else:
            if owner_name.strip():
                user.name = owner_name.strip()
            if owner_email.strip():
                user.email = owner_email.strip().lower()
            user.status = "active"

        membership = _ensure_membership(session, workspace, user, "owner", "active")
        onboarding.workspace_bootstrapped = True
        onboarding.current_step = "channel_setup"
        onboarding.updated_at = _now()
        return _create_user_session(session, workspace, user, membership)


def _magic_link_payload(session, user: User, workspace: Workspace, *, invite_id: Optional[str] = None) -> tuple[AuthMagicLink, str]:
    token = secrets.token_urlsafe(36)
    row = AuthMagicLink(
        workspace_id=workspace.id,
        user_id=user.id,
        email=(user.email or "").strip().lower(),
        token=token,
        status="pending",
        expires_at=_now() + timedelta(minutes=MAGIC_LINK_TTL_MINUTES),
        invite_id=invite_id,
    )
    session.add(row)
    session.flush()
    app_url = os.environ.get("NAZAR_APP_URL", "http://localhost:8002").rstrip("/")
    return row, f"{app_url}/?magic_link={token}"


def request_magic_link(email: str) -> dict:
    init_db()
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        raise ValueError("email is required")

    with session_scope() as session:
        user = _find_user_by_email(session, normalized_email)
        if user is None:
            raise ValueError("No account found for this email")
        membership = session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == user.id, WorkspaceMembership.status == "active")
            .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
        ).scalars().first()
        if membership is None:
            raise ValueError("No active workspace access for this email")
        workspace = session.execute(select(Workspace).where(Workspace.id == membership.workspace_id)).scalar_one()
        link_row, magic_url = _magic_link_payload(session, user, workspace)
        send_result = send_magic_link_email(
            to_email=normalized_email,
            recipient_name=user.name,
            workspace_name=workspace.name,
            magic_url=magic_url,
        )
        return {
            "ok": True,
            "delivery": send_result,
            "dev_magic_link": magic_url if send_result.get("mode") == "dev" else None,
            "expires_at": link_row.expires_at.isoformat(),
        }


def verify_magic_link(token: str) -> dict:
    init_db()
    if not token:
        raise ValueError("token is required")
    with session_scope() as session:
        row = session.execute(select(AuthMagicLink).where(AuthMagicLink.token == token)).scalar_one_or_none()
        if row is None:
            raise ValueError("Magic link is invalid")
        if row.status != "pending" or row.used_at is not None:
            raise ValueError("Magic link has already been used")
        if _with_tz(row.expires_at) < _now():
            row.status = "expired"
            raise ValueError("Magic link has expired")
        user = session.execute(select(User).where(User.id == row.user_id)).scalar_one_or_none()
        workspace = session.execute(select(Workspace).where(Workspace.id == row.workspace_id)).scalar_one_or_none()
        if user is None or workspace is None:
            raise ValueError("Magic link is invalid")
        membership = _membership(session, workspace.id, user.id)
        if membership is None or membership.status != "active":
            raise ValueError("User no longer has active access")
        row.status = "used"
        row.used_at = _now()
        return _create_user_session(session, workspace, user, membership)


def list_workspace_invites(workspace_slug: Optional[str] = None) -> list[dict]:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session, workspace_slug)
        rows = session.execute(
            select(WorkspaceInvite)
            .where(WorkspaceInvite.workspace_id == workspace.id)
            .order_by(WorkspaceInvite.created_at.desc())
        ).scalars().all()
        return [
            {
                "id": row.id,
                "email": row.email,
                "name": row.name,
                "role": normalize_role(row.role),
                "role_label": role_label(row.role),
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
                "last_sent_at": row.last_sent_at.isoformat() if row.last_sent_at else None,
            }
            for row in rows
        ]


def create_workspace_invite(*, workspace_slug: Optional[str], email: str, name: str, role: str, invited_by_user_id: Optional[str]) -> dict:
    init_db()
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        raise ValueError("email is required")
    with session_scope() as session:
        workspace = _workspace(session, workspace_slug)
        existing = session.execute(
            select(WorkspaceInvite)
            .where(
                WorkspaceInvite.workspace_id == workspace.id,
                WorkspaceInvite.email == normalized_email,
                WorkspaceInvite.status.in_(["pending", "sent"]),
            )
            .order_by(WorkspaceInvite.created_at.desc())
        ).scalars().first()
        if existing:
            raise ValueError("A pending invite already exists for this email")

        row = WorkspaceInvite(
            workspace_id=workspace.id,
            email=normalized_email,
            name=(name or "").strip() or None,
            role=normalize_role(role),
            status="sent",
            invite_token=secrets.token_urlsafe(32),
            invited_by_user_id=invited_by_user_id,
            created_at=_now(),
            expires_at=_now() + timedelta(days=INVITE_TTL_DAYS),
            last_sent_at=_now(),
        )
        session.add(row)
        session.flush()
        app_url = os.environ.get("NAZAR_APP_URL", "http://localhost:8002").rstrip("/")
        invite_url = f"{app_url}/?invite_token={row.invite_token}"
        send_result = send_workspace_invite_email(
            to_email=normalized_email,
            recipient_name=row.name or normalized_email.split("@", 1)[0],
            workspace_name=workspace.name,
            invite_url=invite_url,
            role_label=role_label(row.role),
        )
        onboarding = _ensure_workspace_onboarding(session, workspace.id)
        onboarding.team_invited_or_skipped = True
        onboarding.current_step = "first_campaign"
        onboarding.updated_at = _now()
        return {
            "invite": {
                "id": row.id,
                "email": row.email,
                "name": row.name,
                "role": normalize_role(row.role),
                "role_label": role_label(row.role),
                "status": row.status,
                "expires_at": row.expires_at.isoformat(),
                "last_sent_at": row.last_sent_at.isoformat() if row.last_sent_at else None,
            },
            "delivery": send_result,
            "dev_invite_link": invite_url if send_result.get("mode") == "dev" else None,
        }


def resend_workspace_invite(invite_id: str) -> dict:
    init_db()
    with session_scope() as session:
        invite = session.execute(select(WorkspaceInvite).where(WorkspaceInvite.id == invite_id)).scalar_one_or_none()
        if invite is None:
            raise ValueError("Invite not found")
        if invite.revoked_at is not None or invite.status == "revoked":
            raise ValueError("Invite has been revoked")
        if invite.accepted_at is not None or invite.status == "accepted":
            raise ValueError("Invite has already been accepted")
        invite.status = "sent"
        invite.last_sent_at = _now()
        invite.expires_at = _now() + timedelta(days=INVITE_TTL_DAYS)
        workspace = session.execute(select(Workspace).where(Workspace.id == invite.workspace_id)).scalar_one()
        app_url = os.environ.get("NAZAR_APP_URL", "http://localhost:8002").rstrip("/")
        invite_url = f"{app_url}/?invite_token={invite.invite_token}"
        send_result = send_workspace_invite_email(
            to_email=invite.email,
            recipient_name=invite.name or invite.email.split("@", 1)[0],
            workspace_name=workspace.name,
            invite_url=invite_url,
            role_label=role_label(invite.role),
        )
        return {
            "ok": True,
            "delivery": send_result,
            "dev_invite_link": invite_url if send_result.get("mode") == "dev" else None,
        }


def revoke_workspace_invite(invite_id: str) -> dict:
    init_db()
    with session_scope() as session:
        invite = session.execute(select(WorkspaceInvite).where(WorkspaceInvite.id == invite_id)).scalar_one_or_none()
        if invite is None:
            raise ValueError("Invite not found")
        invite.status = "revoked"
        invite.revoked_at = _now()
        return {"ok": True}


def accept_workspace_invite(invite_token: str, *, name: Optional[str] = None) -> dict:
    init_db()
    if not invite_token:
        raise ValueError("invite token is required")
    with session_scope() as session:
        invite = session.execute(select(WorkspaceInvite).where(WorkspaceInvite.invite_token == invite_token)).scalar_one_or_none()
        if invite is None:
            raise ValueError("Invite is invalid")
        if invite.status == "revoked" or invite.revoked_at is not None:
            raise ValueError("Invite has been revoked")
        if invite.accepted_at is not None or invite.status == "accepted":
            raise ValueError("Invite has already been accepted")
        if _with_tz(invite.expires_at) < _now():
            invite.status = "expired"
            raise ValueError("Invite has expired")
        workspace = session.execute(select(Workspace).where(Workspace.id == invite.workspace_id)).scalar_one()
        user = _find_user_by_email(session, invite.email)
        if user is None:
            user = User(
                name=(name or invite.name or invite.email.split("@", 1)[0]).strip(),
                email=invite.email,
                status="active",
            )
            session.add(user)
            session.flush()
        elif name and name.strip():
            user.name = name.strip()
        user.status = "active"
        membership = _ensure_membership(session, workspace, user, invite.role, "active")
        invite.status = "accepted"
        invite.accepted_at = _now()
        invite.accepted_user_id = user.id
        link_row, magic_url = _magic_link_payload(session, user, workspace, invite_id=invite.id)
        send_result = send_magic_link_email(
            to_email=invite.email,
            recipient_name=user.name,
            workspace_name=workspace.name,
            magic_url=magic_url,
        )
        return {
            "ok": True,
            "delivery": send_result,
            "dev_magic_link": magic_url if send_result.get("mode") == "dev" else None,
            "expires_at": link_row.expires_at.isoformat(),
            "membership": _serialize_user(user, membership),
        }


def update_member_role(user_id: str, role: str, *, workspace_slug: Optional[str] = None) -> dict:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session, workspace_slug)
        membership = _membership(session, workspace.id, user_id)
        if membership is None:
            raise ValueError("Team member not found")
        if normalize_role(membership.role) == "owner":
            raise ValueError("Owner role cannot be changed")
        membership.role = normalize_role(role)
        return _serialize_user(membership.user, membership)


def deactivate_member(user_id: str, *, workspace_slug: Optional[str] = None) -> dict:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session, workspace_slug)
        membership = _membership(session, workspace.id, user_id)
        if membership is None:
            raise ValueError("Team member not found")
        if normalize_role(membership.role) == "owner":
            raise ValueError("Owner cannot be deactivated")
        membership.status = "inactive"
        membership.user.status = "inactive"
        session_rows = session.execute(select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))).scalars().all()
        for row in session_rows:
            row.revoked_at = _now()
        assigned = session.execute(
            select(Conversation).where(
                Conversation.workspace_id == workspace.id,
                Conversation.assigned_user_id == user_id,
            )
        ).scalars().all()
        for conversation in assigned:
            conversation.assigned_user_id = None
        return _serialize_user(membership.user, membership)
