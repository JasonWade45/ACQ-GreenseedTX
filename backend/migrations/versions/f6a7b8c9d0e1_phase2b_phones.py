"""Phase 2b: multiple phone numbers per lead (Data Syndicate exports).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    for col in [
        sa.Column("primary_phone_type", sa.String(40), nullable=True),
        sa.Column("phone2", sa.String(40), nullable=True),
        sa.Column("phone2_type", sa.String(40), nullable=True),
        sa.Column("phone3", sa.String(40), nullable=True),
        sa.Column("phone3_type", sa.String(40), nullable=True),
    ]:
        op.add_column("leads", col)


def downgrade():
    for col in ("phone3_type", "phone3", "phone2_type", "phone2", "primary_phone_type"):
        op.drop_column("leads", col)
