"""Drop the unused messages.sent_at column.

The application has no send path, so a column that could record "a message left this
machine" is a liability rather than a feature: it was never written by any code and
every existing value is NULL. Removing it makes the draft-only boundary expressible in
the schema itself.

Revision ID: i1j2k3l4m5n6
Revises: h8i9j0k1l2m3
"""

from alembic import op
import sqlalchemy as sa

revision = "i1j2k3l4m5n6"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    if _has_column("messages", "sent_at"):
        with op.batch_alter_table("messages") as batch:
            batch.drop_column("sent_at")


def downgrade() -> None:
    if not _has_column("messages", "sent_at"):
        with op.batch_alter_table("messages") as batch:
            batch.add_column(sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
