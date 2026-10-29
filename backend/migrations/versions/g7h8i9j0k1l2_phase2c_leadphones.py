"""Phase 2c: lead_phones table + phone4 slot (all phone numbers from any sheet).

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
"""

from alembic import op
import sqlalchemy as sa

revision = "g7h8i9j0k1l2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("leads", sa.Column("phone4", sa.String(40), nullable=True))
    op.add_column("leads", sa.Column("phone4_type", sa.String(40), nullable=True))
    op.add_column("leads", sa.Column("phone5", sa.String(40), nullable=True))
    op.add_column("leads", sa.Column("phone5_type", sa.String(40), nullable=True))
    op.create_table(
        "lead_phones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("phone_normalized", sa.String(40), index=True),
        sa.Column("phone_type", sa.String(40), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_column", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("lead_phones")
    op.drop_column("leads", "phone5_type")
    op.drop_column("leads", "phone5")
    op.drop_column("leads", "phone4_type")
    op.drop_column("leads", "phone4")
