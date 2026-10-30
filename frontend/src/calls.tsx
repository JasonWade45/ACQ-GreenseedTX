import { useState } from "react";
import type { FormEvent } from "react";
import { Copy, PhoneCall, Plus, Send, Tag, X } from "lucide-react";
import {
  Button,
  Field,
  Loading,
  Modal,
  Notice,
  Panel,
  ErrorState,
  useAction,
  useData,
} from "./components";
import { api, dateTime, del, post } from "./api";

type Call = {
  id: number;
  outcome: string;
  label: string;
  direction: string;
  duration_seconds: number | null;
  notes: string | null;
  next_step: string | null;
  occurred_at: string;
};

type CallsResponse = {
  items: Call[];
  outcomes: { code: string; label: string }[];
  suggestion: {
    should_schedule: boolean;
    reason: string;
    followup_type: string | null;
    due_at: string | null;
  } | null;
};

type Script = {
  objective: string;
  steps: { step_number: number; title: string; content: string; tips: string }[];
  key_objections: { objection: string; response: string }[];
  next_step: string;
};

export function CallsPanel({ leadId }: { leadId: number }) {
  const query = useData<CallsResponse>(`calls-${leadId}`, `/leads/${leadId}/conversations`);
  const action = useAction();
  const [outcome, setOutcome] = useState("connected");
  const [duration, setDuration] = useState("");
  const [notes, setNotes] = useState("");
  const [nextStep, setNextStep] = useState("");
  const [script, setScript] = useState<Script | null>(null);
  const [scriptBusy, setScriptBusy] = useState(false);

  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => query.refetch()} />;
  const data = query.data;

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ok = await action.run(
      () =>
        post(`/leads/${leadId}/conversations`, {
          outcome,
          duration_seconds: duration ? Number(duration) : null,
          notes: notes || null,
          next_step: nextStep || null,
        }),
      "Call recorded",
    );
    if (ok) {
      setNotes("");
      setNextStep("");
      setDuration("");
    }
  }

  async function openScript() {
    setScriptBusy(true);
    try {
      const result = await api<{ script: Script }>(`/leads/${leadId}/conversations/script`);
      setScript(result.script);
    } finally {
      setScriptBusy(false);
    }
  }

  return (
    <div className="stack">
      <Notice tone="info">
        <strong>Call log.</strong> Record a conversation that already happened. The app
        suggests the next step and creates a local follow-up; it never dials, texts or
        writes to the CRM.
      </Notice>
      <Panel
        title="Record a call"
        subtitle="The outcome decides the next follow-up date. Nothing is scheduled silently."
        action={
          <Button variant="secondary" onClick={openScript} disabled={scriptBusy}>
            <PhoneCall size={16} />
            {scriptBusy ? "Building script…" : "Live call script"}
          </Button>
        }
      >
        <form className="form-stack" onSubmit={submit}>
          <Field label="Outcome">
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              {data.outcomes.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Duration (seconds, optional)">
            <input
              type="number"
              min={0}
              max={86400}
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
              placeholder="e.g. 240"
            />
          </Field>
          <Field label="What happened" hint="The seller's own words are more useful than a summary.">
            <textarea
              rows={3}
              maxLength={20000}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Wants to close before spring; roof is older; asked for a number."
            />
          </Field>
          <Field label="Next step you promised (optional)">
            <input
              value={nextStep}
              maxLength={2000}
              onChange={(e) => setNextStep(e.target.value)}
              placeholder="Call back Thursday after 4 pm"
            />
          </Field>
          {action.error && <p className="form-error">{action.error}</p>}
          <Button type="submit" disabled={action.busy}>
            <Plus size={16} />
            {action.busy ? "Saving…" : "Save call"}
          </Button>
        </form>
        {data.suggestion && (
          <p className="panel-footnote">
            Last outcome: <strong>{data.suggestion.reason}</strong>
            {data.suggestion.should_schedule && data.suggestion.due_at
              ? ` Next follow-up: ${dateTime(data.suggestion.due_at)}.`
              : " No follow-up was scheduled."}
          </p>
        )}
      </Panel>

      <Panel title={`Call history (${data.items.length})`}>
        {data.items.length === 0 ? (
          <p className="muted">No calls recorded yet.</p>
        ) : (
          <div className="stack">
            {data.items.map((call) => (
              <article key={call.id} className="panel" style={{ padding: "0.9rem" }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <strong>{call.label}</strong>
                  <span className="muted">{dateTime(call.occurred_at)}</span>
                </div>
                {call.notes && <p>{call.notes}</p>}
                {call.next_step && <p className="muted">Next step: {call.next_step}</p>}
                {call.duration_seconds != null && (
                  <p className="muted">Duration: {call.duration_seconds}s</p>
                )}
              </article>
            ))}
          </div>
        )}
      </Panel>

      {script && (
        <Modal title="Live call script" subtitle={script.objective} onClose={() => setScript(null)}>
          <div className="stack">
            {script.steps.map((step) => (
              <div key={step.step_number} className="panel" style={{ padding: "0.9rem" }}>
                <strong>
                  {step.step_number}. {step.title}
                </strong>
                <p>{step.content}</p>
                <p className="muted">Tip: {step.tips}</p>
              </div>
            ))}
            <h3>Likely objections</h3>
            {script.key_objections.map((item) => (
              <div key={item.objection}>
                <strong>{item.objection}</strong>
                <p>{item.response}</p>
              </div>
            ))}
            <p className="panel-footnote">{script.next_step}</p>
          </div>
        </Modal>
      )}
    </div>
  );
}

type LeadTag = { id: number; tag: string };

export function TagsPanel({ leadId }: { leadId: number }) {
  const query = useData<LeadTag[]>(`tags-${leadId}`, `/leads/${leadId}/tags`);
  const action = useAction();
  const [value, setValue] = useState("");

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    const ok = await action.run(
      () => post(`/leads/${leadId}/tags`, { tag: value.trim() }),
      "Tag added",
    );
    if (ok) setValue("");
  }

  if (query.isPending) return null;
  if (query.isError) return null;
  const tags = Array.isArray(query.data) ? query.data : [];

  return (
    <Panel
      title="Tags"
      subtitle="Local labels for filtering and export. They never leave this machine."
    >
      <div className="row" style={{ flexWrap: "wrap", gap: "0.4rem", marginBottom: "0.75rem" }}>
        {tags.length === 0 && <span className="muted">No tags yet.</span>}
        {tags.map((tag) => (
          <span key={tag.id} className="badge badge-neutral" style={{ gap: "0.35rem" }}>
            <Tag size={12} />
            {tag.tag}
            <button
              type="button"
              aria-label={`Remove ${tag.tag}`}
              onClick={() => action.run(() => del(`/leads/${leadId}/tags/${tag.id}`), "Tag removed")}
              style={{ border: 0, background: "transparent", cursor: "pointer", padding: 0 }}
            >
              <X size={12} />
            </button>
          </span>
        ))}
      </div>
      <form className="row" onSubmit={add} style={{ gap: "0.5rem" }}>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="e.g. probate"
          maxLength={60}
          aria-label="New tag"
        />
        <Button type="submit" variant="secondary" disabled={action.busy || !value.trim()}>
          Add tag
        </Button>
      </form>
    </Panel>
  );
}


