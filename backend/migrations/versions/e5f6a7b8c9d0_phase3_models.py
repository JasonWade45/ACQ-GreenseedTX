"""Phase 3-7 data model: templates, messages, sequences, sync conflicts, tasks.

Revision ID: e5f6a7b8c9d0
Revises: c3d4e5f6a7b8
"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category", sa.String(60), nullable=False, index=True),
        sa.Column("lead_type_match", sa.JSON(), nullable=True),
        sa.Column("flag_conditions", sa.JSON(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("variant", sa.String(4), nullable=False, server_default="A"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("stats", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("direction", sa.String(10), nullable=False, server_default="outbound"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("variant", sa.String(4), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT", index=True),
        sa.Column("validator_result", sa.JSON(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("classification", sa.String(30), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )
    op.create_table(
        "sequences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("lead_type", sa.String(120), nullable=True),
        sa.Column("cadence", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "sequence_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sequence_id", sa.Integer(), sa.ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("day_offset", sa.Integer(), nullable=False),
        sa.Column("template_category", sa.String(60), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "lead_sequence_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("sequence_id", sa.Integer(), sa.ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_due_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("stop_reason", sa.String(80), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "sync_conflicts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("field", sa.String(80), nullable=False),
        sa.Column("local_value", sa.Text(), nullable=True),
        sa.Column("crm_value", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolution", sa.String(40), nullable=True),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("due_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open", index=True),
        sa.Column("source", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    for t in ("tasks", "sync_conflicts", "lead_sequence_state", "sequence_steps", "sequences", "messages", "templates"):
        op.drop_table(t)
