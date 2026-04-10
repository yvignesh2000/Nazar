"""product foundation baseline"""

from alembic import op
import sqlalchemy as sa


revision = "0001_product_foundation_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),
    )
    op.create_index("ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"], unique=False)
    op.create_index("ix_workspace_memberships_user_id", "workspace_memberships", ["user_id"], unique=False)
    op.create_index("ix_workspace_memberships_role", "workspace_memberships", ["role"], unique=False)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_sessions_workspace_id", "user_sessions", ["workspace_id"], unique=False)
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"], unique=False)
    op.create_index("ix_user_sessions_token", "user_sessions", ["token"], unique=True)

    op.create_table(
        "workspace_config_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "key", name="uq_workspace_config_key"),
    )
    op.create_index("ix_workspace_config_entries_workspace_id", "workspace_config_entries", ["workspace_id"], unique=False)

    op.create_table(
        "contacts",
        sa.Column("id", sa.String(length=12), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("assigned_to", sa.String(length=255), nullable=True),
        sa.Column("pipeline_stage", sa.String(length=32), nullable=False),
        sa.Column("deal_value", sa.Float(), nullable=False),
        sa.Column("lead_score", sa.Integer(), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_messages", sa.Integer(), nullable=False),
        sa.Column("opt_in", sa.Boolean(), nullable=False),
        sa.Column("opt_in_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.UniqueConstraint("workspace_id", "phone", name="uq_contacts_workspace_phone"),
    )
    op.create_index("ix_contacts_workspace_id", "contacts", ["workspace_id"], unique=False)
    op.create_index("ix_contacts_phone", "contacts", ["phone"], unique=False)
    op.create_index("ix_contacts_pipeline_stage", "contacts", ["pipeline_stage"], unique=False)

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", sa.String(length=12), sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("bot_mode", sa.Boolean(), nullable=False),
        sa.Column("handoff_required", sa.Boolean(), nullable=False),
        sa.Column("assigned_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_preview", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "contact_id", name="uq_conversations_workspace_contact"),
    )
    op.create_index("ix_conversations_workspace_id", "conversations", ["workspace_id"], unique=False)
    op.create_index("ix_conversations_contact_id", "conversations", ["contact_id"], unique=False)
    op.create_index("ix_conversations_status", "conversations", ["status"], unique=False)
    op.create_index("ix_conversations_assigned_user_id", "conversations", ["assigned_user_id"], unique=False)
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"], unique=False)
    op.create_index("ix_conversations_last_inbound_at", "conversations", ["last_inbound_at"], unique=False)
    op.create_index("ix_conversations_last_outbound_at", "conversations", ["last_outbound_at"], unique=False)

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", sa.String(length=12), sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sent_by", sa.String(length=64), nullable=False),
        sa.Column("wa_message_id", sa.String(length=128), nullable=True),
        sa.Column("delivery_status", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_conversation_messages_workspace_id", "conversation_messages", ["workspace_id"], unique=False)
    op.create_index("ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"], unique=False)
    op.create_index("ix_conversation_messages_contact_id", "conversation_messages", ["contact_id"], unique=False)
    op.create_index("ix_conversation_messages_timestamp", "conversation_messages", ["timestamp"], unique=False)
    op.create_index("ix_conversation_messages_wa_message_id", "conversation_messages", ["wa_message_id"], unique=False)

    op.create_table(
        "message_status_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wa_message_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("recipient", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_message_status_events_workspace_id", "message_status_events", ["workspace_id"], unique=False)
    op.create_index("ix_message_status_events_conversation_id", "message_status_events", ["conversation_id"], unique=False)
    op.create_index("ix_message_status_events_wa_message_id", "message_status_events", ["wa_message_id"], unique=False)

    op.create_table(
        "templates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("variables_json", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("reply_rate", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "name", name="uq_templates_workspace_name"),
    )
    op.create_index("ix_templates_workspace_id", "templates", ["workspace_id"], unique=False)

    op.create_table(
        "contact_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", sa.String(length=12), sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contact_notes_workspace_id", "contact_notes", ["workspace_id"], unique=False)
    op.create_index("ix_contact_notes_contact_id", "contact_notes", ["contact_id"], unique=False)
    op.create_index("ix_contact_notes_author_user_id", "contact_notes", ["author_user_id"], unique=False)
    op.create_index("ix_contact_notes_created_at", "contact_notes", ["created_at"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_workspace_id", "audit_events", ["workspace_id"], unique=False)
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"], unique=False)
    op.create_index("ix_audit_events_entity_type", "audit_events", ["entity_type"], unique=False)
    op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"], unique=False)
    op.create_index("ix_audit_events_action", "audit_events", ["action"], unique=False)
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"], unique=False)

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_background_jobs_workspace_id", "background_jobs", ["workspace_id"], unique=False)
    op.create_index("ix_background_jobs_requested_by_user_id", "background_jobs", ["requested_by_user_id"], unique=False)
    op.create_index("ix_background_jobs_kind", "background_jobs", ["kind"], unique=False)
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"], unique=False)
    op.create_index("ix_background_jobs_available_at", "background_jobs", ["available_at"], unique=False)
    op.create_index("ix_background_jobs_created_at", "background_jobs", ["created_at"], unique=False)
    op.create_index("ix_background_jobs_updated_at", "background_jobs", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_background_jobs_updated_at", table_name="background_jobs")
    op.drop_index("ix_background_jobs_created_at", table_name="background_jobs")
    op.drop_index("ix_background_jobs_available_at", table_name="background_jobs")
    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_index("ix_background_jobs_kind", table_name="background_jobs")
    op.drop_index("ix_background_jobs_requested_by_user_id", table_name="background_jobs")
    op.drop_index("ix_background_jobs_workspace_id", table_name="background_jobs")
    op.drop_table("background_jobs")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_id", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_type", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_workspace_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_contact_notes_created_at", table_name="contact_notes")
    op.drop_index("ix_contact_notes_author_user_id", table_name="contact_notes")
    op.drop_index("ix_contact_notes_contact_id", table_name="contact_notes")
    op.drop_index("ix_contact_notes_workspace_id", table_name="contact_notes")
    op.drop_table("contact_notes")
    op.drop_index("ix_templates_workspace_id", table_name="templates")
    op.drop_table("templates")
    op.drop_index("ix_message_status_events_wa_message_id", table_name="message_status_events")
    op.drop_index("ix_message_status_events_conversation_id", table_name="message_status_events")
    op.drop_index("ix_message_status_events_workspace_id", table_name="message_status_events")
    op.drop_table("message_status_events")
    op.drop_index("ix_conversation_messages_wa_message_id", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_timestamp", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_contact_id", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_conversation_id", table_name="conversation_messages")
    op.drop_index("ix_conversation_messages_workspace_id", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_last_outbound_at", table_name="conversations")
    op.drop_index("ix_conversations_last_inbound_at", table_name="conversations")
    op.drop_index("ix_conversations_last_message_at", table_name="conversations")
    op.drop_index("ix_conversations_assigned_user_id", table_name="conversations")
    op.drop_index("ix_conversations_status", table_name="conversations")
    op.drop_index("ix_conversations_contact_id", table_name="conversations")
    op.drop_index("ix_conversations_workspace_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_contacts_pipeline_stage", table_name="contacts")
    op.drop_index("ix_contacts_phone", table_name="contacts")
    op.drop_index("ix_contacts_workspace_id", table_name="contacts")
    op.drop_table("contacts")
    op.drop_index("ix_workspace_config_entries_workspace_id", table_name="workspace_config_entries")
    op.drop_table("workspace_config_entries")
    op.drop_index("ix_user_sessions_token", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_workspace_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_workspace_memberships_role", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_user_id", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_workspace_id", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.drop_table("workspaces")
