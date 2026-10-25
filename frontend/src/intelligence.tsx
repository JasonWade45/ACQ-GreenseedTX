import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Check,
  CheckCheck,
  Clipboard,
  Cloud,
  FileText,
  KeyRound,
  LockKeyhole,
  RefreshCw,
  Save,
  ShieldCheck,
  Sparkles,
  Unplug,
} from "lucide-react";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Loading,
  Modal,
  Notice,
  Panel,
  Timestamp,
  useAction,
  useData,
  useWorkspace,
} from "./components";
import { human, patch, post } from "./api";
import type {
  CloudPurpose,
  CloudReview,
  IntegrationStatus,
  LeadProfile,
} from "./types";

const PURPOSES: Record<
  CloudPurpose,
  { label: string; button: string; description: string }
> = {
  analyze: {
    label: "Evidence-based analysis",
    button: "Analyze with Groq",
    description:
      "Extract supported facts, flag contradictions and list what is still unknown.",
  },
  notes: {
    label: "Organize source notes",
    button: "Organize notes",
    description:
      "Turn available notes into a clear proposal without replacing the originals.",
  },
  draft: {
    label: "Human-reviewed follow-up draft",
    button: "Draft with Groq",
    description:
      "Prepare natural American English from verified callback or motivation context. Nothing is sent to a seller.",
  },
};

function CredentialForm({
  provider,
  configured,
}: {
  provider: "groq" | "resimpli";
  configured: boolean;
}) {
  const action = useAction();
  const [key, setKey] = useState("");
  const [consent, setConsent] = useState(false);
  const [remove, setRemove] = useState(false);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    const result = await action.run(
      () =>
        post("/integrations/credentials", {
          provider,
          api_key: key,
          confirm_private_storage: consent,
        }),
      "Replacement key saved on the backend",
    );
    if (result) {
      setKey("");
      setConsent(false);
    }
  }
  return (
    <div className="credential-block">
      <form onSubmit={save} className="form-stack">
        <Field
          label={`Replacement ${provider === "groq" ? "Groq" : "REsimpli"} API key`}
          hint="Never re-use a key exposed in chat. It is not returned or saved in browser storage."
        >
          <input
            type="password"
            autoComplete="new-password"
            spellCheck={false}
            value={key}
            onChange={(event) => setKey(event.target.value)}
            placeholder={
              configured
                ? "A key is saved. Enter a replacement to rotate it."
                : "Paste a replacement key locally"
            }
            required
            minLength={16}
          />
        </Field>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
          />
          I authorize private backend storage on this machine.
        </label>
        <div className="row wrap">
          <Button
            type="submit"
            busy={action.busy}
            disabled={!consent || key.length < 16}
          >
            <KeyRound size={14} />
            Save private key
          </Button>
          {configured && (
            <Button
              variant="ghost"
              type="button"
              onClick={() => setRemove(!remove)}
            >
              <Unplug size={14} />
              Remove saved key
            </Button>
          )}
        </div>
      </form>
      {remove && (
        <Notice tone="warning">
          <p>
            Remove the saved backend key? Environment-variable overrides may
            remain active.
          </p>
          <Button
            variant="danger"
            busy={action.busy}
            onClick={async () => {
              const result = await action.run(
                () =>
                  post("/integrations/credentials", {
                    provider,
                    action: "remove",
                    confirm_private_storage: true,
                  }),
                "Saved key removed",
              );
              if (result) setRemove(false);
            }}
          >
            Confirm key removal
          </Button>
        </Notice>
      )}
      {action.error && <Notice tone="warning">{action.error}</Notice>}
    </div>
  );
}

