"""Bulk-remove CRM-sync copies created for a lead already linked by a CRM push."""

import os
import psycopg

DSN = os.environ["DATABASE_URL"]
TABLES = [
    "activities", "ai_checklist_suggestions", "ai_insights", "appointments", "audit_log",
    "call_logs", "call_plans", "cloud_requests", "crm_note_outbox", "drafts", "followups",
    "grok_runs", "import_rows", "lead_checklist_items", "lead_phones", "lead_properties",
    "lead_sequence_state", "lead_tags", "messages", "stage_history", "suggested_actions",
    "suppression", "sync_conflicts", "tasks",
]

with psycopg.connect(DSN) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            create temporary table dup_map on commit drop as
            select l.id as duplicate, cp.lead_id as original
            from leads l join crm_pushes cp on cp.resimpli_lead_id = l.external_id
            where l.id <> cp.lead_id and l.stage_code = 'unmapped'
        """)
        cur.execute("select count(*) from dup_map")
        print("duplicate sync leads:", cur.fetchone()[0], flush=True)
        for table in TABLES:
            cur.execute("SAVEPOINT move_child")
            try:
                cur.execute(f"update {table} t set lead_id=m.original from dup_map m where t.lead_id=m.duplicate")
                cur.execute("RELEASE SAVEPOINT move_child")
            except psycopg.Error:
                cur.execute("ROLLBACK TO SAVEPOINT move_child")
                cur.execute(f"delete from {table} t using dup_map m where t.lead_id=m.duplicate")
                cur.execute("RELEASE SAVEPOINT move_child")
            print("handled", table, flush=True)
        cur.execute("delete from leads l using dup_map m where l.id=m.duplicate")
        print("removed leads:", cur.rowcount, flush=True)
    conn.commit()
