import { createContext, useContext, useEffect, useRef, useState } from "react";
import type {
  ReactNode,
  ButtonHTMLAttributes,
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Inbox,
  LoaderCircle,
  X,
} from "lucide-react";
import { api, dateTime, human, isoFromLocal, post } from "./api";
import type { Meta, Followup } from "./types";

export const WorkspaceContext = createContext<{
  meta: Meta;
  toast: (message: string, tone?: "success" | "error") => void;
}>({
  meta: {
    stages: [],
    outcomes: [],
    import_fields: {},
    timezone: "America/New_York",
    mode: "disabled",
    sources: [],
    managers: [],
    communication: "",
  },
  toast: () => {},
});
export const useWorkspace = () => useContext(WorkspaceContext);
export function useData<T>(key: string, path: string, enabled = true) {
  return useQuery({
    queryKey: [key, path],
    queryFn: () => api<T>(path),
    enabled,
  });
}
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { toast } = useWorkspace();
  const client = useQueryClient();
  async function run<T>(
    fn: () => Promise<T>,
    message?: string,
  ): Promise<T | undefined> {
    setBusy(true);
    setError("");
    try {
      const value = await fn();
      await client.invalidateQueries();
      if (message) toast(message);
      return value;
    } catch (e) {
      const text =
        e instanceof Error ? e.message : "This action could not be completed";
      setError(text);
      toast(text, "error");
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return { run, busy, error, setError };
}
export function Button({
  children,
  className = "",
  busy = false,
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  busy?: boolean;
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button
      {...props}
      disabled={busy || props.disabled}
      className={`btn btn-${variant} ${className}`}
    >
      {busy && <LoaderCircle size={15} className="spin" />}
      {children}
    </button>
  );
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
export function StageBadge({ code }: { code: string }) {
  const { meta } = useWorkspace();
  return (
    <Badge
      tone={
        ["closed", "under_contract", "qualified"].includes(code)
          ? "green"
          : ["offer_made", "negotiation", "contract_sent"].includes(code)
            ? "purple"
            : code === "dead"
              ? "neutral"
              : code === "new"
                ? "blue"
                : "teal"
      }
    >
      {meta.stages.find((s) => s.code === code)?.label || human(code)}
    </Badge>
  );
}
export function RestrictionBadge({ status }: { status: string }) {
  return status === "do_not_contact" ? (
    <Badge tone="red">Do Not Contact</Badge>
  ) : status === "unknown" ? (
    <Badge tone="amber">Permission review</Badge>
  ) : (
    <Badge tone="green">Restriction reviewed</Badge>
  );
}
export function Notice({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return (
    <div className={`notice notice-${tone}`}>
      <AlertCircle size={17} />
      <div>{children}</div>
    </div>
  );
}
export function ErrorState({
  error,
  retry,
}: {
  error: Error | null;
  retry?: () => void;
}) {
  return (
    <div className="error-state" role="alert">
      <AlertCircle size={24} />
      <h3>We couldn’t load this view</h3>
      <p>{error?.message || "The local server is unavailable."}</p>
      {retry && (
        <Button variant="secondary" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading workspace-skeleton" role="status">
      <div className="loading-label">
        <LoaderCircle size={19} className="spin" />
        <span>Loading your workspace…</span>
      </div>
      <div className="skeleton-title" aria-hidden="true" />
      <div className="skeleton-cards" aria-hidden="true">
        <i />
        <i />
        <i />
        <i />
      </div>
      <div className="skeleton-panel" aria-hidden="true" />
    </div>
  );
}
export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <Inbox size={27} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="heading-actions">{actions}</div>
    </div>
  );
}
export function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function CountLink({
  value,
  label,
  to = "/leads",
}: {
  value: number;
  label: string;
  to?: string;
}) {
  return (
    <Link className="count-link" to={to}>
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
      <ArrowUpRight size={14} />
    </Link>
  );
}
export function Pagination({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onChange: (p: number) => void;
}) {
  return (
    <div className="pagination">
      <span>
        {total
          ? `${((page - 1) * pageSize + 1).toLocaleString()}–${Math.min(page * pageSize, total).toLocaleString()} of ${total.toLocaleString()}`
          : "0 records"}
      </span>
      <div className="row">
        <Button
          variant="secondary"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
        >
          <ChevronLeft size={15} />
        </Button>
        <span>
          Page {page} of {Math.max(1, Math.ceil(total / pageSize))}
        </span>
        <Button
          variant="secondary"
          aria-label="Next page"
          disabled={page * pageSize >= total}
          onClick={() => onChange(page + 1)}
        >
          <ChevronRight size={15} />
        </Button>
      </div>
    </div>
  );
}
export function Modal({
  title,
  subtitle,
  children,
  onClose,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const autofocus =
      ref.current?.querySelector<HTMLElement>("[data-autofocus]");
    if (autofocus) autofocus.focus();
    else ref.current?.focus();
    return () => previous?.focus();
  }, []);
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          if (e.key === "Tab") {
            const all = ref.current?.querySelectorAll<HTMLElement>(
              'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]',
            );
            if (all?.length) {
              const first = all[0],
                last = all[all.length - 1];
              if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
              } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
              }
            }
          }
        }}
      >
        <div className="modal-heading">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function Info({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="info-field">
      <span>{label}</span>
      <div>{children || <span className="muted">Not recorded</span>}</div>
    </div>
  );
}
export function FollowupDialog({
  followup,
  mode,
  onClose,
}: {
  followup: Followup;
  mode: "complete" | "reschedule" | "cancel";
  onClose: () => void;
}) {
  const { meta } = useWorkspace();
  const action = useAction();
  const [outcome, setOutcome] = useState("");
  const [note, setNote] = useState("");
  const [due, setDue] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const result = await action.run(
      () =>
        post(`/followups/${followup.id}/action`, {
          action: mode,
          outcome: outcome || null,
          note,
          due_at: isoFromLocal(due),
          confirm: confirmed,
        }),
      `Follow-up ${mode === "complete" ? "completed" : mode === "reschedule" ? "rescheduled" : "cancelled"} locally`,
    );
    if (result) onClose();
  }
  return (
    <Modal
      title={`${human(mode)} follow-up`}
      subtitle={followup.reason}
      onClose={onClose}
    >
      <form onSubmit={submit} className="form-stack">
        <Notice>
          Recording a completion does not mean a call or message occurred.
          Nothing is sent by this app.
        </Notice>
        {mode === "complete" && (
          <>
            <Field label="Actual outcome">
              <select
                required
                value={outcome}
                onChange={(e) => setOutcome(e.target.value)}
              >
                <option value="">Select the actual outcome</option>
                {meta.outcomes.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            </Field>
            <Field label="Outcome notes">
              <textarea
                value={note}
                required={outcome === "Other"}
                onChange={(e) => setNote(e.target.value)}
                placeholder="What actually happened?"
              />
            </Field>
          </>
        )}
        {mode === "reschedule" && (
          <Field
            label="New date and time"
            hint="Enter in this browser’s local timezone. Stored in UTC; queues use the business timezone."
          >
            <input
              type="datetime-local"
              required
              value={due}
              onChange={(e) => setDue(e.target.value)}
            />
          </Field>
        )}
        <label className="checkbox-label">
          <input
            type="checkbox"
            required
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          I confirm this local-only{" "}
          {mode === "complete"
            ? "outcome"
            : mode === "cancel"
              ? "cancellation"
              : "schedule change"}
          .
        </label>
        {action.error && <Notice tone="danger">{action.error}</Notice>}
        <div className="modal-actions">
          <Button type="button" variant="secondary" onClick={onClose}>
            Keep unchanged
          </Button>
          <Button
            busy={action.busy}
            variant={mode === "cancel" ? "danger" : "primary"}
            type="submit"
          >
            {mode === "complete" ? <Check size={16} /> : null}Confirm {mode}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
export function FollowupCreate({
  leadId,
  onClose,
}: {
  leadId: number;
  onClose: () => void;
}) {
  const action = useAction();
  const [due, setDue] = useState("");
  const [reason, setReason] = useState("");
  const [priority, setPriority] = useState(50);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const r = await action.run(
      () =>
        post("/followups", {
          lead_id: leadId,
          due_at: isoFromLocal(due),
          reason,
          priority,
        }),
      "Follow-up added locally",
    );
    if (r) onClose();
  }
  return (
    <Modal
      title="Schedule a follow-up"
      subtitle="A local task — never automated outreach."
      onClose={onClose}
    >
      <form onSubmit={submit} className="form-stack">
        <Field label="Why is a follow-up needed?">
          <textarea
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reference an explicit request or your next internal step."
          />
        </Field>
        <Field
          label="Due date and time (optional)"
          hint="Browser local time. Leave blank to keep this task unscheduled, not overdue."
        >
          <input
            type="datetime-local"
            value={due}
            onChange={(e) => setDue(e.target.value)}
          />
        </Field>
        <Field label="Business priority (0–100)">
          <input
            type="number"
            min="0"
            max="100"
            value={priority}
            onChange={(e) => setPriority(Number(e.target.value))}
          />
        </Field>
        <div className="modal-actions">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={action.busy}>Create local task</Button>
        </div>
      </form>
    </Modal>
  );
}
export function EvidenceList({
  records,
}: {
  records: { ref: string; text: string }[];
}) {
  return (
    <details className="evidence">
      <summary>Review source context ({records.length} records)</summary>
      <div>
        {records.map((r, i) => (
          <div key={r.ref + ":" + i}>
            <code>{r.ref}</code>
            <p>{r.text}</p>
          </div>
        ))}
      </div>
    </details>
  );
}
export function Timestamp({
  value,
  dateOnly = false,
}: {
  value: string | null;
  dateOnly?: boolean;
}) {
  const { meta } = useWorkspace();
  return <>{dateTime(value, meta.timezone, dateOnly)}</>;
}

export function navigateTabs(event: ReactKeyboardEvent<HTMLElement>) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = Array.from(
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
  );
  if (!tabs.length) return;
  const current = Math.max(
    0,
    tabs.findIndex((tab) => tab === document.activeElement),
  );
  const next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) %
          tabs.length;
  event.preventDefault();
  tabs[next].focus();
  tabs[next].click();
}
