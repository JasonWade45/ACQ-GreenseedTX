"""Phase 1 safety foundations: suppression, license area, audit support.

Revision ID: a1b2c3d4e5f6
Revises: 0a6d91cf17b2
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "0a6d91cf17b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "suppression",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phone", sa.String(40), nullable=False, index=True),
        sa.Column("phone_normalized", sa.String(40), index=True),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "reason IN ('stop','stopall','unsubscribe','cancel','end','quit',"
            "'wrong_number','not_interested','remove_me','do_not_text','manual','litigator')",
            name="ck_suppression_reason",
        ),
    )
    op.add_column("leads", sa.Column("in_license", sa.Boolean(), nullable=False, server_default=sa.text("1")))


def downgrade():
    op.drop_index("ix_leads_in_license", table_name="leads")
    op.drop_column("leads", "in_license")
    op.drop_index("ix_suppression_phone_normalized", table_name="suppression")
    op.drop_table("suppression")
