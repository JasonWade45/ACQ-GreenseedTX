"""REsimpli push mapping, note outbox, checklists and xAI run records.

Every table is new and every column is additive, so an existing database upgrades in
place without touching a lead, activity, draft or setting. The writes this schema makes
possible are deliberately narrow: a lead may be *created* in REsimpli (``crm_pushes``
holds the mapping and the hash of what was sent), a note may be attached to that
creation (``crm_note_outbox``), and a person's checklist work and AI output are local
records. There is no column anywhere that records a message being sent.

Revision ID: j2k3l4m5n6
Revises: i1j2k3l4m5n6
"""

from alembic import op
import sqlalchemy as sa

revision = "j2k3l4m5n6"
down_revision = "i1j2k3l4m5n6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_pushes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False, server_default=sa.text("'resimpli'")),
        sa.Column("resimpli_lead_id", sa.String(100), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("note_hash", sa.String(64), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("pushed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("state IN ('pending','blocked','pushing','pushed','failed')"),
        sa.CheckConstraint("provider IN ('resimpli')"),
    )
    op.create_index("ix_crm_pushes_lead_id", "crm_pushes", ["lead_id"], unique=True)
    op.create_index("ix_crm_pushes_resimpli_lead_id", "crm_pushes", ["resimpli_lead_id"])
    op.create_index("ix_crm_pushes_state", "crm_pushes", ["state"])
    op.create_index("ix_crm_pushes_created_at", "crm_pushes", ["created_at"])

    op.create_table(
        "crm_note_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note_hash", sa.String(64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False, server_default=sa.text("'import'")),
        sa.Column("state", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("delivered_via", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("lead_id", "note_hash", name="uq_crm_note_outbox_lead_hash"),
        sa.CheckConstraint("state IN ('pending','blocked','delivered','skipped')"),
        sa.CheckConstraint("source IN ('import','enrichment','manual','advisor')"),
    )
    op.create_index("ix_crm_note_outbox_lead_id", "crm_note_outbox", ["lead_id"])
    op.create_index("ix_crm_note_outbox_state", "crm_note_outbox", ["state"])
    op.create_index("ix_crm_note_outbox_created_at", "crm_note_outbox", ["created_at"])

    op.create_table(
        "checklist_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_checklist_templates_key", "checklist_templates", ["key"], unique=True)

    op.create_table(
        "checklist_template_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("checklist_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("default_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("template_id", "position", name="uq_checklist_template_item_position"),
    )
    op.create_index("ix_checklist_template_items_template_id", "checklist_template_items", ["template_id"])

    op.create_table(
        "lead_checklist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_key", sa.String(40), nullable=False),
        sa.Column(
            "template_item_id",
            sa.Integer(),
            sa.ForeignKey("checklist_template_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default=sa.text("'template'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("source IN ('template','ai','manual')"),
    )
    op.create_index("ix_lead_checklist_items_lead_id", "lead_checklist_items", ["lead_id"])
    op.create_index("ix_lead_checklist_items_template_key", "lead_checklist_items", ["template_key"])

    op.create_table(
        "grok_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=True),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("api", sa.String(30), nullable=False, server_default=sa.text("'responses'")),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default=sa.text("'succeeded'")),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("request_preview", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("purpose IN ('followup_draft','checklist_suggest','advisor')"),
        sa.CheckConstraint("state IN ('succeeded','failed','invalid','blocked')"),
        sa.CheckConstraint("api IN ('responses','chat_completions')"),
    )
    op.create_index("ix_grok_runs_lead_id", "grok_runs", ["lead_id"])
    op.create_index("ix_grok_runs_purpose", "grok_runs", ["purpose"])
    op.create_index("ix_grok_runs_state", "grok_runs", ["state"])
    op.create_index("ix_grok_runs_input_hash", "grok_runs", ["input_hash"])
    op.create_index("ix_grok_runs_created_at", "grok_runs", ["created_at"])

    op.create_table(
        "ai_checklist_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("grok_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('pending','accepted','rejected')"),
    )
    op.create_index("ix_ai_checklist_suggestions_lead_id", "ai_checklist_suggestions", ["lead_id"])
    op.create_index("ix_ai_checklist_suggestions_run_id", "ai_checklist_suggestions", ["run_id"])
    op.create_index("ix_ai_checklist_suggestions_status", "ai_checklist_suggestions", ["status"])
    op.create_index("ix_ai_checklist_suggestions_created_at", "ai_checklist_suggestions", ["created_at"])


def downgrade() -> None:
    op.drop_table("ai_checklist_suggestions")
    op.drop_table("grok_runs")
    op.drop_table("lead_checklist_items")
    op.drop_table("checklist_template_items")
    op.drop_table("checklist_templates")
    op.drop_table("crm_note_outbox")
    op.drop_table("crm_pushes")
