import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clipboard, RefreshCw, ShieldAlert, Sparkles, X } from "lucide-react";
import { Link } from "react-router-dom";
import { api, patch, post } from "../api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Loading,
  PageHeader,
  Panel,
  useAction,
  useWorkspace,
} from "../components";
import type { MessageDraft, SequenceSummary } from "../types";

type Queue = { items: MessageDraft[]; total: number };

export default function DraftsPage() {
  const queue = useQuery({
    queryKey: ["drafts"],
    queryFn: () => api<Queue>("/drafts?status=DRAFT"),
  });
  const client = useQueryClient();
  const { toast } = useWorkspace();
  const action = useAction();
  const [tier, setTier] = useState("");
  const [bulk, setBulk] = useState<{
    requested: number;
    generated: number;
    blocked: number;
    results: { lead_id: number; ok: boolean; reason?: string }[];
  } | null>(null);
  const [editing, setEditing] = useState<Record<number, string>>({});
  const pending = useQuery({
    queryKey: ["restriction-pending"],
    queryFn: () =>
      api<{ total: number; items: { id: number; full_name: string | null }[] }>(
        "/leads/restrictions/pending?limit=5",
      ),
  });
  const cadence = useQuery({
    queryKey: ["sequences"],
    queryFn: () => api<SequenceSummary>("/sequences/summary"),
  });

  async function refresh() {
    await queue.refetch();
    client.invalidateQueries({ queryKey: ["briefing"] });
  }

  async function runDue() {
    const result = await action.run(
      () => post<{ processed: number; items: any[] }>("/sequences/run-due"),
      "Due follow-up drafts prepared. Nothing was sent.",
    );
    if (result) {
      const drafted = result.items.filter((i) => i.status === "drafted").length;
      const blocked = result.items.filter((i) => i.status === "blocked").length;
      toast(
        `${drafted} draft(s) prepared, ${blocked} stopped by a gate. Nothing was sent.`,
      );
    }
    await refresh();
    client.invalidateQueries({ queryKey: ["sequences"] });
  }

  async function decide(id: number, decision: "approve" | "reject") {
    await action.run(
      () => post(`/messages/${id}/${decision}`),
      decision === "approve"
        ? "Draft marked reviewed. Nothing was sent."
        : "Draft rejected",
    );
    await refresh();
  }

  async function save(item: MessageDraft) {
    const body = editing[item.id] ?? item.body;
    await action.run(
      () => patch(`/messages/${item.id}`, { body }),
      "Draft saved after validation",
    );
    await refresh();
  }

  async function generate() {
    if (
      !window.confirm(
        `Generate drafts for every ${tier} lead that passes the gates? Drafts are created for review only — nothing is copied and nothing is sent.`,
      )
    )
      return;
    const result = await action.run(
      () =>
        post<{
          requested: number;
          generated: number;
          blocked: number;
          results: { lead_id: number; ok: boolean; reason?: string }[];
        }>("/drafts/bulk", { tier: tier || null, confirm: true }),
      "Drafts generated into the review queue",
    );
    setBulk(result || null);
    await refresh();
  }

  if (queue.isPending) return <Loading />;
  if (queue.isError)
    return <ErrorState error={queue.error} retry={() => queue.refetch()} />;

  return (
    <>
      <PageHeader
        eyebrow="COPY ONLY. NEVER SENT."
        title="Draft review queue"
        description="Every cold draft is validated in code before you can copy it. Bulk generation creates drafts; it never copies or sends them."
        actions={
          <Button variant="secondary" onClick={refresh}>
            <RefreshCw size={14} /> Refresh
          </Button>
        }
      />
      <Panel
        title="Generate drafts for a reviewed tier"
        subtitle="Data Syndicate distress context never appears in the message text."
      >
        <div className="row wrap">
          <Field label="Priority tier">
            <select value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value="">Choose a tier…</option>
              {["P1", "P2", "P3", "P4"].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </Field>
          <Button busy={action.busy} disabled={!tier} onClick={generate}>
            <Sparkles size={15} /> Generate drafts
          </Button>
        </div>
        {bulk && (
          <div className="stack">
            <div className="settings-facts">
              <div>
                <span>Requested</span>
                <strong>{bulk.requested}</strong>
              </div>
              <div>
                <span>Generated</span>
                <strong>{bulk.generated}</strong>
              </div>
              <div>
                <span>Blocked by a gate</span>
                <strong>{bulk.blocked}</strong>
              </div>
            </div>
            {bulk.results.filter((r) => !r.ok).length > 0 && (
              <ul className="task-list">
                {bulk.results
                  .filter((r) => !r.ok)
                  .map((r) => (
                    <li key={r.lead_id}>
                      <div>
                        <strong>Lead #{r.lead_id}</strong>
                        <p>{r.reason}</p>
                      </div>
                    </li>
                  ))}
              </ul>
            )}
          </div>
        )}
        {action.error && <p className="muted">{action.error}</p>}
      </Panel>

      <Panel
        title="Due follow-ups"
        subtitle="The daily runner prepares a draft for every cadence step that is due. It never sends and it stops itself on a reply, a suppression, an appointment or a closed stage."
      >
        <div className="settings-facts">
          <div>
            <span>Active cadences</span>
            <strong>{cadence.data?.active ?? "—"}</strong>
          </div>
          <div>
            <span>Due today</span>
            <strong>{cadence.data?.due_today ?? "—"}</strong>
          </div>
          <div>
            <span>Automatic run</span>
            <strong>
              {cadence.data?.runner_enabled
                ? `Daily at ${cadence.data.runner_hour_utc}:15 UTC`
                : "Disabled"}
            </strong>
          </div>
        </div>
        <Button
          variant="secondary"
          busy={action.busy}
          disabled={!cadence.data?.due_today}
          onClick={runDue}
        >
          <RefreshCw size={15} /> Prepare due drafts
        </Button>
        {!cadence.data?.due_today && (
          <p className="muted">Nothing is due right now.</p>
        )}
      </Panel>

      <Panel
        title="Blocked by an unreviewed contact restriction"
        subtitle="A draft cannot exist for a lead whose contact permission nobody has reviewed. Review them from the seller list, in batches."
        action={
          <Link className="text-link" to="/leads">
            Open seller leads
          </Link>
        }
      >
        <div className="settings-facts">
          <div>
            <span>Waiting for a review</span>
            <strong>{pending.data?.total ?? "—"}</strong>
          </div>
        </div>
        {(pending.data?.total ?? 0) === 0 ? (
          <p className="muted">
            Every lead has a recorded contact-permission review.
          </p>
        ) : (
          <p className="muted">
            Select leads on the seller list and choose “Review contact restrictions”.
            Each lead still keeps its own audit row and the skip-trace, suppression and
            licence checks stay in force.
          </p>
        )}
      </Panel>

      <Panel title={`Drafts awaiting review (${queue.data.total})`}>
        {queue.data.items.length === 0 ? (
          <Empty
            title="No drafts waiting"
            description="Generate drafts for a tier, or open a lead to prepare one."
          />
        ) : (
          <ul className="task-list">
            {queue.data.items.map((item) => {
              const ok = item.validator_result?.ok !== false;
              return (
                <li key={item.id}>
                  <div>
                    <strong>
                      <Link to={`/leads/${item.lead_id}`}>
                        {item.lead_name || `Lead #${item.lead_id}`}
                      </Link>{" "}
                      <Badge tone={ok ? "green" : "amber"}>
                        {ok ? "validator passed" : "validator failed"}
                      </Badge>{" "}
                      {item.heat ? <Badge>{item.heat}</Badge> : null}
                    </strong>
                    <p className="muted">
                      {item.why_this_template?.length
                        ? `Why this template: ${item.why_this_template.join(", ")}`
                        : "Why this template: recorded on the draft"}
                    </p>
                    <Field label="Draft text">
                      <textarea
                        rows={5}
                        value={editing[item.id] ?? item.body}
                        onChange={(e) =>
                          setEditing((current) => ({
                            ...current,
                            [item.id]: e.target.value,
                          }))
                        }
                      />
                    </Field>
                    {!ok && (
                      <p className="muted">
                        <ShieldAlert size={13} />{" "}
                        {(item.validator_result?.reasons || []).join(" · ")}
                      </p>
                    )}
                    <div className="row wrap">
                      <Button
                        variant="secondary"
                        busy={action.busy}
                        onClick={() => save(item)}
                      >
                        <Check size={15} /> Save
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={async () => {
                          try {
                            await navigator.clipboard.writeText(
                              editing[item.id] ?? item.body,
                            );
                            toast("Draft copied. Nothing was sent.");
                          } catch {
                            toast(
                              "Clipboard unavailable. Select and copy the text manually.",
                              "error",
                            );
                          }
                        }}
                      >
                        <Clipboard size={15} /> Copy
                      </Button>
                      <Button
                        busy={action.busy}
                        disabled={!ok}
                        onClick={() => decide(item.id, "approve")}
                      >
                        <Check size={15} /> Mark reviewed
                      </Button>
                      <Button
                        variant="secondary"
                        busy={action.busy}
                        onClick={() => decide(item.id, "reject")}
                      >
                        <X size={15} /> Reject
                      </Button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>
      <p className="muted" style={{ fontSize: 12 }}>
        There is no send button, no bulk copy and no automated outreach job in this
        application.
      </p>
    </>
  );
}
