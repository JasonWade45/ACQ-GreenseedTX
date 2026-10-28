"""Phase 2 lead fields: Data Syndicate import, tiering, dedupe key, skip-trace.

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
"""

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    for col in [
        sa.Column("recorded_date", sa.DateTime(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("heat", sa.String(20), nullable=True),
        sa.Column("equity_pct", sa.Float(), nullable=True),
        sa.Column("county", sa.String(120), nullable=True),
        sa.Column("lead_type", sa.String(120), nullable=True),
        sa.Column("priority_tier", sa.String(4), nullable=True),
        sa.Column("priority_rank", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(700), nullable=True),
        sa.Column("needs_skip_trace", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("user_edited_fields", sa.JSON(), nullable=True),
        sa.Column("import_batch_id", sa.String(64), nullable=True),
    ]:
        op.add_column("leads", col)
    op.create_index("ix_leads_county", "leads", ["county"])
    op.create_index("ix_leads_lead_type", "leads", ["lead_type"])
    op.create_index("ix_leads_priority_tier", "leads", ["priority_tier"])
    op.create_index("ix_leads_dedupe_key", "leads", ["dedupe_key"])
    op.create_index("ix_leads_needs_skip_trace", "leads", ["needs_skip_trace"])


def downgrade():
    for idx in ("ix_leads_needs_skip_trace", "ix_leads_dedupe_key", "ix_leads_priority_tier", "ix_leads_lead_type", "ix_leads_county"):
        op.drop_index(idx, table_name="leads")
    for col in ("import_batch_id", "user_edited_fields", "needs_skip_trace", "dedupe_key", "priority_rank", "priority_tier", "lead_type", "county", "equity_pct", "heat", "score", "recorded_date"):
        op.drop_column("leads", col)
