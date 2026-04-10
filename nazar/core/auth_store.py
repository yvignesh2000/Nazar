"""
Workspace auth and session storage.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from db import User, UserSession, Workspace, WorkspaceMembership, default_workspace_slug, init_db, session_scope

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_TTL_DAYS = 14
ROLE_LEVEL = {"agent": 1, "admin": 2, "owner": 3}


def _with_tz(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=IST)


def _workspace(session) -> Workspace:
    workspace = session.execute(
        select(Workspace).where(Workspace.slug == default_workspace_slug())
    ).scalar_one_or_none()
    if workspace is None:
        workspace = session.execute(select(Workspace)).scalar_one()
    return workspace


def _membership(session, workspace_id: str, user_id: str) -> Optional[WorkspaceMembership]:
    return session.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    ).scalar_one_or_none()


def _serialize_session(session_row: UserSession, user: User, workspace: Workspace, membership: WorkspaceMembership) -> dict:
    return {
        "token": session_row.token,
        "expires_at": session_row.expires_at.isoformat(),
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": membership.role,
            "status": membership.status,
        },
        "workspace": {
            "id": workspace.id,
            "slug": workspace.slug,
            "name": workspace.name,
        },
    }


def _serialize_identity(user: User, workspace: Workspace, membership: WorkspaceMembership) -> dict:
    return {
        "token": None,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": membership.role,
            "status": membership.status,
        },
        "workspace": {
            "id": workspace.id,
            "slug": workspace.slug,
            "name": workspace.name,
        },
    }


def role_allowed(actual_role: str, allowed_roles: set[str]) -> bool:
    return ROLE_LEVEL.get(actual_role or "agent", 0) >= min(ROLE_LEVEL.get(role, 0) for role in allowed_roles)


def create_session(api_key: str) -> dict:
    init_db()
    expected_api_key = os.environ.get("NAZAR_API_KEY", "nazar_dev_key")
    if api_key != expected_api_key:
        raise ValueError("Invalid API key")

    with session_scope() as session:
        workspace = _workspace(session)
        membership = session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace.id)
            .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
        ).scalars().first()
        if membership is None:
            raise ValueError("No workspace membership available")
        user = session.execute(select(User).where(User.id == membership.user_id)).scalar_one()

        expires_at = datetime.now(IST) + timedelta(days=SESSION_TTL_DAYS)
        session_row = UserSession(
            workspace_id=workspace.id,
            user_id=user.id,
            token=secrets.token_urlsafe(32),
            expires_at=expires_at,
        )
        session.add(session_row)
        session.flush()
        return _serialize_session(session_row, user, workspace, membership)


def get_default_owner_context() -> Optional[dict]:
    init_db()
    with session_scope() as session:
        workspace = _workspace(session)
        membership = session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace.id)
            .order_by(WorkspaceMembership.role.desc(), WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
        ).scalars().first()
        if membership is None:
            return None
        user = session.execute(select(User).where(User.id == membership.user_id)).scalar_one_or_none()
        if user is None:
            return None
        return _serialize_identity(user, workspace, membership)


def get_session(token: str) -> Optional[dict]:
    if not token:
        return None
    init_db()
    with session_scope() as session:
        session_row = session.execute(
            select(UserSession).where(UserSession.token == token)
        ).scalar_one_or_none()
        if session_row is None or session_row.revoked_at is not None:
            return None
        if _with_tz(session_row.expires_at) < datetime.now(IST):
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
        session_row = session.execute(
            select(UserSession).where(UserSession.token == token)
        ).scalar_one_or_none()
        if session_row is None:
            return False
        session_row.revoked_at = datetime.now(IST)
        return True