type PreviewPlan = {
  eligible: boolean;
  reason: string | null;
  message: string;
  body: Record<string, unknown> | null;
  matches: { full_name: string | null; address: string | null }[];
};

export function ScriptPanel({ leadId }: { leadId: number }) {
  const query = useData<{ script: Script; text: string }>(
    `script-${leadId}`,
    `/leads/${leadId}/script`,
  );
  const action = useAction();
  const [preview, setPreview] = useState<PreviewPlan | null>(null);
  const [confirmation, setConfirmation] = useState("");

  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} retry={() => query.refetch()} />;
  const { script, text } = query.data;

  async function previewPush() {
    const result = await action.run(
      () => post<PreviewPlan>(`/leads/${leadId}/crm/preview`, { include_note: true, note: text }),
      "CRM preview ready",
    );
    if (result) setPreview(result);
  }

  async function push() {
    const result = await action.run(
      () =>
        post(`/leads/${leadId}/crm/push`, {
          include_note: true,
          note: text,
          confirmation,
        }),
      "Push attempted",
    );
    if (result) {
      setPreview(null);
      setConfirmation("");
    }
  }

  return (
    <div className="stack">
      <Notice tone="info">
        <strong>Call script.</strong> Built only from this lead's recorded facts; it never
        invents an ARV, repair number or offer. Saving it creates a local note. Pushing
        sends it only as the CRM lead-creation comment.
      </Notice>
      <Panel
        title={script.objective}
        action={
          <div className="row" style={{ gap: "0.4rem" }}>
            <Button
              variant="secondary"
              onClick={() => navigator.clipboard?.writeText(text)}
            >
              <Copy size={15} />
              Copy
            </Button>
            <Button
              variant="secondary"
              onClick={() =>
                action.run(() => post(`/leads/${leadId}/script`, { save: true }), "Script saved as a note")
              }
              disabled={action.busy}
            >
              Save as note
            </Button>
            <Button variant="secondary" onClick={previewPush} disabled={action.busy}>
              <Send size={15} />
              Preview CRM push
            </Button>
          </div>
        }
      >
        {script.steps.map((step) => (
          <div key={step.step_number} className="panel" style={{ padding: "0.9rem" }}>
            <strong>
              {step.step_number}. {step.title}
            </strong>
            <p>{step.content}</p>
            <p className="muted">Tip: {step.tips}</p>
          </div>
        ))}
        <h3>Likely objections</h3>
        {script.key_objections.map((item) => (
          <div key={item.objection}>
            <strong>{item.objection}</strong>
            <p>{item.response}</p>
          </div>
        ))}
        <p className="panel-footnote">{script.next_step}</p>
      </Panel>

      {preview && (
        <Panel title="CRM push preview" subtitle="Nothing is sent until you type the confirmation.">
          <p>{preview.message}</p>
          {preview.matches.length > 0 && (
            <Notice tone="warning">
              A matching CRM lead exists. Link it instead of creating a duplicate.
            </Notice>
          )}
          {preview.body && (
            <pre style={{ maxHeight: 240, overflow: "auto", fontSize: "0.75rem" }}>
              {JSON.stringify(preview.body, null, 2)}
            </pre>
          )}
          {preview.eligible ? (
            <div className="row" style={{ gap: "0.5rem", marginTop: "0.75rem" }}>
              <input
                aria-label="CRM confirmation"
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
                placeholder="Type PUSH TO CRM"
              />
              <Button onClick={push} disabled={action.busy || confirmation !== "PUSH TO CRM"}>
                Push this lead with the script
              </Button>
            </div>
          ) : (
            <p className="muted">
              Reason: {preview.reason || "Not eligible"}. Configure the CRM push in CRM & AI first.
            </p>
          )}
        </Panel>
      )}
    </div>
  );
}
