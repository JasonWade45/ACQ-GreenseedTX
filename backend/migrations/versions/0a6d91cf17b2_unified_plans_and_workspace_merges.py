"""Add local preparation plans and reviewed legacy workspace migration ledger.

Revision ID: 0a6d91cf17b2
Revises: 9e8b3c712f42
"""

from alembic import op
import sqlalchemy as sa

revision = "0a6d91cf17b2"
down_revision = "9e8b3c712f42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "call_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("opener", sa.Text()),
        sa.Column("talking_points", sa.JSON(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("guardrails", sa.JSON(), nullable=False),
        sa.Column("internal_only", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_call_plans_lead_id", "call_plans", ["lead_id"])
    op.create_table(
        "workspace_merges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_name", sa.String(300), nullable=False),
        sa.Column("snapshot_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("mapping", sa.JSON(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index("ix_workspace_merges_source_fingerprint", "workspace_merges", ["source_fingerprint"])


def downgrade():
    op.drop_index("ix_workspace_merges_source_fingerprint", table_name="workspace_merges")
    op.drop_table("workspace_merges")
    op.drop_index("ix_call_plans_lead_id", table_name="call_plans")
    op.drop_table("call_plans")
