"""Data Syndicate delta: context fields, cold outreach mode, suggested actions.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2

Every column is additive and nullable/defaulted, so an existing database upgrades
in place without losing a single lead, activity, draft or setting.
"""

from alembic import op
import sqlalchemy as sa

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("leads", sa.Column("ds_flags", sa.JSON(), nullable=True))
    op.add_column("leads", sa.Column("ds_flags_raw", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("ds_extra_flags", sa.JSON(), nullable=True))
    op.add_column("leads", sa.Column("ds_compatible_offers", sa.JSON(), nullable=True))
    op.add_column(
        "leads",
        sa.Column("outreach_mode", sa.String(20), nullable=False, server_default=sa.text("'relationship'")),
    )
    op.create_index("ix_leads_outreach_mode", "leads", ["outreach_mode"])
    op.add_column("messages", sa.Column("reason_tags", sa.JSON(), nullable=True))
    op.add_column(
        "import_batches",
        sa.Column("profile", sa.String(40), nullable=False, server_default=sa.text("'standard'")),
    )
    op.create_table(
        "suggested_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False, index=True),
        sa.Column("classification", sa.String(30), nullable=True, index=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'"), index=True),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('pending','confirmed','dismissed')"),
    )


def downgrade():
    op.drop_table("suggested_actions")
    op.drop_column("import_batches", "profile")
    op.drop_column("messages", "reason_tags")
    op.drop_index("ix_leads_outreach_mode", table_name="leads")
    op.drop_column("leads", "outreach_mode")
    op.drop_column("leads", "ds_compatible_offers")
    op.drop_column("leads", "ds_extra_flags")
    op.drop_column("leads", "ds_flags_raw")
    op.drop_column("leads", "ds_flags")
