"""Call log, tags, assignment rules and the local automation engine.

Every table is new and every change is additive, so an existing database upgrades in
place without touching a lead, activity, draft or CRM mapping. These features are local
bookkeeping: a call that already happened, a label, a desk assignment and a rule that
creates a follow-up. None of them can contact a seller, send a message or write to the
CRM.

Revision ID: k3l4m5n6o7p8
Revises: j2k3l4m5n6
"""

from alembic import op
import sqlalchemy as sa

revision = "k3l4m5n6o7p8"
down_revision = "j2k3l4m5n6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assignment_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state", sa.String(2), nullable=True),
        sa.Column("city", sa.String(120), nullable=True),
        sa.Column("target_assignee", sa.String(120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name"),
        sa.CheckConstraint(
            "(is_fallback AND state IS NULL AND city IS NULL) OR "
            "(NOT is_fallback AND (state IS NOT NULL OR city IS NOT NULL))"
        ),
    )
    op.create_index("ix_assignment_rules_priority", "assignment_rules", ["priority"])
    op.create_index("ix_assignment_rules_state", "assignment_rules", ["state"])
    op.create_index("ix_assignment_rules_city", "assignment_rules", ["city"])

    op.create_table(
        "automation_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rule_type", sa.String(30), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name"),
        sa.CheckConstraint("rule_type IN ('stale_lead','hot_lead','dead_lead')"),
    )
    op.create_index("ix_automation_rules_rule_type", "automation_rules", ["rule_type"])
    op.create_index("ix_automation_rules_enabled", "automation_rules", ["enabled"])

    op.create_table(
        "automation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("automation_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rule_name", sa.String(120), nullable=False),
        sa.Column("records_affected", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("result", sa.String(20), nullable=False, server_default=sa.text("'success'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("result IN ('success','failed','skipped')"),
    )
    op.create_index("ix_automation_logs_rule_id", "automation_logs", ["rule_id"])
    op.create_index("ix_automation_logs_result", "automation_logs", ["result"])

    op.create_table(
        "lead_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("lead_id", "tag", name="uq_lead_tag"),
    )
    op.create_index("ix_lead_tags_lead_id", "lead_tags", ["lead_id"])
    op.create_index("ix_lead_tags_tag", "lead_tags", ["tag"])

    op.create_table(
        "call_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False, server_default=sa.text("'outbound'")),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("followup_id", sa.Integer(), sa.ForeignKey("followups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('connected','interested','wants_offer','no_answer','voicemail',"
            "'callback','not_interested','dnc','wrong_number')"
        ),
        sa.CheckConstraint("direction IN ('outbound','inbound')"),
        sa.CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0"),
    )
    op.create_index("ix_call_logs_lead_id", "call_logs", ["lead_id"])
    op.create_index("ix_call_logs_outcome", "call_logs", ["outcome"])
    op.create_index("ix_call_logs_occurred_at", "call_logs", ["occurred_at"])


def downgrade() -> None:
    op.drop_table("call_logs")
    op.drop_table("lead_tags")
    op.drop_table("automation_logs")
    op.drop_table("automation_rules")
    op.drop_table("assignment_rules")
