"""queue routing and ai assist"""

from alembic import op
import sqlalchemy as sa


revision = "0003_queue_and_ai_assist"
down_revision = "0002_reply_policy_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("ai_assist_status", sa.String(length=32), nullable=True))
    op.add_column("conversations", sa.Column("ai_assist_draft", sa.Text(), nullable=True))
    op.add_column("conversations", sa.Column("ai_assist_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_conversations_ai_assist_status", "conversations", ["ai_assist_status"], unique=False)
    op.create_index("ix_conversations_ai_assist_updated_at", "conversations", ["ai_assist_updated_at"], unique=False)

    op.create_table(
        "routing_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("policy_use_case_key", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "scope_type", "scope_key", name="uq_routing_rule_scope"),
    )
    op.create_index("ix_routing_rules_workspace_id", "routing_rules", ["workspace_id"], unique=False)
    op.create_index("ix_routing_rules_scope_type", "routing_rules", ["scope_type"], unique=False)
    op.create_index("ix_routing_rules_scope_key", "routing_rules", ["scope_key"], unique=False)
    op.create_index("ix_routing_rules_policy_use_case_key", "routing_rules", ["policy_use_case_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_routing_rules_policy_use_case_key", table_name="routing_rules")
    op.drop_index("ix_routing_rules_scope_key", table_name="routing_rules")
    op.drop_index("ix_routing_rules_scope_type", table_name="routing_rules")
    op.drop_index("ix_routing_rules_workspace_id", table_name="routing_rules")
    op.drop_table("routing_rules")

    op.drop_index("ix_conversations_ai_assist_updated_at", table_name="conversations")
    op.drop_index("ix_conversations_ai_assist_status", table_name="conversations")
    op.drop_column("conversations", "ai_assist_updated_at")
    op.drop_column("conversations", "ai_assist_draft")
    op.drop_column("conversations", "ai_assist_status")
