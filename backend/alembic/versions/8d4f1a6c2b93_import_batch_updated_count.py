"""import batch updated_count

Revision ID: 8d4f1a6c2b93
Revises: fffbf9bca0cc
Create Date: 2026-10-23 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '8d4f1a6c2b93'
down_revision = 'fffbf9bca0cc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('import_batches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('import_batches', schema=None) as batch_op:
        batch_op.drop_column('updated_count')
