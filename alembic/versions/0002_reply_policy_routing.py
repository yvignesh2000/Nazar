"""reply policy routing"""

from alembic import op
import sqlalchemy as sa


revision = "0002_reply_policy_routing"
down_revision = "0001_product_foundation_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("use_case_key", sa.String(length=64), nullable=False, server_default="default_inbound"))
    op.add_column("conversations", sa.Column("source_type", sa.String(length=64), nullable=False, server_default="direct_inbound"))
    op.add_column("conversations", sa.Column("source_ref", sa.String(length=64), nullable=True))
    op.add_column("conversations", sa.Column("active_reply_policy_key", sa.String(length=64), nullable=False, server_default="default_inbound"))
    op.add_column("conversations", sa.Column("human_queue", sa.String(length=64), nullable=True))
    op.create_index("ix_conversations_use_case_key", "conversations", ["use_case_key"], unique=False)
    op.create_index("ix_conversations_source_type", "conversations", ["source_type"], unique=False)
    op.create_index("ix_conversations_source_ref", "conversations", ["source_ref"], unique=False)
    op.create_index("ix_conversations_active_reply_policy_key", "conversations", ["active_reply_policy_key"], unique=False)
    op.create_index("ix_conversations_human_queue", "conversations", ["human_queue"], unique=False)

    op.create_table(
        "reply_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("use_case_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("reply_mode", sa.String(length=32), nullable=False, server_default="bot_first"),
        sa.Column("fallback_queue", sa.String(length=64), nullable=False, server_default="sales"),
        sa.Column("force_human_keywords_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "use_case_key", name="uq_reply_policy_use_case"),
    )
    op.create_index("ix_reply_policies_workspace_id", "reply_policies", ["workspace_id"], unique=False)
    op.create_index("ix_reply_policies_use_case_key", "reply_policies", ["use_case_key"], unique=False)
    op.create_index("ix_reply_policies_reply_mode", "reply_policies", ["reply_mode"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_reply_policies_reply_mode", table_name="reply_policies")
    op.drop_index("ix_reply_policies_use_case_key", table_name="reply_policies")
    op.drop_index("ix_reply_policies_workspace_id", table_name="reply_policies")
    op.drop_table("reply_policies")

    op.drop_index("ix_conversations_human_queue", table_name="conversations")
    op.drop_index("ix_conversations_active_reply_policy_key", table_name="conversations")
    op.drop_index("ix_conversations_source_ref", table_name="conversations")
    op.drop_index("ix_conversations_source_type", table_name="conversations")
    op.drop_index("ix_conversations_use_case_key", table_name="conversations")
    op.drop_column("conversations", "human_queue")
    op.drop_column("conversations", "active_reply_policy_key")
    op.drop_column("conversations", "source_ref")
    op.drop_column("conversations", "source_type")
    op.drop_column("conversations", "use_case_key")