export function IntegrationSettings() {
  const query = useData<IntegrationStatus>("integrations", "/integrations");
  if (query.isPending) return <Loading />;
  if (query.isError)
    return <ErrorState error={query.error} retry={() => query.refetch()} />;
  if (!query.data.groq || !query.data.resimpli)
    return (
      <Notice tone="warning">
        Integration settings are unavailable. Refresh after updating the
        backend.
      </Notice>
    );
  return (
    <div className="integration-section" id="connections">
      <div className="section-intro">
        <div>
          <span className="eyebrow">CONNECTIONS, WITH GUARDRAILS</span>
          <h2>Your intelligence & source of truth</h2>
          <p>
            Private keys stay on the backend. You decide exactly when context
            leaves this device.
          </p>
        </div>
        <Badge tone="green">
          <ShieldCheck size={12} />
          No seller communication
        </Badge>
      </div>
      <div className="integration-grid">
        <GroqSettings status={query.data} />
        <ResimpliSettings status={query.data} />
      </div>
      <div className="private-storage-note">
        <LockKeyhole size={15} />
        <span>
          Saved in ignored <code>.env.secrets</code>, not in the ZIP, database
          or browser storage. This is a private plaintext file: protect it with
          OS permissions and disk encryption.
        </span>
      </div>
    </div>
  );
}

