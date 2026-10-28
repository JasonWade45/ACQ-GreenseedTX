import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "../api";
import { Button, Empty, ErrorState, Loading, PageHeader, Panel } from "../components";

type Briefing = {
  generated_at: string;
  replies_needing_action: { lead_id: number; name: string; classification: string; confidence: number; received_at: string }[];
  followups_due: { lead_id: number; name: string; due_at: string }[];
  drafts_awaiting_approval: number;
  leads_needing_skip_trace: number;
  stalled_leads: number;
  sync_conflicts: number;
  last_backup: string | null;
};

export function BriefingPage() {
  const data = useQuery({ queryKey: ["briefing"], queryFn: () => api<Briefing>("/briefing") });
  if (data.isPending) return <Loading />;
  if (data.isError) return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const b = data.data!;
  return (
    <>
      <PageHeader
        eyebrow="MORNING BRIEFING"
        title="Daily briefing"
        description="One screen: replies, follow-ups, drafts, skip-trace, stalled leads, conflicts, backup."
        actions={
          <Button variant="secondary" onClick={() => data.refetch()}>
            <RefreshCw size={14} /> Refresh
          </Button>
        }
      />
      <div className="kpi-grid" style={{ marginBottom: 16 }}>
        <div className="kpi">
          <span>Replies needing action</span>
          <strong>{b.replies_needing_action.length}</strong>
        </div>
        <div className="kpi">
          <span>Follow-ups due</span>
          <strong>{b.followups_due.length}</strong>
        </div>
        <div className="kpi">
          <span>Drafts awaiting approval</span>
          <strong>{b.drafts_awaiting_approval}</strong>
        </div>
        <div className="kpi">
          <span>Needs skip trace</span>
          <strong>{b.leads_needing_skip_trace}</strong>
        </div>
        <div className="kpi">
          <span>Stalled leads (14d+)</span>
          <strong>{b.stalled_leads}</strong>
        </div>
        <div className="kpi">
          <span>Sync conflicts</span>
          <strong>{b.sync_conflicts}</strong>
        </div>
      </div>
      <Panel title="Replies needing action (hottest first)">
        {b.replies_needing_action.length === 0 ? (
          <Empty title="No replies needing action" description="All caught up." />
        ) : (
          <ul className="task-list">
            {b.replies_needing_action.map((r) => (
              <li key={r.lead_id}>
                <div>
                  <strong>{r.name}</strong>
                  <p>
                    {r.classification} · confidence {Math.round(r.confidence * 100)}%
                  </p>
                  <span className="task-meta">{r.received_at}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel title="Follow-ups due">
        {b.followups_due.length === 0 ? (
          <Empty title="No follow-ups due" description="Nothing due today." />
        ) : (
          <ul className="task-list">
            {b.followups_due.map((f) => (
              <li key={f.lead_id}>
                <div>
                  <strong>{f.name}</strong>
                  <span className="task-meta">due {f.due_at}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <p style={{ fontSize: 12, opacity: 0.6, marginTop: 12 }}>
        Last backup: {b.last_backup || "none"} · Generated {b.generated_at}
      </p>
    </>
  );
}
