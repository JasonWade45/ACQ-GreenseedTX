"""Reviewed, opt-in Groq requests; additive and no changes to existing seller records.

Revision ID: 9e8b3c712f42
Revises: daec27051e18
"""

from alembic import op
import sqlalchemy as sa

revision = "9e8b3c712f42"
down_revision = "daec27051e18"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cloud_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("records", sa.JSON(), nullable=False),
        sa.Column("source_map", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("purpose IN ('analyze','notes','draft')"),
        sa.CheckConstraint(
            "state IN ('pending_review','running','completed','completed_stale','failed','outcome_unknown','expired')"
        ),
    )
    for field in ("lead_id", "state", "created_at"):
        op.create_index("ix_cloud_requests_" + field, "cloud_requests", [field])


def downgrade():
    for field in ("lead_id", "state", "created_at"):
        op.drop_index("ix_cloud_requests_" + field, table_name="cloud_requests")
    op.drop_table("cloud_requests")
