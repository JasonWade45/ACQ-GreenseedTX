/**
 * CRM sync, checklists and the AI cards.
 *
 * Three rules shape this file. Every card says what state it is in and what can be done
 * next, using one status vocabulary (ok / warning / danger / info / neutral) so the same
 * colour never means two things. Nothing here sends anything: a push creates a record in
 * the CRM and the confirmation is typed by a person, while an AI draft can only be edited
 * and copied.
 *
 * Direction: the stylesheet uses logical properties only, so the layout mirrors when the
 * document is right-to-left, and every piece of seller-supplied text is marked dir="auto"
 * so an Arabic note reads correctly inside an English interface. There is no translation
 * layer in this application yet, and this module does not pretend to be one.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  Check,
  CircleAlert,
  Clipboard,
  ClipboardCheck,
  Copy,
  DatabaseZap,
  FileText,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Upload,
} from "lucide-react";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Loading,
  Notice,
  Panel,
  useAction,
  useData,
} from "./components";
import { dateTime, patch, post } from "./api";
import "./crm.css";

export type StatusTone = "ok" | "warning" | "danger" | "info" | "neutral";

export const statusLabels: Record<StatusTone, string> = {
  ok: "Done",
  warning: "Needs attention",
  danger: "Blocked",
  info: "Waiting",
  neutral: "Not started",
};

export function StatusPill({
  tone,
  children,
}: {
  tone: StatusTone;
  children: React.ReactNode;
}) {
  return (
    <span className={`crm-status crm-status-${tone}`} role="status">
      <span className="crm-status-dot" aria-hidden="true" />
      {children}
    </span>
  );
}

export function ProgressRing({
  percent,
  done,
  total,
  label,
}: {
  percent: number;
  done: number;
  total: number;
  label: string;
}) {
  const radius = 28;
  const circumference = 2 * Math.PI * radius;
  const offset =
    circumference - (Math.min(100, Math.max(0, percent)) / 100) * circumference;
  return (
    <div
      className="crm-ring"
      role="img"
      aria-label={`${label}: ${done} of ${total} complete (${percent}%)`}
    >
      <svg viewBox="0 0 72 72" width="72" height="72" aria-hidden="true">
        <circle
          className="crm-ring-track"
          cx="36"
          cy="36"
          r={radius}
          fill="none"
          strokeWidth="8"
        />
        <circle
          className="crm-ring-value"
          cx="36"
          cy="36"
          r={radius}
          fill="none"
          strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 36 36)"
        />
      </svg>
      <div className="crm-ring-label">
        <strong>{percent}%</strong>
        <span>
          {done}/{total}
        </span>
      </div>
    </div>
  );
}

type ChecklistGroup = {
  key: string;
  name: string;
  done: number;
  total: number;
  percent: number;
  complete: boolean;
  items: {
    id: number;
    title: string;
    detail: string | null;
    done: boolean;
    source: string;
  }[];
};

type CrmSync = {
  state: string;
  resimpli_lead_id: string | null;
  reason: string | null;
  message: string | null;
  pushed_at: string | null;
};

type Note = {
  id: number;
  body: string;
  state: string;
  reason: string | null;
  delivered_via: string | null;
  created_at: string;
};

type Advice = {
  run_id: string;
  model: string;
  created_at: string;
  advice: {
    situation_summary: string;
    next_steps: string[];
    do_not: string[];
    risks: string[];
    exit_strategy: {
      name: string;
      reasoning: string;
      missing_information: string[];
    };
    confidence: "low" | "medium" | "high";
  };
  disclaimer: string;
  compliance: string;
};

export type LeadCards = {
  lead_id: number;
  full_name: string;
  next_action: {
    kind: string | null;
    title: string;
    due_at: string | null;
    detail: string | null;
  };
  checklist: {
    checklists: ChecklistGroup[];
    done: number;
    total: number;
    percent: number;
    complete: boolean;
  };
  exit_strategy: Advice | null;
  last_conversation: {
    occurred_at: string | null;
    direction: string | null;
    summary: string;
    outcome: string | null;
  } | null;
  crm_sync: CrmSync;
  notes: Note[];
  ai: { enabled: boolean; remaining_today: number };
};

export const crmTone = (state: string): StatusTone => {
  switch (state) {
    case "pushed":
      return "ok";
    case "blocked":
      return "warning";
    case "failed":
      return "danger";
    case "pushing":
      return "info";
    default:
      return "neutral";
  }
};

const reasonLabel = (reason: string | null) =>
  ({
    needs_phone: "Needs a phone",
    invalid_phone: "No valid 10-digit phone",
    missing_address: "No property address",
    land_without_apn: "Land lead without an APN",
    do_not_contact: "Restricted lead",
    missing_crm_defaults: "Account IDs not loaded",
    exists_in_crm: "Already in REsimpli",
    crm_search_failed: "CRM unreachable",
    already_pushed: "Already pushed",
    writes_disabled: "Writes switched off",
    confirmation_required: "Confirmation needed",
    rejected_payload: "REsimpli refused it",
    outcome_unknown: "Outcome unknown — check the CRM",
    rate_limited: "Rate limited",
  })[reason || ""] || (reason ? reason.replaceAll("_", " ") : "Ready");

export function LeadIntegrationCards({ leadId }: { leadId: number | string }) {
  const cards = useData<LeadCards>("lead-cards", `/leads/${leadId}/cards`);
  const action = useAction();
  const client = useQueryClient();
  const [copied, setCopied] = useState<number | null>(null);

  if (cards.isPending) return <Loading />;
  if (cards.isError)
    return <ErrorState error={cards.error} retry={() => cards.refetch()} />;
  const data = cards.data;
  if (!data?.next_action || !data.checklist || !data.crm_sync)
    return (
      <Notice tone="warning">
        The CRM and checklist cards could not be read from this server. The rest
        of the lead profile still works.
      </Notice>
    );
  const sync = data.crm_sync;

  async function tick(itemId: number, done: boolean) {
    await action.run(
      () => patch(`/checklists/items/${itemId}`, { done }),
      done ? "Item complete" : "Item reopened",
    );
  }

  async function copyNote(note: Note) {
    try {
      await navigator.clipboard.writeText(note.body);
      setCopied(note.id);
    } catch {
      action.setError(
        "The clipboard is unavailable in this browser; select the text and copy it manually.",
      );
    }
  }

  return (
    <div className="crm-cards" aria-label="Lead integration cards">
      <Panel
        title="Next action"
        subtitle="The one thing to do next on this lead"
      >
        <div className="crm-card-body">
          <StatusPill tone={data.next_action.kind ? "info" : "neutral"}>
            {data.next_action.kind
              ? data.next_action.kind.replaceAll("_", " ")
              : "Nothing scheduled"}
          </StatusPill>
          <p dir="auto">{data.next_action.title}</p>
          {data.next_action.due_at && (
            <span className="crm-muted">
              Due {dateTime(data.next_action.due_at)}
            </span>
          )}
        </div>
      </Panel>

      <Panel
        title="Checklists"
        subtitle="Lead Manager and Acquisition, copied onto this lead"
        action={
          <Button
            variant="ghost"
            busy={action.busy}
            onClick={() =>
              action.run(async () => {
                await client.invalidateQueries({ queryKey: ["lead-cards"] });
              }, "Checklists refreshed")
            }
          >
            <RefreshCw size={15} />
            Refresh
          </Button>
        }
      >
        <div className="crm-checklist-head">
          <ProgressRing
            percent={data.checklist.percent}
            done={data.checklist.done}
            total={data.checklist.total}
            label="Total checklist progress"
          />
          <div>
            <strong>
              {data.checklist.complete
                ? "All checklist work is done"
                : `${data.checklist.total - data.checklist.done} item(s) open`}
            </strong>
            <p className="crm-muted">
              Ticking an item writes locally only. Nothing is sent anywhere.
            </p>
          </div>
        </div>
        {data.checklist.checklists.map((group) => (
          <section
            key={group.key}
            className="crm-checklist-group"
            aria-label={`${group.name} checklist`}
          >
            <header>
              <h3>{group.name}</h3>
              <span className="crm-muted">
                {group.done}/{group.total} · {group.percent}%
              </span>
            </header>
            <ul>
              {group.items.map((item) => (
                <li key={item.id}>
                  <label className="crm-check">
                    <input
                      type="checkbox"
                      checked={item.done}
                      onChange={(event) => tick(item.id, event.target.checked)}
                    />
                    <span dir="auto">{item.title}</span>
                  </label>
                  {item.source === "ai" && (
                    <Badge tone="purple">AI suggestion</Badge>
                  )}
                  {item.detail && (
                    <p className="crm-muted" dir="auto">
                      {item.detail}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </Panel>

      <Panel
        title="Exit strategy"
        subtitle="Decision support from the advisor, never advice"
      >
        {data.exit_strategy ? (
          <div className="crm-card-body">
            <StatusPill
              tone={
                data.exit_strategy.advice.confidence === "low"
                  ? "warning"
                  : "info"
              }
            >
              {data.exit_strategy.advice.confidence} confidence
            </StatusPill>
            <h3 dir="auto">{data.exit_strategy.advice.exit_strategy.name}</h3>
            <p dir="auto">
              {data.exit_strategy.advice.exit_strategy.reasoning}
            </p>
            {data.exit_strategy.advice.exit_strategy.missing_information
              .length > 0 && (
              <div>
                <strong>Missing information</strong>
                <ul dir="auto">
                  {data.exit_strategy.advice.exit_strategy.missing_information.map(
                    (item) => (
                      <li key={item}>{item}</li>
                    ),
                  )}
                </ul>
              </div>
            )}
            <Notice tone="warning">
              <ShieldCheck size={16} /> {data.exit_strategy.disclaimer}{" "}
              {data.exit_strategy.compliance}
            </Notice>
            <span className="crm-muted">
              {data.exit_strategy.model} ·{" "}
              {dateTime(data.exit_strategy.created_at)}
            </span>
          </div>
        ) : (
          <Empty
            title="No advisor note yet"
            description="Run the advisor from the AI panel. It answers with a schema-checked exit strategy, the reasoning, and what it does not know."
          />
        )}
      </Panel>

      <Panel
        title="Last conversation"
        subtitle="From the read-only activity sync"
      >
        {data.last_conversation ? (
          <div className="crm-card-body">
            <StatusPill
              tone={data.last_conversation.outcome ? "info" : "neutral"}
            >
              {data.last_conversation.direction || "activity"}
            </StatusPill>
            <p dir="auto">{data.last_conversation.summary}</p>
            <span className="crm-muted">
              {dateTime(data.last_conversation.occurred_at)}
              {data.last_conversation.outcome
                ? ` · ${data.last_conversation.outcome}`
                : ""}
            </span>
          </div>
        ) : (
          <Empty
            title="No activity recorded"
            description="Sync the CRM or record an activity to see the last conversation here."
          />
        )}
      </Panel>

      <Panel title="CRM sync" subtitle="Create-only: one lead, no updates">
        <div className="crm-card-body">
          <StatusPill tone={crmTone(sync.state)}>
            {sync.state === "not_pushed"
              ? "Not in the CRM yet"
              : crmTone(sync.state) === "ok"
                ? "Pushed"
                : reasonLabel(sync.reason)}
          </StatusPill>
          {sync.resimpli_lead_id && (
            <span className="crm-muted">
              REsimpli id {sync.resimpli_lead_id}
            </span>
          )}
          {sync.message && (
            <p className="crm-muted" dir="auto">
              {sync.message}
            </p>
          )}
          {sync.pushed_at && (
            <span className="crm-muted">Pushed {dateTime(sync.pushed_at)}</span>
          )}
          <p className="crm-muted">
            The Push Queue previews the exact request body before anything is
            created, and the CRM is searched by address and phone first.
          </p>
        </div>
      </Panel>

      <Panel
        title="Notes"
        subtitle="[GreenSeed] notes — copy is the only way out"
      >
        {data.notes.length === 0 ? (
          <Empty
            title="No note yet"
            description="A note is written when the lead is pushed, or built here for copying."
          />
        ) : (
          <ul className="crm-notes">
            {data.notes.map((note) => (
              <li key={note.id}>
                <header>
                  <StatusPill
                    tone={
                      note.state === "delivered"
                        ? "ok"
                        : note.state === "blocked"
                          ? "warning"
                          : "info"
                    }
                  >
                    {note.state === "delivered"
                      ? "In the CRM comment"
                      : note.state === "blocked"
                        ? "Local only"
                        : "Pending"}
                  </StatusPill>
                  <span className="crm-muted">{dateTime(note.created_at)}</span>
                </header>
                <pre dir="auto" className="crm-note-body">
                  {note.body}
                </pre>
                {note.reason && (
                  <p className="crm-muted" dir="auto">
                    {note.reason}
                  </p>
                )}
                <Button variant="secondary" onClick={() => copyNote(note)}>
                  {copied === note.id ? (
                    <ClipboardCheck size={15} />
                  ) : (
                    <Copy size={15} />
                  )}
                  {copied === note.id ? "Copied" : "Copy note"}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

type PushRow = {
  lead_id: number;
  full_name: string;
  address: string | null;
  state: string;
  reason: string | null;
  message: string | null;
  resimpli_lead_id: string | null;
  pushed_at: string | null;
};

type PushQueue = {
  rows: PushRow[];
  counts: { total: number; ready: number; blocked: number };
  failed: number;
  mode: "review" | "auto";
  writes_enabled: boolean;
};

type PushSettings = {
  settings: {
    mode: "review" | "auto";
    marketing_campign_id: string;
    market_id: string;
    pipeline_id: string;
    main_status_id: string;
    note_fields: Record<string, boolean>;
  };
  crm_writes_enabled: boolean;
  confirmation_phrase: string;
  note_fields: Record<string, boolean>;
  write_scope: string;
};

type Plan = {
  lead_id: number;
  eligible: boolean;
  reason: string | null;
  message: string;
  body: Record<string, unknown> | null;
  payload_hash: string | null;
  warnings: string[];
  matches: {
    resimpli_lead_id: string;
    full_name: string | null;
    address: string | null;
    matched_on: string;
  }[];
  note: string | null;
  writes_nothing?: boolean;
};

export function PushQueuePanel() {
  const queue = useData<PushQueue>(
    "push-queue",
    "/integrations/resimpli/push/queue",
  );
  const settings = useData<PushSettings>(
    "push-settings",
    "/integrations/resimpli/push/settings",
  );
  const action = useAction();
  const [plan, setPlan] = useState<Plan | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [selected, setSelected] = useState<number | null>(null);

  if (queue.isPending || settings.isPending) return <Loading />;
  if (queue.isError)
    return <ErrorState error={queue.error} retry={() => queue.refetch()} />;
  if (settings.isError)
    return (
      <ErrorState error={settings.error} retry={() => settings.refetch()} />
    );

  const phrase = settings.data.confirmation_phrase;

  async function preview(leadId: number) {
    setSelected(leadId);
    setConfirmation("");
    const result = await action.run(() =>
      post<Plan>(`/leads/${leadId}/crm/preview`, { include_note: true }),
    );
    if (result) setPlan(result);
  }

  async function push(leadId: number) {
    const result = await action.run(
      () =>
        post<{
          state: string;
          reason: string | null;
          message: string;
          resimpli_lead_id: string | null;
        }>(`/leads/${leadId}/crm/push`, { confirmation, include_note: true }),
      "Push attempted",
    );
    if (result) setPlan(null);
  }

  return (
    <>
      <Panel
        title="Push Queue"
        subtitle={settings.data.write_scope}
        action={
          <div className="crm-toolbar">
            <StatusPill tone={queue.data.writes_enabled ? "ok" : "warning"}>
              {queue.data.writes_enabled ? "Writes enabled" : "Writes off"}
            </StatusPill>
            <Badge tone={queue.data.mode === "auto" ? "purple" : "neutral"}>
              {queue.data.mode} mode
            </Badge>
          </div>
        }
      >
        <div className="crm-metrics">
          <div>
            <strong>{queue.data.counts.ready}</strong>
            <span>Ready</span>
          </div>
          <div>
            <strong>{queue.data.counts.blocked}</strong>
            <span>Blocked</span>
          </div>
          <div>
            <strong>{queue.data.failed}</strong>
            <span>Failed</span>
          </div>
        </div>
        {queue.data.rows.length === 0 ? (
          <Empty
            title="Nothing waiting"
            description="Every lead is either already in the CRM or has been removed from the queue."
          />
        ) : (
          <div className="crm-table-wrap">
            <table className="crm-table">
              <caption className="crm-muted">
                Every lead that is not yet in the CRM, with the reason it is
                waiting.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Lead</th>
                  <th scope="col">Address</th>
                  <th scope="col">Status</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {queue.data.rows.map((row) => (
                  <tr key={row.lead_id}>
                    <td dir="auto">{row.full_name || "Owner unknown"}</td>
                    <td dir="auto">{row.address || "No address"}</td>
                    <td>
                      <StatusPill
                        tone={row.reason ? "warning" : crmTone(row.state)}
                      >
                        {reasonLabel(row.reason)}
                      </StatusPill>
                      {row.message && row.reason && (
                        <p className="crm-muted" dir="auto">
                          {row.message}
                        </p>
                      )}
                    </td>
                    <td>
                      <Button
                        variant="ghost"
                        onClick={() => preview(row.lead_id)}
                      >
                        <FileText size={15} />
                        Preview
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {plan && (
        <Panel
          title={`Preview for lead ${plan.lead_id}`}
          subtitle="This is the exact body that would be created. Nothing has been sent."
          action={
            <Button variant="ghost" onClick={() => setPlan(null)}>
              Close
            </Button>
          }
        >
          <div className="crm-card-body">
            <StatusPill tone={plan.eligible ? "ok" : "warning"}>
              {reasonLabel(plan.reason)}
            </StatusPill>
            <p dir="auto">{plan.message}</p>
            {plan.warnings.map((warning) => (
              <Notice key={warning} tone="warning">
                <AlertTriangle size={16} /> {warning}
              </Notice>
            ))}
            {plan.matches.length > 0 && (
              <div>
                <strong>Possible match already in the CRM</strong>
                <ul dir="auto">
                  {plan.matches.map((match) => (
                    <li key={match.resimpli_lead_id}>
                      {match.full_name || "Unnamed"} ·{" "}
                      {match.address || "no address"} (matched on{" "}
                      {match.matched_on}, id {match.resimpli_lead_id})
                    </li>
                  ))}
                </ul>
                <p className="crm-muted">
                  Nothing is created while a match exists. Link the lead instead
                  if it is the same property.
                </p>
              </div>
            )}
            {plan.note && (
              <div>
                <strong>Note that would travel in the comment</strong>
                <pre dir="auto" className="crm-note-body">
                  {plan.note}
                </pre>
              </div>
            )}
            <pre dir="ltr" className="crm-note-body crm-json">
              {JSON.stringify(plan.body, null, 2)}
            </pre>
            {plan.payload_hash && (
              <span className="crm-muted">
                Payload hash {plan.payload_hash.slice(0, 16)}…
              </span>
            )}
            {plan.eligible && (
              <div className="crm-confirm">
                <label htmlFor="crm-confirm-input">
                  Type <strong>{phrase}</strong> to create this one lead in
                  REsimpli
                </label>
                <input
                  id="crm-confirm-input"
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  autoComplete="off"
                  dir="ltr"
                />
                <Button
                  busy={action.busy}
                  disabled={
                    confirmation !== phrase || !queue.data.writes_enabled
                  }
                  onClick={() => selected !== null && push(selected)}
                >
                  <Upload size={16} />
                  Create in REsimpli
                </Button>
                {!queue.data.writes_enabled && (
                  <p className="crm-muted">
                    Writes are switched off in the environment
                    (CRM_WRITES_ENABLED).
                  </p>
                )}
              </div>
            )}
          </div>
        </Panel>
      )}
      {action.error && <Notice tone="danger">{action.error}</Notice>}
    </>
  );
}

type PushDefaults = {
  marketing_campign_id: string;
  market_id: string;
  pipeline_id: string;
  main_status_id: string;
  mode: "review" | "auto";
};

export function PushSettingsPanel() {
  const stored = useData<PushSettings>(
    "push-settings",
    "/integrations/resimpli/push/settings",
  );
  const account = useData<{
    account_options: Record<
      string,
      { error: string | null; options: unknown[] }
    >;
  }>("push-accounts", "/integrations/resimpli/push/accounts", false);
  const action = useAction();
  const [form, setForm] = useState<PushDefaults | null>(null);
  const values = form || (stored.data ? { ...stored.data.settings } : null);

  if (stored.isPending) return <Loading />;
  if (stored.isError)
    return <ErrorState error={stored.error} retry={() => stored.refetch()} />;
  if (!values) return null;

  async function save() {
    if (!values) return;
    await action.run(
      () => patch("/integrations/resimpli/push/settings", values),
      "Push settings saved",
    );
  }

  const field = (key: keyof PushDefaults, label: string) => (
    <label className="crm-field" key={key}>
      <span>{label}</span>
      <input
        value={String(values?.[key] || "")}
        dir="ltr"
        onChange={(event) =>
          setForm({ ...(values as PushDefaults), [key]: event.target.value })
        }
      />
    </label>
  );

  return (
    <Panel
      title="CRM push settings"
      subtitle="The four ObjectIds every lead needs, and the mode"
      action={
        <Button
          variant="ghost"
          busy={account.isFetching}
          onClick={() => account.refetch()}
        >
          <RefreshCw size={15} />
          Load from my account
        </Button>
      }
    >
      <div className="crm-form">
        <label className="crm-field">
          <span>Mode</span>
          <select
            value={values.mode}
            onChange={(event) =>
              setForm({
                ...values,
                mode: event.target.value as "review" | "auto",
              })
            }
          >
            <option value="review">
              Review — type the confirmation for each push
            </option>
            <option value="auto">Auto — push after an import or sync</option>
          </select>
        </label>
        {field(
          "marketing_campign_id",
          "Marketing campaign id (marketingCampignId, the API's spelling)",
        )}
        {field("market_id", "Market id (marketId)")}
        {field("pipeline_id", "Pipeline id (pipelineId)")}
        {field("main_status_id", "Main status id (mainStatusId)")}
        <Button busy={action.busy} onClick={save}>
          <Check size={16} />
          Save push settings
        </Button>
      </div>
      {account.data && (
        <div className="crm-account">
          <p className="crm-muted">
            Read-only lists from your account. Copy the id you want into the
            field above; this request writes nothing.
          </p>
          {Object.entries(account.data.account_options).map(([name, value]) => (
            <details key={name}>
              <summary>
                {name.replaceAll("_", " ")} ({value.options.length})
              </summary>
              {value.error ? (
                <Notice tone="danger">{value.error}</Notice>
              ) : (
                <pre dir="ltr" className="crm-note-body crm-json">
                  {JSON.stringify(value.options.slice(0, 20), null, 2)}
                </pre>
              )}
            </details>
          ))}
        </div>
      )}
      {action.error && <Notice tone="danger">{action.error}</Notice>}
    </Panel>
  );
}

type GrokStatus = {
  enabled: boolean;
  key_configured: boolean;
  used: number;
  limit: number;
  remaining: number;
  exhausted: boolean;
  api: string;
  models: Record<string, string>;
  monthly_estimate: { basis: string; monthly_usd: number; note?: string };
  fields: { key: string; label: string }[];
  enabled_fields: string[];
  disclaimer: string;
  compliance: string;
};

export function GrokStatusPanel() {
  const status = useData<GrokStatus>(
    "grok-status",
    "/integrations/grok/status",
  );
  if (status.isPending) return <Loading />;
  if (status.isError)
    return <ErrorState error={status.error} retry={() => status.refetch()} />;
  const data = status.data;
  return (
    <Panel
      title="Grok (xAI)"
      subtitle="Drafts, checklist suggestions and advisor notes only"
      action={
        <StatusPill
          tone={data.enabled ? (data.exhausted ? "warning" : "ok") : "neutral"}
        >
          {data.enabled
            ? data.exhausted
              ? "Daily cap reached"
              : "Enabled"
            : "Off"}
        </StatusPill>
      }
    >
      <div className="crm-metrics">
        <div>
          <strong>
            {data.used}/{data.limit}
          </strong>
          <span>calls today</span>
        </div>
        <div>
          <strong>${data.monthly_estimate.monthly_usd.toFixed(2)}</strong>
          <span>
            {data.monthly_estimate.basis === "observed_last_30_days"
              ? "observed / month"
              : "estimated / month"}
          </span>
        </div>
        <div>
          <strong>{data.api}</strong>
          <span>API surface</span>
        </div>
      </div>
      <ul className="crm-facts">
        <li>
          <Bot size={15} /> Advisor model <code>{data.models.advisor}</code>
        </li>
        <li>
          <Sparkles size={15} /> Follow-up and checklist model{" "}
          <code>{data.models.followup_draft}</code>
        </li>
        <li>
          <DatabaseZap size={15} /> Fields allowed to leave this machine:{" "}
          {data.enabled_fields.join(", ") || "none"}
        </li>
        <li>
          <MessageSquareText size={15} /> Drafts are copy-only; no message can
          be sent from this application.
        </li>
        <li>
          <ShieldCheck size={15} /> {data.disclaimer}
        </li>
      </ul>
      {data.monthly_estimate.note && (
        <p className="crm-muted">{data.monthly_estimate.note}</p>
      )}
    </Panel>
  );
}

type IntegrationSummary = {
  push_queue: { ready: number; blocked: number; total: number };
  failed_syncs: number;
  checklists_due: { open_items: number; leads_due: number };
  advisor_ready: number;
  notes_blocked: number;
};

export function IntegrationWidgets() {
  const summary = useData<IntegrationSummary>(
    "integration-summary",
    "/dashboard/integrations",
  );
  if (summary.isPending) return <Loading />;
  if (summary.isError)
    return <ErrorState error={summary.error} retry={() => summary.refetch()} />;
  const data = summary.data;
  if (!data?.push_queue || !data.checklists_due)
    return (
      <Notice tone="warning">
        The CRM counters are unavailable on this server, so nothing is shown
        rather than a misleading zero.
      </Notice>
    );
  const widget = (
    label: string,
    value: number,
    tone: StatusTone,
    hint: string,
    to?: string,
  ) => (
    <div className={`crm-widget crm-widget-${tone}`} key={label}>
      <span className="crm-widget-label">{label}</span>
      <strong>{value}</strong>
      <span className="crm-muted">{hint}</span>
      {to && (
        <a className="crm-widget-link" href={to}>
          Open
        </a>
      )}
    </div>
  );
  return (
    <Panel
      title="CRM and AI"
      subtitle="What is waiting, and what needs a person"
    >
      <div className="crm-widgets">
        {widget(
          "Push queue ready",
          data.push_queue.ready,
          data.push_queue.ready ? "info" : "neutral",
          "leads that can be created",
          "/crm",
        )}
        {widget(
          "Failed syncs",
          data.failed_syncs,
          data.failed_syncs ? "danger" : "ok",
          "creates that need a check",
          "/crm",
        )}
        {widget(
          "Checklists due",
          data.checklists_due.leads_due,
          data.checklists_due.leads_due ? "warning" : "ok",
          `${data.checklists_due.open_items} open items`,
        )}
        {widget(
          "Advisor ready",
          data.advisor_ready,
          data.advisor_ready ? "ok" : "neutral",
          "leads with an advisor note",
        )}
        {widget(
          "Notes blocked",
          data.notes_blocked,
          data.notes_blocked ? "warning" : "ok",
          "kept locally: no note endpoint",
        )}
      </div>
    </Panel>
  );
}

export function CrmQueuePage() {
  return (
    <>
      <header className="crm-page-head">
        <h1>CRM and AI</h1>
        <p>
          One CRM write exists in this application: creating a lead. Notes
          travel with the create, or wait locally because REsimpli documents no
          note endpoint. The AI writes drafts, checklists and decision support
          for a person to review.
        </p>
      </header>
      <PushSettingsPanel />
      <PushQueuePanel />
      <GrokStatusPanel />
    </>
  );
}

export const crmIcons = { CircleAlert, Clipboard };
