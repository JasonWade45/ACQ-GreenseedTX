"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Badge, EmptyState, ErrorBox, PageHeader, Spinner, useAsync } from "@/components/UI";
import { WorkQueue, WorkTask, apiPost, fmtDate, fmtDateTime, isOverdue, stageBadge } from "@/lib/api";

const OUTCOME_OPTIONS = [
  { value: "connected", label: "Connected" },
  { value: "no_answer", label: "No answer" },
  { value: "left_voicemail", label: "Left voicemail" },
  { value: "callback_requested", label: "Callback requested" },
  { value: "seller_not_interested", label: "Seller not interested" },
  { value: "appointment_scheduled", label: "Appointment scheduled" },
  { value: "wrong_number", label: "Wrong number" },
  { value: "other", label: "Other" },
];

function TaskCard({
  task,
  onCompleted,
}: {
  task: WorkTask;
  onCompleted: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState("connected");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function complete() {
    setBusy(true);
    setError(null);
    try {
      // Complete the lead's open follow-up if one exists; otherwise record an activity.
      const fus = await fetch(`/api/followups?status=open&lead_id=${task.lead_id}`).then((r) => r.json());
      if (fus.items && fus.items.length > 0) {
        await apiPost(`/api/followups/${fus.items[0].id}/complete`, { outcome, notes: notes || undefined });
      } else {
        await apiPost(`/api/leads/${task.lead_id}/activities`, {
          activity_type: "call",
          direction: "outbound",
          outcome,
          summary: `Recorded outcome: ${outcome}`,
          detail: notes || undefined,
        });
      }
      setOpen(false);
      setNotes("");
      onCompleted();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="rounded-xl border border-ink-200 bg-white p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link href={`/leads/${task.lead_id}`} className="font-semibold text-ink-900 hover:underline">
              {task.seller_name}
            </Link>
            <span className={`badge ${stageBadge(task.stage)}`}>{task.stage.replace(/_/g, " ")}</span>
            {task.do_not_contact && <Badge className="bg-red-100 text-red-800">DNC</Badge>}
            <Badge className="bg-ink-100 text-ink-600">{task.confidence} confidence</Badge>
          </div>
          <div className="mt-0.5 text-xs text-ink-500">
            {task.phone || "no phone"}
            {task.property_address ? ` · ${task.property_address}` : ""}
          </div>
        </div>
        <div className="text-right text-xs text-ink-500">
          <div className="font-semibold text-ink-700">Priority {task.priority}</div>
          {task.next_followup_at && (
            <div className={isOverdue(task.next_followup_at) ? "text-red-700" : ""}>
              due {fmtDate(task.next_followup_at)}
            </div>
          )}
          {task.last_contact_at ? <div>last contact {fmtDate(task.last_contact_at)}</div> : <div>never contacted</div>}
        </div>
      </div>

      <div className="mt-2 rounded-lg bg-ink-50 px-2.5 py-2 text-sm">
        <div className="font-medium text-ink-800">{task.reason}</div>
        <div className="mt-0.5 text-ink-600">Next: {task.suggested_next_action}</div>
        {task.last_activity_summary && (
          <div className="mt-1 text-xs text-ink-500">Last activity: {task.last_activity_summary}</div>
        )}
      </div>

      {task.evidence.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-[11px] text-ink-500">
          {task.evidence.slice(0, 3).map((ev, i) => (
            <li key={i}>· {ev}</li>
          ))}
        </ul>
      )}

      <div className="mt-2.5 flex flex-wrap gap-2">
        <Link className="btn" href={`/leads/${task.lead_id}`}>
          Open profile
        </Link>
        <Link className="btn" href={`/leads/${task.lead_id}`}>
          Draft message
        </Link>
        <button className="btn" onClick={() => setOpen((v) => !v)}>
          {open ? "Close" : "Mark complete"}
        </button>
      </div>

      {open && (
        <div className="mt-2 rounded-lg border border-ink-200 bg-ink-50 p-2.5">
          <label className="label">What actually happened?</label>
          <select className="input" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            {OUTCOME_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <label className="label mt-2">Notes</label>
          <textarea className="input min-h-[50px]" value={notes} onChange={(e) => setNotes(e.target.value)} />
          {error && <div className="mt-2 text-sm text-red-700">{error}</div>}
          <div className="mt-2 flex gap-2">
            <button className="btn-primary" disabled={busy} onClick={complete}>
              {busy ? "Saving…" : "Save outcome"}
            </button>
          </div>
          <p className="mt-1.5 text-[11px] text-ink-500">
            Recording an outcome does not send anything. Place the call or send the message yourself.
          </p>
        </div>
      )}
    </li>
  );
}

function FollowupsInner() {
  const searchParams = useSearchParams();
  const leadFilter = searchParams.get("lead");
  const { data, error, loading, reload } = useAsync<WorkQueue>(() => apiGetWorkQueue());

  async function apiGetWorkQueue() {
    const res = await fetch("/api/work-queue");
    if (!res.ok) throw new Error(`Failed to load work queue (${res.status})`);
    return res.json() as Promise<WorkQueue>;
  }

  const sections = (data?.sections || []).filter((s) => !leadFilter || s.tasks.some((t) => t.lead_id === leadFilter));

  return (
    <>
      <PageHeader
        title="Daily follow-up queue"
        subtitle={
          data
            ? `${data.total_tasks} open tasks · ${data.today} · sorted by priority, then due date`
            : "Overdue, due today, callbacks, appointments and more"
        }
      />

      <div className="mb-4 rounded-lg border border-ink-200 bg-white p-3 text-xs text-ink-600">
        Every task shows <span className="font-semibold">why</span> it is on the list and a suggested next action.
        Completing a task asks what actually happened — this app never contacts a seller on your behalf.
        {leadFilter && (
          <button className="ml-2 underline" onClick={() => window.location.assign("/followups")}>
            clear lead filter
          </button>
        )}
      </div>

      {loading && <Spinner label="Building work queue…" />}
      {error && <ErrorBox message={error} onRetry={reload} />}

      {!loading && !error && data && data.total_tasks === 0 && (
        <EmptyState
          title="Nothing needs attention"
          description="No overdue follow-ups, callbacks, appointments today, or leads missing critical information. Run a sync or import to refresh the queue."
          action={
            <Link className="btn" href="/">
              Back to dashboard
            </Link>
          }
        />
      )}

      <div className="space-y-6">
        {sections.map((section) => (
          <section key={section.key}>
            <div className="mb-2 flex items-center gap-2">
              <h2 className="text-sm font-semibold text-ink-800">{section.label}</h2>
              <span className="rounded-full bg-brand-600 px-2 py-0.5 text-xs font-semibold text-white shadow-sm shadow-brand-600/25">
                {section.tasks.length}
              </span>
            </div>
            {section.tasks.length === 0 ? (
              <p className="text-sm text-ink-400">None.</p>
            ) : (
              <ul className="space-y-2 stagger">
                {section.tasks.map((task) => (
                  <TaskCard key={`${section.key}-${task.lead_id}`} task={task} onCompleted={reload} />
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>
    </>
  );
}

export default function FollowupsPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <FollowupsInner />
    </Suspense>
  );
}