function GroqSettings({ status }: { status: IntegrationStatus }) {
  const s = status.groq;
  const action = useAction();
  const [enabled, setEnabled] = useState(s.enabled);
  const [model, setModel] = useState(s.model);
  const [limit, setLimit] = useState(s.daily_limit);
  const [tokens, setTokens] = useState(s.max_output_tokens);
  return (
    <Panel
      title="Groq cloud intelligence"
      subtitle="Reviewed context. Structured answers. No autonomous actions."
      className="connection-card"
      action={
        <div className="connection-mark groq-mark">
          <Sparkles size={24} />
        </div>
      }
    >
      <div className="connection-status">
        <Badge tone={s.enabled ? "purple" : "neutral"}>
          {s.enabled ? "Enabled · approval required" : "Cloud disabled"}
        </Badge>
        <Badge tone={s.key_configured ? "green" : "amber"}>
          {s.key_configured ? "Key saved" : "Key required"}
        </Badge>
        <Badge tone={s.validated ? "green" : "neutral"}>
          {s.validated ? "Model access checked" : "Access not checked"}
        </Badge>
      </div>
      <div className="cloud-policy">
        <ShieldCheck size={21} />
        <div>
          <strong>Redact → review → approve</strong>
          <p>
            No cloud analysis during sync. Every request needs its own preview
            and explicit approval. Redaction is not a guarantee—review the text.
          </p>
        </div>
      </div>
      {status.environment_overrides.groq && (
        <Notice tone="warning">
          Runtime environment variables override some Groq settings. Update
          those variables and restart if a saved change is not effective.
        </Notice>
      )}
      <CredentialForm provider="groq" configured={s.key_configured} />
      <div className="connection-actions">
        <Button
          variant="secondary"
          busy={action.busy}
          disabled={!s.key_configured}
          onClick={() =>
            action.run(
              () => post("/integrations/groq/test", { confirm: true }),
              "Model-list access checked. No seller context was transmitted.",
            )
          }
        >
          <RefreshCw size={14} />
          Test key · no seller data
        </Button>
      </div>
      <form
        className="provider-config"
        onSubmit={(event) => {
          event.preventDefault();
          action.run(
            () =>
              patch("/integrations/groq", {
                enabled,
                model,
                daily_request_limit: limit,
                max_output_tokens: tokens,
              }),
            "Groq configuration saved",
          );
        }}
      >
        <Field label="Structured-output model">
          <select
            value={model}
            onChange={(event) => setModel(event.target.value)}
          >
            {(s.supported_models || []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </Field>
        <div className="info-grid">
          <Field label="UTC daily request cap">
            <input
              type="number"
              min={1}
              max={500}
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
            />
          </Field>
          <Field label="Max output tokens / request">
            <input
              type="number"
              min={512}
              max={4096}
              value={tokens}
              onChange={(event) => setTokens(Number(event.target.value))}
            />
          </Field>
        </div>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={enabled}
            disabled={!s.key_configured}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          Enable manually approved Groq requests
        </label>
        <div className="row wrap">
          <Button variant="secondary" busy={action.busy}>
            <Save size={14} />
            Save AI configuration
          </Button>
          <Badge>
            {s.used_today} / {s.daily_limit} requests used today
          </Badge>
        </div>
      </form>
      {action.error && <Notice tone="warning">{action.error}</Notice>}
      <p className="connection-disclaimer">
        Groq is an external provider. Availability, free-tier limits and billing
        depend on your account. The app caps requests/tokens; it does not
        guarantee zero provider charges.
      </p>
    </Panel>
  );
}

function ResimpliSettings({ status }: { status: IntegrationStatus }) {
  const s = status.resimpli;
  const action = useAction();
  const [adapter, setAdapter] = useState("");
  const [verified, setVerified] = useState(false);
  const [confirm, setConfirm] = useState("");
  return (
    <Panel
      title="REsimpli CRM"
      subtitle="Your primary CRM. Documented seller reads only."
      className="connection-card"
      action={
        <div className="connection-mark crm-mark">
          <Cloud size={24} />
        </div>
      }
    >
      <div className="connection-status">
        <Badge tone={s.mode === "live" ? "green" : "neutral"}>
          {human(s.mode)} mode
        </Badge>
        <Badge tone={s.key_configured ? "green" : "amber"}>
          {s.key_configured ? "Key saved" : "Key required"}
        </Badge>
        <Badge tone={s.adapter_verified ? "green" : "amber"}>
          {s.adapter_verified
            ? "Adapter asserted verified"
            : "Adapter unverified"}
        </Badge>
      </div>
      <div className="crm-steps">
        <span className={s.key_configured ? "done" : ""}>
          <Check size={12} />
          Private key
        </span>
        <span className={s.adapter_verified ? "done" : ""}>
          <Check size={12} />
          Account adapter
        </span>
        <span className={s.validated ? "done" : ""}>
          <Check size={12} />
          Read check
        </span>
      </div>
      <Notice>
        Saving a key does not prove account integration. The public request
        catalog does not define your response fields. Verify the adapter against
        authorized account responses first.
      </Notice>
      {status.environment_overrides.resimpli && (
        <Notice tone="warning">
          A runtime environment override is active. Restart with updated
          environment values if mode/key changes do not take effect.
        </Notice>
      )}
      <CredentialForm provider="resimpli" configured={s.key_configured} />
      <details className="adapter-editor">
        <summary>Configure a verified private response adapter</summary>
        <div className="form-stack">
          <p>
            Paste only the response-mapping JSON—not API keys or actual seller
            records. The fictional fixture adapter cannot be marked live.
          </p>
          <Field label="Private REsimpli response adapter JSON">
            <textarea
              rows={8}
              className="code-editor"
              spellCheck={false}
              value={adapter}
              onChange={(event) => setAdapter(event.target.value)}
              placeholder="Use the account-verified adapter described in the integration guide."
            />
          </Field>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={verified}
              onChange={(event) => setVerified(event.target.checked)}
            />
            I verified these paths and semantics against actual authorized
            account responses, not the fixtures.
          </label>
          <Button
            variant="secondary"
            busy={action.busy}
            disabled={!adapter || !verified}
            onClick={async () => {
              const result = await action.run(
                () =>
                  post("/integrations/resimpli/adapter", {
                    adapter_json: adapter,
                    confirm_verified_against_account: verified,
                  }),
                "Private adapter saved",
              );
              if (result) {
                setAdapter("");
                setVerified(false);
              }
            }}
          >
            <Save size={14} />
            Save verified adapter
          </Button>
        </div>
      </details>
      <div className="connection-actions">
        <Button
          variant="secondary"
          busy={action.busy}
          disabled={!s.key_configured || !s.adapter_verified}
          onClick={() =>
            action.run(
              () => post("/integrations/resimpli/test", { confirm: true }),
              "Read response matched your adapter. Full seller sync still needs reconciliation.",
            )
          }
        >
          <RefreshCw size={14} />
          Check read access
        </Button>
        <Badge tone={s.validated ? "green" : "neutral"}>
          {s.validated ? "Read check passed" : "Read check pending"}
        </Badge>
      </div>
      <div className="crm-enable">
        <Field label="Type ENABLE READ ONLY to activate live reads">
          <input
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            placeholder="ENABLE READ ONLY"
          />
        </Field>
        <div className="row wrap">
          <Button
            variant="secondary"
            disabled={
              !s.key_configured ||
              !s.adapter_verified ||
              confirm !== "ENABLE READ ONLY"
            }
            busy={action.busy}
            onClick={async () => {
              const result = await action.run(
                () =>
                  patch("/integrations/resimpli", {
                    enabled: true,
                    confirmation: confirm,
                  }),
                "Live read-only mode enabled. Run a manual sync and reconcile it.",
              );
              if (result) setConfirm("");
            }}
          >
            Enable read-only mode
          </Button>
          {s.mode === "live" && (
            <Button
              variant="ghost"
              busy={action.busy}
              onClick={() =>
                action.run(
                  () => patch("/integrations/resimpli", { enabled: false }),
                  "CRM reads disabled",
                )
              }
            >
              Disable CRM reads
            </Button>
          )}
        </div>
      </div>
      {action.error && <Notice tone="warning">{action.error}</Notice>}
      <div className="connection-footer">
        <ShieldCheck size={15} />
        <span>CRM creation, edits and outreach remain disabled.</span>
        <Link to="/sync">
          Sync health <ArrowRight size={13} />
        </Link>
      </div>
    </Panel>
  );
}

export function CloudWorkbench({ lead }: { lead: LeadProfile }) {
  const integrations = useData<IntegrationStatus>(
    "integrations",
    "/integrations",
  );
  const history = useData<CloudReview[]>(
    "cloud-history",
    `/leads/${lead.id}/cloud/requests`,
  );
  const action = useAction();
  const [review, setReview] = useState<CloudReview | null>(null);
  const requests = Array.isArray(history.data) ? history.data : [];
  const latest = requests.find((item) =>
    ["completed", "completed_stale", "failed", "outcome_unknown"].includes(
      item.state,
    ),
  );
  const enabled =
    !!integrations.data?.groq?.enabled &&
    !!integrations.data?.groq?.key_configured;
  async function prepare(purpose: CloudPurpose) {
    const item = await action.run(() =>
      post<CloudReview>(`/leads/${lead.id}/cloud/preview`, { purpose }),
    );
    if (item) setReview(item);
  }
  return (
    <>
      <Panel
        title="Your reviewed AI workspace"
        subtitle="Groq can organize, analyze and draft—only after you approve the redacted context."
        className="cloud-workbench"
        action={
          <Badge tone={enabled ? "purple" : "neutral"}>
            <Sparkles size={12} />
            {enabled ? "Groq · manual review" : "Groq · setup required"}
          </Badge>
        }
      >
        <div className="cloud-workbench-top">
          <div className="cloud-workbench-icon">
            <Sparkles size={26} />
          </div>
          <div>
            <h3>More clarity. Still your decision.</h3>
            <p>
              Preview exactly what will leave this device. Names, contact
              details and known addresses are masked first. Original notes and
              CRM fields are never replaced.
            </p>
          </div>
          <Link className="btn btn-secondary" to="/settings#connections">
            <KeyRound size={14} />
            Connections
          </Link>
        </div>
        {!enabled && (
          <Notice>
            Cloud processing is off or the replacement key is not configured.
            Local rules and template drafts still work without Groq.
          </Notice>
        )}
        <div className="ai-tool-grid">
          {(
            Object.entries(PURPOSES) as [
              CloudPurpose,
              (typeof PURPOSES)[CloudPurpose],
            ][]
          ).map(([purpose, info]) => (
            <div className="ai-tool" key={purpose}>
              <div className="row">
                <span className="ai-tool-icon">
                  {purpose === "notes" ? (
                    <FileText size={19} />
                  ) : purpose === "draft" ? (
                    <Clipboard size={19} />
                  ) : (
                    <Sparkles size={19} />
                  )}
                </span>
                <strong>{info.label}</strong>
              </div>
              <p>{info.description}</p>
              <Button
                variant="secondary"
                disabled={
                  !enabled ||
                  (purpose === "draft" &&
                    lead.restriction_status !== "reviewed_clear")
                }
                busy={action.busy}
                onClick={() => prepare(purpose)}
              >
                {info.button}
                <ArrowRight size={14} />
              </Button>
            </div>
          ))}
        </div>
        {action.error && <Notice tone="warning">{action.error}</Notice>}
        {latest && (
          <div className="latest-cloud-result">
            <div className="row between wrap">
              <h3>Latest reviewed result</h3>
              <Badge tone={latest.state === "completed" ? "green" : "amber"}>
                {human(latest.state)}
              </Badge>
              <small>
                <Timestamp value={latest.completed_at} />
              </small>
            </div>
            <CloudResult key={latest.id} request={latest} lead={lead} />
          </div>
        )}
        <div className="cloud-bottom-line">
          <ShieldCheck size={14} />
          <span>
            Explicit approval every time · no background cloud jobs · no seller
            messages
          </span>
          {integrations.data?.groq && (
            <Badge>
              {integrations.data.groq.used_today}/
              {integrations.data.groq.daily_limit} daily requests
            </Badge>
          )}
        </div>
      </Panel>
      {review && (
        <CloudReviewDialog
          lead={lead}
          initial={review}
          onClose={() => setReview(null)}
        />
      )}
    </>
  );
}

function CloudReviewDialog({
  lead,
  initial,
  onClose,
}: {
  lead: LeadProfile;
  initial: CloudReview;
  onClose: () => void;
}) {
  const [review, setReview] = useState(initial);
  const [selected, setSelected] = useState(
    initial.records.map((record) => record.ref),
  );
  const [extra, setExtra] = useState("");
  const [approved, setApproved] = useState(false);
  const [fresh, setFresh] = useState(false);
  const action = useAction();
  const info = PURPOSES[review.purpose];
  const pending = review.state === "pending_review";
  async function redact() {
    const value = await action.run(() =>
      post<CloudReview>(`/leads/${lead.id}/cloud/preview`, {
        purpose: review.purpose,
        additional_redactions: extra
          .split("\n")
          .map((term) => term.trim())
          .filter(Boolean),
      }),
    );
    if (value) {
      setReview(value);
      setSelected(value.records.map((record) => record.ref));
      setApproved(false);
    }
  }
  async function execute() {
    const value = await action.run(() =>
      post<CloudReview>(`/cloud/requests/${review.id}/execute`, {
        confirmation: "SEND REVIEWED CONTEXT",
        payload_hash: review.payload_hash,
        selected_refs: selected,
        force_refresh: fresh,
      }),
    );
    if (value) {
      setReview(value);
      setApproved(false);
    }
  }
  return (
    <Modal
      title="Review before Groq"
      subtitle={info.label + " · no seller communication"}
      onClose={() => {
        if (!action.busy) onClose();
      }}
    >
      <div className="cloud-review-body">
        <div className="review-steps">
          <span className="done">1. Redacted</span>
          <span className={pending ? "active" : "done"}>2. Your approval</span>
          <span className={!pending ? "active" : ""}>3. Review result</span>
        </div>
        {pending ? (
          <>
            <Notice tone="warning">
              <strong>This context has not been transmitted.</strong>
              <p>
                Groq is an external service. Review every selected record for
                personal or sensitive details. Automatic masking can miss
                information. Only selected records and the constraints below
                will be uploaded after approval.
              </p>
            </Notice>
            <div className="review-meta">
              <Badge>{review.records.length} evidence records</Badge>
              <Badge tone="green">
                {review.result.redactions || 0} masking replacements
              </Badge>
              <Badge>{review.model_id}</Badge>
              <small>
                Review expires <Timestamp value={review.expires_at} />
              </small>
            </div>
            {review.result.truncated && (
              <Notice tone="warning">
                The context window was limited. Some older/longer information is
                not included. Review the excerpts; do not assume complete
                history.
              </Notice>
            )}
            <div className="row between">
              <strong>{selected.length} records selected</strong>
              <div className="row">
                <Button
                  variant="ghost"
                  onClick={() => setSelected(review.records.map((r) => r.ref))}
                >
                  Select all
                </Button>
                <Button variant="ghost" onClick={() => setSelected([])}>
                  Clear
                </Button>
              </div>
            </div>
            <div className="review-records">
              {review.records.map((record) => (
                <label
                  className={`review-record ${selected.includes(record.ref) ? "selected" : ""}`}
                  key={record.ref}
                >
                  <input
                    type="checkbox"
                    checked={selected.includes(record.ref)}
                    onChange={(event) =>
                      setSelected((value) =>
                        event.target.checked
                          ? [...value, record.ref]
                          : value.filter((ref) => ref !== record.ref),
                      )
                    }
                    aria-label={`Include evidence ${record.ref}`}
                  />
                  <div>
                    <div className="row wrap">
                      <code>{record.ref}</code>
                      <strong>{record.label || "Source record"}</strong>
                      {record.outcome && <Badge>{record.outcome}</Badge>}
                    </div>
                    <p>{record.text}</p>
                    {record.timestamp && (
                      <small>
                        <Timestamp value={record.timestamp} />
                      </small>
                    )}
                  </div>
                </label>
              ))}
            </div>
            <details className="privacy-advanced">
              <summary>Extra redactions & request constraints</summary>
              <Field
                label="Additional words or phrases to hide"
                hint="One literal phrase per line. Rebuild the preview and review it again."
              >
                <textarea
                  rows={3}
                  value={extra}
                  onChange={(event) => setExtra(event.target.value)}
                  placeholder="A co-owner name, employer, or other sensitive detail"
                />
              </Field>
              <Button variant="secondary" busy={action.busy} onClick={redact}>
                <ShieldCheck size={14} />
                Apply extra redactions
              </Button>
              <h4>Also included as non-identifying constraints</h4>
              <pre>{JSON.stringify(review.result.constraints, null, 2)}</pre>
            </details>
            <label className="checkbox-label approval-line">
              <input
                type="checkbox"
                checked={approved}
                onChange={(event) => setApproved(event.target.checked)}
              />
              I reviewed the selected redacted context and authorize this
              request to Groq.
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={fresh}
                onChange={(event) => setFresh(event.target.checked)}
              />
              Request a fresh response instead of reusing a matching local
              result (uses provider quota).
            </label>
            <div className="review-actions">
              <Button
                variant="secondary"
                onClick={onClose}
                disabled={action.busy}
              >
                Keep data local
              </Button>
              <Button
                busy={action.busy}
                disabled={!approved || !selected.length}
                onClick={execute}
              >
                <Sparkles size={15} />
                {action.busy
                  ? "Processing approved context…"
                  : `Approve & ${review.purpose === "draft" ? "draft" : review.purpose === "notes" ? "organize" : "analyze"} with Groq`}
              </Button>
            </div>
          </>
        ) : (
          <>
            <CloudResult request={review} lead={lead} />
            <div className="review-actions">
              <Button variant="secondary" onClick={onClose}>
                Close review
                <CheckCheck size={15} />
              </Button>
            </div>
          </>
        )}
        {action.error && <Notice tone="warning">{action.error}</Notice>}
      </div>
    </Modal>
  );
}

function CloudResult({
  request,
  lead,
}: {
  request: CloudReview;
  lead: LeadProfile;
}) {
  const action = useAction();
  const { toast } = useWorkspace();
  const [confirmed, setConfirmed] = useState(false);
  const [saved, setSaved] = useState(false);
  const alreadySaved = !!request.result.saved_note_id || saved;
  const stale =
    request.source_context_stale ||
    request.state === "completed_stale" ||
    (request.purpose === "draft" &&
      request.result.draft_id === lead.draft?.id &&
      lead.draft_stale);
  const result = request.result;
  if (request.state !== "completed")
    return (
      <Notice tone="warning">
        {request.error ||
          "This request did not produce an applied result. No automatic retry or seller communication occurred."}
      </Notice>
    );
  const blocked = lead.restriction_status !== "reviewed_clear";
  return (
    <div className="cloud-result">
      {stale && (
        <Notice tone="warning">
          Source context changed. Prepare a new reviewed request before using
          this result.
        </Notice>
      )}
      {result.cached_from && (
        <Badge tone="green">Reused local result · no new API call</Badge>
      )}
      <Notice>
        AI proposal, not a verified source record. Review meaning, not just
        matching quotes. Original CRM/spreadsheet notes stay unchanged.
      </Notice>
      {result.summary && <p className="cloud-summary">{result.summary.text}</p>}
      {!!result.organized_notes?.length && (
        <div className="organized-note-list">
          {result.organized_notes.map((note, index) => (
            <div key={index}>
              <span className="note-index">
                {String(index + 1).padStart(2, "0")}
              </span>
              <div>
                <p>{note.text}</p>
                <small>Evidence: {note.evidence.join(", ")}</small>
                <blockquote>{note.quote}</blockquote>
              </div>
            </div>
          ))}
        </div>
      )}
      {result.missing_information && result.missing_information.length > 0 && (
        <div className="cloud-open-questions">
          <strong>Still needs verification</strong>
          <ul>
            {result.missing_information.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {request.purpose === "notes" && (
        <div className="save-organized">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
              disabled={alreadySaved || stale}
            />
            I verified this proposal against the original source.
          </label>
          <Button
            variant="secondary"
            busy={action.busy}
            disabled={!confirmed || stale || alreadySaved}
            onClick={async () => {
              const value = await action.run(
                () =>
                  post(`/cloud/requests/${request.id}/save-notes`, {
                    confirm: true,
                  }),
                "Organized notes saved locally; originals preserved",
              );
              if (value) setSaved(true);
            }}
          >
            <Save size={14} />
            {alreadySaved
              ? "Already saved locally"
              : "Save as a separate local note"}
          </Button>
        </div>
      )}
      {request.purpose === "draft" &&
        (blocked || result.draft_blocked_by_current_restriction ? (
          <Notice tone="warning">
            Current contact restrictions block marketing drafts.
          </Notice>
        ) : (
          result.body && (
            <div className="cloud-draft-preview">
              <label className="field">
                <span>Groq-prepared draft · edit in the draft panel</span>
                <textarea rows={5} readOnly value={result.body} />
              </label>
              <p>{result.review_note}</p>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                I reviewed this wording against the source facts.
              </label>
              <Button
                disabled={stale || !confirmed}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(result.body || "");
                    toast("Reviewed draft copied. Nothing was sent.");
                  } catch {
                    toast(
                      "Clipboard unavailable. Select the reviewed text to copy manually.",
                      "error",
                    );
                  }
                }}
              >
                <Clipboard size={14} />
                Copy reviewed draft
              </Button>
            </div>
          )
        ))}
      {request.purpose === "analyze" && (
        <p className="cloud-result-link">
          <Check size={15} />
          The grounded analysis is available below; conflicting source values
          remain flagged.
        </p>
      )}
      {action.error && <Notice tone="warning">{action.error}</Notice>}
    </div>
  );
}
