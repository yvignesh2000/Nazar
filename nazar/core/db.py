"""
Nazar relational foundation.

This module holds the shared database engine, core product models, and
migration-first schema bootstrapping helpers.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


def _default_database_url() -> str:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{data_dir / 'nazar.db'}"


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip() or _default_database_url()


def get_storage_backend_name() -> str:
    database_url = get_database_url().lower()
    if "://" not in database_url:
        return "unknown"
    return database_url.split("://", 1)[0]


def _engine_kwargs() -> dict:
    kwargs = {"future": True, "pool_pre_ping": True}
    if get_storage_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
    return kwargs


ENGINE = create_engine(get_database_url(), **_engine_kwargs())
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, expire_on_commit=False)


if get_storage_backend_name() == "sqlite":
    @event.listens_for(ENGINE, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def default_workspace_slug() -> str:
    return os.environ.get("NAZAR_WORKSPACE_SLUG", "default").strip() or "default"


def default_workspace_name() -> str:
    return os.environ.get("NAZAR_WORKSPACE_NAME", "Nazar").strip() or "Nazar"


def default_owner_name() -> str:
    return os.environ.get("NAZAR_OWNER_NAME", "Admin").strip() or "Admin"


def default_owner_email() -> str:
    return os.environ.get("NAZAR_OWNER_EMAIL", "").strip() or None


def allow_schema_create() -> bool:
    return os.environ.get("NAZAR_ALLOW_SCHEMA_CREATE", "0").strip().lower() in {"1", "true", "yes"}


def schema_present() -> bool:
    return inspect(ENGINE).has_table("workspaces")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    slug = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    contacts = relationship("Contact", back_populates="workspace", cascade="all, delete-orphan")
    users = relationship("WorkspaceMembership", back_populates="workspace", cascade="all, delete-orphan")
    config_entries = relationship("WorkspaceConfigEntry", back_populates="workspace", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="workspace", cascade="all, delete-orphan")
    templates = relationship("TemplateRecord", back_populates="workspace", cascade="all, delete-orphan")
    background_jobs = relationship("BackgroundJob", back_populates="workspace", cascade="all, delete-orphan")
    reply_policies = relationship("ReplyPolicy", back_populates="workspace", cascade="all, delete-orphan")
    routing_rules = relationship("RoutingRule", back_populates="workspace", cascade="all, delete-orphan")
    invites = relationship("WorkspaceInvite", back_populates="workspace", cascade="all, delete-orphan")
    onboarding_state = relationship("WorkspaceOnboardingState", back_populates="workspace", uselist=False, cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email = Column(String(255), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    memberships = relationship("WorkspaceMembership", back_populates="user", cascade="all, delete-orphan")
    assigned_conversations = relationship("Conversation", back_populates="assigned_user")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    magic_links = relationship("AuthMagicLink", back_populates="user", cascade="all, delete-orphan")


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(32), nullable=False, default="agent", index=True)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    workspace = relationship("Workspace", back_populates="users")
    user = relationship("User", back_populates="memberships")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="sessions")


class WorkspaceInvite(Base):
    __tablename__ = "workspace_invites"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    role = Column(String(32), nullable=False, default="sales_rep", index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    invite_token = Column(String(255), unique=True, nullable=False, index=True)
    invited_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    accepted_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_sent_at = Column(DateTime(timezone=True), nullable=True)

    workspace = relationship("Workspace", back_populates="invites")


class AuthMagicLink(Base):
    __tablename__ = "auth_magic_links"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    invite_id = Column(String(36), ForeignKey("workspace_invites.id", ondelete="SET NULL"), nullable=True, index=True)

    user = relationship("User", back_populates="magic_links")


class WorkspaceOnboardingState(Base):
    __tablename__ = "workspace_onboarding_state"

    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    workspace_bootstrapped = Column(Boolean, nullable=False, default=False)
    channel_connected = Column(Boolean, nullable=False, default=False)
    knowledge_ready = Column(Boolean, nullable=False, default=False)
    team_invited_or_skipped = Column(Boolean, nullable=False, default=False)
    first_campaign_ready = Column(Boolean, nullable=False, default=False)
    team_setup_skipped = Column(Boolean, nullable=False, default=False)
    current_step = Column(String(64), nullable=False, default="workspace_basics")
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    workspace = relationship("Workspace", back_populates="onboarding_state")


class WorkspaceConfigEntry(Base):
    __tablename__ = "workspace_config_entries"
    __table_args__ = (UniqueConstraint("workspace_id", "key", name="uq_workspace_config_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(128), nullable=False)
    value_json = Column(Text, nullable=False, default="null")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    workspace = relationship("Workspace", back_populates="config_entries")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("workspace_id", "phone", name="uq_contacts_workspace_phone"),)

    id = Column(String(12), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, default="")
    phone = Column(String(32), nullable=False, index=True)
    company = Column(String(255), nullable=True)
    source = Column(String(128), nullable=True)
    assigned_to = Column(String(255), nullable=True)
    pipeline_stage = Column(String(32), nullable=False, default="New", index=True)
    deal_value = Column(Float, nullable=False, default=0.0)
    lead_score = Column(Integer, nullable=False, default=0)
    tags_json = Column(Text, nullable=False, default="[]")
    last_contacted_at = Column(DateTime(timezone=True), nullable=True)
    last_replied_at = Column(DateTime(timezone=True), nullable=True)
    total_messages = Column(Integer, nullable=False, default=0)
    opt_in = Column(Boolean, nullable=False, default=False)
    opt_in_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    notes = Column(Text, nullable=False, default="")

    workspace = relationship("Workspace", back_populates="contacts")
    messages = relationship(
        "ConversationMessage",
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.timestamp",
    )
    conversation = relationship("Conversation", back_populates="contact", uselist=False, cascade="all, delete-orphan")
    internal_notes = relationship("ContactNote", back_populates="contact", cascade="all, delete-orphan")
    memory_entries = relationship("ContactMemoryEntry", back_populates="contact", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("workspace_id", "contact_id", name="uq_conversations_workspace_contact"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(String(12), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="open", index=True)
    bot_mode = Column(Boolean, nullable=False, default=True)
    handoff_required = Column(Boolean, nullable=False, default=False)
    assigned_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    use_case_key = Column(String(64), nullable=False, default="default_inbound", index=True)
    source_type = Column(String(64), nullable=False, default="direct_inbound", index=True)
    source_ref = Column(String(64), nullable=True, index=True)
    active_reply_policy_key = Column(String(64), nullable=False, default="default_inbound", index=True)
    human_queue = Column(String(64), nullable=True, index=True)
    ai_assist_status = Column(String(32), nullable=True, index=True)
    ai_assist_draft = Column(Text, nullable=True)
    ai_assist_updated_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_message_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_inbound_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_outbound_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_message_preview = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    workspace = relationship("Workspace", back_populates="conversations")
    contact = relationship("Contact", back_populates="conversation")
    assigned_user = relationship("User", back_populates="assigned_conversations")
    messages = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.timestamp",
    )
    status_events = relationship("MessageStatusEvent", back_populates="conversation", cascade="all, delete-orphan")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(String(12), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    direction = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    sent_by = Column(String(64), nullable=False, default="bot")
    wa_message_id = Column(String(128), nullable=True, index=True)
    delivery_status = Column(String(32), nullable=True)

    contact = relationship("Contact", back_populates="messages")
    conversation = relationship("Conversation", back_populates="messages")


class MessageStatusEvent(Base):
    __tablename__ = "message_status_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    wa_message_id = Column(String(128), nullable=False, index=True)
    status = Column(String(32), nullable=False)
    recipient = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    conversation = relationship("Conversation", back_populates="status_events")


class TemplateRecord(Base):
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_templates_workspace_name"),)

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(32), nullable=False)
    body = Column(Text, nullable=False)
    variables_json = Column(Text, nullable=False, default="[]")
    language = Column(String(16), nullable=False, default="en")
    approval_status = Column(String(32), nullable=False, default="pending")
    usage_count = Column(Integer, nullable=False, default=0)
    reply_rate = Column(Float, nullable=False, default=0.0)
    description = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    workspace = relationship("Workspace", back_populates="templates")


class ReplyPolicy(Base):
    __tablename__ = "reply_policies"
    __table_args__ = (UniqueConstraint("workspace_id", "use_case_key", name="uq_reply_policy_use_case"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    use_case_key = Column(String(64), nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    reply_mode = Column(String(32), nullable=False, default="bot_first", index=True)
    fallback_queue = Column(String(64), nullable=False, default="sales")
    force_human_keywords_json = Column(Text, nullable=False, default="[]")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    workspace = relationship("Workspace", back_populates="reply_policies")


class RoutingRule(Base):
    __tablename__ = "routing_rules"
    __table_args__ = (UniqueConstraint("workspace_id", "scope_type", "scope_key", name="uq_routing_rule_scope"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    scope_type = Column(String(32), nullable=False, index=True)
    scope_key = Column(String(64), nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    policy_use_case_key = Column(String(64), nullable=False, index=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    workspace = relationship("Workspace", back_populates="routing_rules")


class ContactNote(Base):
    __tablename__ = "contact_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(String(12), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    contact = relationship("Contact", back_populates="internal_notes")


class ContactMemoryEntry(Base):
    __tablename__ = "contact_memory_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    contact_id = Column(String(12), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_type = Column(String(32), nullable=False, index=True)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    contact = relationship("Contact", back_populates="memory_entries")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    entity_type = Column(String(64), nullable=False, index=True)
    entity_id = Column(String(64), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    details_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    kind = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    payload_json = Column(Text, nullable=False, default="{}")
    result_json = Column(Text, nullable=False, default="{}")
    error_text = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    available_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    workspace = relationship("Workspace", back_populates="background_jobs")


def ensure_schema() -> None:
    if schema_present():
        return
    if allow_schema_create():
        Base.metadata.create_all(bind=ENGINE)
        return
    raise RuntimeError(
        "Database schema is missing. Run `alembic upgrade head` or set "
        "`NAZAR_ALLOW_SCHEMA_CREATE=1` for local bootstrapping."
    )


def init_db() -> None:
    ensure_schema()
    Base.metadata.create_all(bind=ENGINE)
    with session_scope() as session:
        workspace = session.query(Workspace).filter_by(slug=default_workspace_slug()).one_or_none()
        if workspace is None:
            workspace = Workspace(slug=default_workspace_slug(), name=default_workspace_name())
            session.add(workspace)
            session.flush()

        owner_user = session.query(User).filter_by(email=default_owner_email()).one_or_none() if default_owner_email() else None
        if owner_user is None:
            owner_user = session.query(User).filter_by(name=default_owner_name()).one_or_none()
        if owner_user is None:
            owner_user = User(name=default_owner_name(), email=default_owner_email(), status="active")
            session.add(owner_user)
            session.flush()

        membership = session.query(WorkspaceMembership).filter_by(
            workspace_id=workspace.id,
            user_id=owner_user.id,
        ).one_or_none()
        if membership is None:
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=owner_user.id,
                    role="owner",
                    status="active",
                )
            )
        elif membership.role in {"admin", "agent"}:
            membership.role = "owner"

        memberships = session.query(WorkspaceMembership).all()
        for item in memberships:
            if item.role == "admin":
                item.role = "sales_lead"
            elif item.role == "agent":
                item.role = "sales_rep"

        onboarding = session.query(WorkspaceOnboardingState).filter_by(workspace_id=workspace.id).one_or_none()
        if onboarding is None:
            session.add(
                WorkspaceOnboardingState(
                    workspace_id=workspace.id,
                    workspace_bootstrapped=bool(workspace.name and owner_user.email),
                )
            )


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
