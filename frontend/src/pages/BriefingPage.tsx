import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, RefreshCw, ShieldAlert, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api, post } from "../api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Loading,
  PageHeader,
  Panel,
  useAction,
} from "../components";
import type { BriefingData } from "../types";

export function BriefingPage() {
  const data = useQuery({
    queryKey: ["briefing"],
    queryFn: () => api<BriefingData>("/briefing"),
  });
  const client = useQueryClient();
  const action = useAction();
  if (data.isPending) return <Loading />;
  if (data.isError)
    return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const b = data.data!;
  // A literal opt-out is shown in its own compliance block above, so it is not
  // repeated in the ordinary reply list.
  const otherReplies = b.replies_needing_action.filter(
    (r) => r.classification !== "STOP",
  );
  async function decide(id: number, decision: "confirm" | "dismiss") {
    await action.run(
      () => post(`/suggested-actions/${id}/${decision}`),
      decision === "confirm"
        ? "Suggestion applied. Nothing was sent."
        : "Suggestion dismissed",
    );
    await data.refetch();
    client.invalidateQueries({ queryKey: ["lead"] });
  }
  return (
    <>
      <PageHeader
        eyebrow="MORNING BRIEFING"
        title="Daily briefing"
        description="Replies, drafts, skip trace, stalled leads, conflicts and the last backup. Nothing is sent from here."
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
          <span>Drafts awaiting review</span>
          <strong>{b.drafts_awaiting_approval}</strong>
        </div>
        <div className="kpi">
          <span>Needs skip trace</span>
          <strong>{b.leads_needing_skip_trace}</strong>
        </div>
        <div className="kpi">
          <span>Stalled leads ({b.stalled_window_days}d+)</span>
          <strong>{b.stalled_leads}</strong>
        </div>
        <div className="kpi">
          <span>Sync conflicts</span>
          <strong>{b.sync_conflicts}</strong>
        </div>
      </div>

      {b.compliance_first.length > 0 && (
        <Panel
          title="Opt-out replies — confirm suppression"
          subtitle="A literal STOP blocks outreach immediately. Adding the number to the suppression list is your decision."
        >
          <ul className="task-list">
            {b.compliance_first.map((item) => (
              <li key={item.id}>
                <div>
                  <strong>{item.lead_name || "Unnamed lead"}</strong>
                  <p>
                    <Badge tone="amber">{item.classification}</Badge>{" "}
                    confidence {Math.round((item.confidence || 0) * 100)}%
                    {item.evidence ? ` · “${item.evidence}”` : ""}
                  </p>
                </div>
                <div className="row wrap">
                  <Button
                    busy={action.busy}
                    onClick={() => decide(item.id, "confirm")}
                  >
                    <Check size={15} /> {item.label}
                  </Button>
                  <Button
                    variant="secondary"
                    busy={action.busy}
                    onClick={() => decide(item.id, "dismiss")}
                  >
                    <X size={15} /> Dismiss
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel title="Replies needing action (hottest first)">
        {otherReplies.length === 0 ? (
          <Empty title="No replies needing action" description="All caught up." />
        ) : (
          <ul className="task-list">
            {otherReplies.map((r) => (
              <li key={r.suggestion_id}>
                <div>
                  <strong>
                    <Link to={`/leads/${r.lead_id}`}>
                      {r.name || `Lead #${r.lead_id}`}
                    </Link>
                  </strong>
                  <p>
                    <Badge
                      tone={
                        r.classification === "STOP" ||
                        r.classification === "NOT_INTERESTED"
                          ? "amber"
                          : "green"
                      }
                    >
                      {r.classification}
                    </Badge>{" "}
                    confidence {Math.round((r.confidence || 0) * 100)}%
                    {r.needs_review ? " · needs a human read" : ""}
                  </p>
                  {r.evidence && <blockquote>“{r.evidence}”</blockquote>}
                  <span className="task-meta">{r.received_at}</span>
                </div>
                <div className="row wrap">
                  <Button
                    variant="secondary"
                    busy={action.busy}
                    onClick={() => decide(r.suggestion_id, "confirm")}
                  >
                    <Check size={15} /> Confirm
                  </Button>
                  <Button
                    variant="secondary"
                    busy={action.busy}
                    onClick={() => decide(r.suggestion_id, "dismiss")}
                  >
                    <X size={15} /> Dismiss
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        title="Drafts awaiting review"
        subtitle="Copy-only. There is no bulk copy and no send anywhere in this app."
        action={
          <Link className="text-link" to="/drafts">
            Open draft queue
          </Link>
        }
      >
        <div className="settings-facts">
          <div>
            <span>Drafts in the queue</span>
            <strong>{b.drafts_awaiting_approval}</strong>
          </div>
          <div>
            <span>Failing the content validator</span>
            <strong>{b.drafts_failing_validation.length}</strong>
          </div>
        </div>
        {b.drafts_failing_validation.length > 0 && (
          <ul className="task-list">
            {b.drafts_failing_validation.slice(0, 5).map((d) => (
              <li key={d.id}>
                <div>
                  <strong>
                    <ShieldAlert size={14} /> Draft #{d.id}
                  </strong>
                  <p>{d.reasons.join(" · ")}</p>
                </div>
                <Link className="text-link" to={`/leads/${d.lead_id}`}>
                  Review lead
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        title="Leads needing a skip trace"
        subtitle={`${b.leads_needing_skip_trace} address-only leads have no verified owner name or phone.`}
        action={
          <Link className="text-link" to="/imports">
            Open skip-trace loop
          </Link>
        }
      >
        {b.skip_trace_leads.length === 0 ? (
          <Empty title="Nothing waiting" description="Every lead has a verified contact." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Address</th>
                  <th>Heat</th>
                  <th>Score</th>
                  <th>Tier</th>
                </tr>
              </thead>
              <tbody>
                {b.skip_trace_leads.map((lead) => (
                  <tr key={lead.lead_id}>
                    <td>
                      <Link to={`/leads/${lead.lead_id}`}>
                        {lead.address || `Lead #${lead.lead_id}`}
                      </Link>
                    </td>
                    <td>{lead.heat || "—"}</td>
                    <td>{lead.score ?? "—"}</td>
                    <td>{lead.priority_tier || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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

      <Panel title="Backups">
        <div className="settings-facts">
          <div>
            <span>Last backup</span>
            <strong>{b.backups.last_backup_at || "none yet"}</strong>
          </div>
          <div>
            <span>File</span>
            <strong>{b.backups.last_backup_file || "—"}</strong>
          </div>
          <div>
            <span>Second folder</span>
            <strong>{b.backups.second_folder || "not configured"}</strong>
          </div>
          <div>
            <span>Second-folder copy</span>
            <Badge
              tone={
                b.backups.second_folder_ok === null
                  ? "neutral"
                  : b.backups.second_folder_ok
                    ? "green"
                    : "amber"
              }
            >
              {b.backups.second_folder_ok === null
                ? "not run yet"
                : b.backups.second_folder_ok
                  ? "last copy ok"
                  : "last copy failed"}
            </Badge>
          </div>
        </div>
        {b.backups.second_folder_detail && (
          <p className="muted">
            <AlertTriangle size={13} /> {b.backups.second_folder_detail}
          </p>
        )}
        <Link className="text-link" to="/settings?section=runtime">
          Backup settings <RefreshCw size={13} />
        </Link>
      </Panel>

      <p style={{ fontSize: 12, opacity: 0.6, marginTop: 12 }}>
        Generated {b.generated_at} · nothing was sent from this screen.
      </p>
    </>
  );
}
