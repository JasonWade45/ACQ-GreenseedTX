import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Check,
  Clipboard,
  Database,
  FileSearch,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Info,
  Loading,
  Modal,
  Notice,
  Panel,
  useAction,
  useData,
} from "./components";
import { currency, human, patch, post } from "./api";
import type { LeadProfile, Property } from "./types";

type PrepItem = {
  key: string;
  text: string;
  reviewed: boolean;
  answer?: string;
  required?: boolean;
};
type Plan = {
  id: number;
  source: string;
  opener: string | null;
  talking_points: PrepItem[];
  questions: PrepItem[];
  guardrails: string[];
  internal_only: boolean;
  reason: string | null;
  stale: boolean;
  updated_at: string;
};

export function CallPreparation({ lead }: { lead: LeadProfile }) {
  const plan = useData<Plan | null>(
    "preparation",
    `/leads/${lead.id}/call-plan`,
  );
  const action = useAction();
  const [regenerate, setRegenerate] = useState(false);
  const generate = () =>
    action.run(
      () => post(`/leads/${lead.id}/call-plan`, { regenerate: !!plan.data }),
      "Local preparation saved; no contact was recorded",
    );
  return (
    <div className="stack unified-enter">
      <Panel
        title="Prepare the conversation. Keep the evidence."
        subtitle="Local, editable preparation from recorded property facts — no provider call, no dialer, no communication."
        action={
          <Badge tone="green">
            <ShieldCheck size={12} /> Local rules only
          </Badge>
        }
      >
        <Notice>
          Checking a preparation item means <strong>reviewed</strong>, not
          asked, called or contacted. Record actual outcomes separately through
          Record activity.
        </Notice>
        {plan.isPending ? (
          <Loading />
        ) : plan.isError ? (
          <ErrorState error={plan.error} retry={() => plan.refetch()} />
        ) : !plan.data ? (
          <Empty
            title="Start with what is actually known"
            description="Build a saved checklist, property talking points and internal guardrails. An opener is withheld unless identity, restrictions and a recorded callback/motivation context permit it."
            action={
              <Button onClick={generate} busy={action.busy}>
                Build local preparation
              </Button>
            }
          />
        ) : (
          <>
            {plan.data.stale && (
              <Notice tone="warning">
                The seller context changed. This plan is read-only and its
                opener is withheld. Regenerate after reviewing the new evidence;
                the old plan remains in history.
              </Notice>
            )}
            <PreparationForm key={plan.data.id} plan={plan.data} />
            <div className="profile-panel-footer">
              <span className="muted">
                {plan.data.source} · preparation never updates contact status
              </span>
              <Button variant="secondary" onClick={() => setRegenerate(true)}>
                <RefreshCw size={14} /> Regenerate plan
              </Button>
            </div>
          </>
        )}
        {action.error && <Notice tone="danger">{action.error}</Notice>}
      </Panel>
      {regenerate && (
        <Modal
          title="Create a new preparation version?"
          onClose={() => setRegenerate(false)}
        >
          <div className="form-stack">
            <p>
              The old checklist and answers remain in the local database. A new
              version starts unchecked, using current evidence. No seller
              communication occurs.
            </p>
            <div className="modal-actions">
              <Button variant="secondary" onClick={() => setRegenerate(false)}>
                Cancel
              </Button>
              <Button
                busy={action.busy}
                onClick={async () => {
                  if (await generate()) setRegenerate(false);
                }}
              >
                Create new version
              </Button>
            </div>
            {action.error && <Notice tone="danger">{action.error}</Notice>}
          </div>
        </Modal>
      )}
    </div>
  );
}
function PreparationForm({ plan }: { plan: Plan }) {
  const action = useAction();
  const [checks, setChecks] = useState<Record<string, boolean>>(
    Object.fromEntries(
      [...plan.questions, ...plan.talking_points].map((q) => [
        q.key,
        q.reviewed,
      ]),
    ),
  );
  const [answers, setAnswers] = useState<Record<string, string>>(
    Object.fromEntries(plan.questions.map((q) => [q.key, q.answer || ""])),
  );
  const [opener, setOpener] = useState(plan.opener || "");
  const [dirty, setDirty] = useState(false);
  return (
    <div className="form-stack prep-form">
      {plan.reason && (
        <Notice tone={plan.internal_only ? "warning" : "info"}>
          {plan.reason}
        </Notice>
      )}
      {!plan.internal_only && !plan.stale && plan.opener && (
        <div className="prep-opener">
          <Field label="Human-reviewed opener (draft only)">
            <textarea
              value={opener}
              maxLength={1200}
              rows={4}
              onChange={(e) => {
                setOpener(e.target.value);
                setDirty(true);
              }}
            />
          </Field>
          <Button
            variant="secondary"
            onClick={() =>
              action.run(async () => {
                await navigator.clipboard.writeText(opener);
                return true;
              }, "Opener copied — nothing sent")
            }
          >
            <Clipboard size={14} />
            Copy opener
          </Button>
        </div>
      )}
      {!!plan.talking_points.length && (
        <div>
          <h3>Recorded property talking points</h3>
          {plan.talking_points.map((q) => (
            <label className="prep-check" key={q.key}>
              <input
                type="checkbox"
                disabled={plan.stale}
                checked={checks[q.key] || false}
                onChange={(e) => {
                  setChecks({ ...checks, [q.key]: e.target.checked });
                  setDirty(true);
                }}
              />
              <span>
                {q.text}
                <small>
                  Recorded reference; confirm accuracy before relying on it.
                </small>
              </span>
            </label>
          ))}
        </div>
      )}
      <div>
        <h3>Preparation checklist</h3>
        {plan.questions.map((q) => (
          <div className="prep-question" key={q.key}>
            <label className="prep-check">
              <input
                type="checkbox"
                disabled={plan.stale}
                checked={checks[q.key] || false}
                onChange={(e) => {
                  setChecks({ ...checks, [q.key]: e.target.checked });
                  setDirty(true);
                }}
              />
              <span>
                {q.text}
                {q.required && (
                  <small>
                    Priority preparation item · not a completed call
                  </small>
                )}
              </span>
            </label>
            <Field label={`Internal preparation notes: ${human(q.key)}`}>
              <textarea
                rows={2}
                maxLength={3000}
                disabled={plan.stale}
                value={answers[q.key] || ""}
                placeholder="Internal notes only. Do not imply that the seller answered."
                onChange={(e) => {
                  setAnswers({ ...answers, [q.key]: e.target.value });
                  setDirty(true);
                }}
              />
            </Field>
          </div>
        ))}
      </div>
      <div className="prep-guardrails">
        <h3>Do not say / do not assume</h3>
        <ul>
          {plan.guardrails.map((g) => (
            <li key={g}>{g}</li>
          ))}
        </ul>
      </div>
      <div className="row wrap">
        <Button
          disabled={plan.stale || !dirty}
          busy={action.busy}
          onClick={async () => {
            const result = await action.run(
              () =>
                patch(`/call-plans/${plan.id}`, {
                  checks,
                  answers,
                  ...(!plan.internal_only && plan.opener ? { opener } : {}),
                }),
              "Preparation saved; no contact was inferred",
            );
            if (result) setDirty(false);
          }}
        >
          <Check size={15} />
          Save preparation
        </Button>
        <span className="muted">
          {dirty ? "Unsaved local edits" : "Saved checklist"} ·{" "}
          {Object.values(checks).filter(Boolean).length} reviewed
        </span>
      </div>
      {action.error && <Notice tone="danger">{action.error}</Notice>}
    </div>
  );
}

const factNames: Record<string, string> = {
  county: "County",
  lot_acres: "Lot acres",
  tax_market_value: "County market-value reference",
  tax_assessed_value: "County assessed-value reference",
  tax_year: "Tax year",
  estimated_equity: "Recorded equity estimate",
  mortgage_balance: "Recorded mortgage balance",
  occupancy_status: "Recorded occupancy",
  property_condition: "Recorded condition",
};
export function RichPropertyFacts({ property }: { property: Property }) {
  const facts = (property.property_metadata.facts || {}) as Record<
    string,
    unknown
  >;
  const entries = Object.entries(facts).filter(
    ([k, v]) => k in factNames && v != null,
  );
  return entries.length ? (
    <div className="property-extra">
      <div className="info-grid">
        {entries.map(([key, value]) => (
          <Info key={key} label={factNames[key]}>
            {[
              "tax_market_value",
              "tax_assessed_value",
              "estimated_equity",
              "mortgage_balance",
            ].includes(key) && typeof value === "number"
              ? currency(value)
              : String(value)}
          </Info>
        ))}
      </div>
      <small>
        Source-reported facts, not independent verification. Recorded
        value/equity is not an appraisal or an offer.
      </small>
    </div>
  ) : null;
}
type Brief = {
  subject: Record<string, unknown> | null;
  reason?: string;
  criteria?: Record<string, unknown>;
  references?: {
    field: string;
    label: string;
    value: number;
    source: string;
    as_of: string | number | null;
  }[];
  portals?: { label: string; url: string }[];
  notice?: string;
};
export function PropertyResearch({ lead }: { lead: LeadProfile }) {
  const [propertyId, setPropertyId] = useState(
    lead.properties.length === 1 ? String(lead.properties[0].id) : "",
  );
  const data = useData<Brief>(
    "comps-brief",
    `/leads/${lead.id}/comps-brief${propertyId ? `?property_id=${propertyId}` : ""}`,
  );
  const action = useAction();
  const address = data.data?.subject
    ? [
        data.data.subject.street_address,
        data.data.subject.city,
        data.data.subject.state,
        data.data.subject.zip_code,
      ]
        .filter(Boolean)
        .join(", ")
    : "";
  return (
    <div className="stack unified-enter">
      <Panel
        title="Property research brief"
        subtitle="A grounded starting point for comparable-sale research — not fabricated sold comparables."
        action={
          <Badge tone="neutral">
            <FileSearch size={12} /> No MLS feed
          </Badge>
        }
      >
        <Field label="Exact subject property">
          <select
            value={propertyId}
            onChange={(e) => setPropertyId(e.target.value)}
          >
            <option value="">Select a property</option>
            {lead.properties.map((p) => (
              <option key={p.id} value={p.id}>
                {[p.street_address, p.city, p.state]
                  .filter(Boolean)
                  .join(", ") || `Property ${p.id}`}
              </option>
            ))}
          </select>
        </Field>
        {data.isPending ? (
          <Loading />
        ) : data.isError ? (
          <ErrorState error={data.error} />
        ) : !data.data.subject ? (
          <Empty
            title="Choose the exact subject"
            description={
              data.data.reason || "Property information has not been supplied."
            }
          />
        ) : (
          <>
            <div className="research-subject">
              <h3>{address || "Address not recorded"}</h3>
              <Button
                variant="secondary"
                disabled={!address}
                onClick={() =>
                  action.run(async () => {
                    await navigator.clipboard.writeText(address);
                    return true;
                  }, "Subject address copied")
                }
              >
                <Clipboard size={14} />
                Copy subject address
              </Button>
            </div>
            <div className="research-grid">
              <div>
                <h3>Recorded value references</h3>
                {data.data.references?.length ? (
                  data.data.references.map((ref) => (
                    <div className="research-reference" key={ref.field}>
                      <span>
                        {ref.label}
                        <small>
                          {ref.source}
                          {ref.as_of
                            ? ` · source year ${ref.as_of}`
                            : " · as-of date unknown"}
                        </small>
                      </span>
                      <strong>{currency(ref.value)}</strong>
                    </div>
                  ))
                ) : (
                  <p className="muted">
                    No asking price, valuation or tax reference is recorded. No
                    value is estimated by this tool.
                  </p>
                )}
              </div>
              <div>
                <h3>Suggested search criteria</h3>
                <div className="info-grid">
                  {Object.entries(data.data.criteria || {}).map(([k, v]) => (
                    <Info key={k} label={human(k)}>
                      {v == null ? "Unknown — verify first" : String(v)}
                    </Info>
                  ))}
                </div>
              </div>
            </div>
            <Notice>
              {data.data.notice} Price bands, if shown, are search filters
              around an unverified reference — not a price recommendation.
            </Notice>
            <div className="row wrap">
              {data.data.portals?.map((p) => (
                <a
                  key={p.label}
                  className="btn btn-secondary"
                  href={p.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open {p.label}
                </a>
              ))}
            </div>
          </>
        )}
        {action.error && (
          <Notice tone="warning">
            Clipboard unavailable. You can select and copy the address manually.
          </Notice>
        )}
      </Panel>
      <Panel title="Verified sold comparables">
        <Empty
          title="No verified sold comparables connected"
          description="There is no MLS/portal integration. Research actual sold records in an approved source and record supporting evidence yourself. No comparable addresses, sale dates or prices are generated."
        />
      </Panel>
    </div>
  );
}

export function LocalRefreshPanel() {
  const action = useAction();
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState<{
    processed: number;
    updated: number;
    cached: number;
  } | null>(null);
  return (
    <Panel
      title="Refresh the local evidence layer"
      subtitle="Up to 200 of the most recently updated records per run. No cloud or Ollama request is made."
    >
      <div className="row wrap">
        <label className="check-label">
          <input
            type="checkbox"
            checked={confirm}
            onChange={(e) => setConfirm(e.target.checked)}
          />
          I approve refreshing local rules only.
        </label>
        <Button
          variant="secondary"
          busy={action.busy}
          disabled={!confirm}
          onClick={async () => {
            const r = await action.run(
              () =>
                post<{ processed: number; updated: number; cached: number }>(
                  "/insights/refresh-local",
                  { confirm: true, limit: 200 },
                ),
              "Local evidence refresh completed",
            );
            if (r) setResult(r);
          }}
        >
          <RefreshCw size={14} />
          Refresh local rules
        </Button>
      </div>
      {result && (
        <Notice>
          {result.processed} processed · {result.updated} updated ·{" "}
          {result.cached} unchanged/cached · 0 cloud requests.
        </Notice>
      )}
      {action.error && <Notice tone="danger">{action.error}</Notice>}
    </Panel>
  );
}

type Candidate = {
  lead_id: number;
  name: string;
  address: string | null;
  conflicting_fields: string[];
};
type MergeRow = {
  source_id: string;
  name: string;
  address: string | null;
  external_id: string | null;
  kind: string;
  status: string;
  candidates: Candidate[];
  target_id?: number;
  warnings: string[];
};
type Merge = {
  id: string;
  source_name: string;
  status: string;
  counts: {
    source_leads: number;
    created: number;
    linked: number;
    skipped: number;
    source_tables: Record<string, number>;
  };
  pending: number;
  records?: MergeRow[];
};
type Decision = {
  source_id: string;
  action: "separate" | "link" | "skip";
  target_id?: number;
  fill_missing: boolean;
};
export function WorkspaceBridge() {
  const list = useData<Merge[]>("workspace-merges", "/workspace-merges");
  const capabilities = useData<{ local_selection_available: boolean }>(
    "merge-capabilities",
    "/workspace-merges/capabilities",
  );
  const action = useAction();
  const [path, setPath] = useState("");
  const [selected, setSelected] = useState("");
  return (
    <Panel
      title="Bring both workspaces together"
      subtitle="GitHub/Next UUID data → unified workspace. Both original databases are preserved."
      action={
        <Badge tone="green">
          <Database size={12} /> Backup first
        </Badge>
      }
    >
      <div className="merge-intro">
        <div>
          <h3>Snapshot. Review. Approve.</h3>
          <p>
            Existing unified data stays in place. Each legacy seller must be
            explicitly kept separate, linked to a reviewed candidate, or
            skipped. A shared property never automatically merges people.
          </p>
          <p className="muted">
            Historical AI, drafts and old preparation are archived as unverified
            source records, not promoted to current recommendations. Activities,
            appointments and tasks are transferred with source provenance. No
            secrets/settings or CRM writes are migrated.
          </p>
        </div>
        <div className="merge-local">
          <strong>Keep company data on your PC.</strong>
          <p>
            Run <code>MERGE-WORKSPACES.cmd</code> in the updated unified
            project. Choose the GitHub <code>backend\acquisitions.db</code>{" "}
            locally, then return here to review. Do not upload a company
            database to this chat.
          </p>
        </div>
      </div>
      {capabilities.data?.local_selection_available && (
        <form
          className="form-stack"
          onSubmit={async (e) => {
            e.preventDefault();
            const r = await action.run(
              () =>
                post<Merge>("/workspace-merges/prepare", {
                  source_path: path,
                  confirmation: "PREPARE READ ONLY SNAPSHOT",
                }),
              "Read-only source snapshot and target backup prepared",
            );
            if (r) {
              setSelected(r.id);
              setPath("");
            }
          }}
        >
          <Field label="Or paste the GitHub database's full local path">
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              maxLength={1200}
              placeholder="C:\…\ACQ-GreenseedTX\backend\acquisitions.db"
              required
            />
          </Field>
          <Button variant="secondary" busy={action.busy} type="submit">
            Prepare read-only review
          </Button>
        </form>
      )}
      {list.isPending ? (
        <Loading />
      ) : list.isError ? (
        <ErrorState error={list.error} />
      ) : list.data.length ? (
        <div className="merge-jobs">
          {list.data.map((job) => (
            <button
              key={job.id}
              onClick={() => setSelected(job.id)}
              className={`merge-job ${selected === job.id ? "selected" : ""}`}
            >
              <span>
                <strong>{job.source_name}</strong>
                <small>
                  {job.counts.source_leads} source sellers · {job.pending}{" "}
                  awaiting review
                </small>
              </span>
              <Badge tone={job.status === "completed" ? "green" : "amber"}>
                {human(job.status)}
              </Badge>
            </button>
          ))}
        </div>
      ) : (
        <p className="muted">
          No database migration prepared. Your existing workspace is unchanged.
        </p>
      )}
      {selected && <MergeReview key={selected} id={selected} />}
      {action.error && <Notice tone="danger">{action.error}</Notice>}
    </Panel>
  );
}
function MergeReview({ id }: { id: string }) {
  const detail = useData<Merge>("workspace-merge", `/workspace-merges/${id}`);
  const action = useAction();
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [confirmation, setConfirmation] = useState("");
  const [page, setPage] = useState(0);
  if (detail.isPending) return <Loading />;
  if (detail.isError) return <ErrorState error={detail.error} />;
  const job = detail.data;
  const pending = (job.records || []).filter((row) => row.status === "pending");
  const visible = pending.slice(page * 20, (page + 1) * 20);
  const choice = (row: MergeRow, value: string) => {
    const [action, target] = value.split(":");
    if (!action) {
      setDecisions((prev) => {
        const next = { ...prev };
        delete next[row.source_id];
        return next;
      });
      return;
    }
    setDecisions({
      ...decisions,
      [row.source_id]: {
        source_id: row.source_id,
        action: action as Decision["action"],
        target_id: target ? Number(target) : undefined,
        fill_missing: decisions[row.source_id]?.fill_missing || false,
      },
    });
  };
  const active = Object.values(decisions).filter((d) =>
    pending.some((r) => r.source_id === d.source_id),
  );
  return (
    <div className="merge-review form-stack">
      <div className="row wrap">
        <Badge>{job.counts.created} created</Badge>
        <Badge>{job.counts.linked} linked</Badge>
        <Badge>{job.counts.skipped} skipped</Badge>
        <Badge tone="amber">{job.pending} pending</Badge>
        {!!pending.length && (
          <Button
            variant="secondary"
            busy={action.busy}
            onClick={async () => {
              const r = await action.run(
                () => post(`/workspace-merges/${id}/refresh`),
                "Pending matches refreshed. Review decisions again.",
              );
              if (r) {
                setDecisions({});
                setConfirmation("");
                setPage(0);
              }
            }}
          >
            <RefreshCw size={14} />
            Refresh pending matches
          </Button>
        )}
      </div>
      <Notice>
        The source snapshot stays unchanged. Known fields are never overwritten.
        Linking transfers the selected seller’s history and binds an available
        CRM ID; choose it only after confirming the same person. DNC remains
        sticky. Checkboxes do not lift restrictions or prove contact.
      </Notice>
      {visible.map((row) => (
        <div className="merge-row" key={row.source_id}>
          <div>
            <h3>{row.name}</h3>
            <p>{row.address || "No property address"}</p>
            <small>
              {human(row.kind)} · legacy ID {row.source_id}
              {row.external_id ? ` · CRM ID ${row.external_id}` : ""}
            </small>
          </div>
          <Field label={`Decision for ${row.name}`}>
            <select
              value={
                decisions[row.source_id]
                  ? `${decisions[row.source_id].action}${decisions[row.source_id].target_id ? `:${decisions[row.source_id].target_id}` : ""}`
                  : ""
              }
              onChange={(e) => choice(row, e.target.value)}
            >
              <option value="">Not reviewed — leave untouched</option>
              {row.kind !== "previously_migrated" &&
                row.kind !== "existing_resimpli_record" && (
                  <option value="separate">
                    Keep as a separate seller record
                  </option>
                )}
              {row.candidates.map((c) => (
                <option key={c.lead_id} value={`link:${c.lead_id}`}>
                  Link reviewed person: {c.name} · local #{c.lead_id}
                </option>
              ))}
              <option value="skip">Skip this snapshot record</option>
            </select>
          </Field>
          {row.candidates.map((c) => (
            <div className="merge-candidate" key={c.lead_id}>
              <Link to={`/leads/${c.lead_id}`} target="_blank" rel="noreferrer">
                Review local #{c.lead_id}: {c.name}
              </Link>
              <span>{c.address || "Address unknown"}</span>
              {c.conflicting_fields.length > 0 && (
                <Badge tone="red">
                  Conflicting: {c.conflicting_fields.join(", ")}
                </Badge>
              )}
            </div>
          ))}
          {decisions[row.source_id]?.action === "link" && (
            <label className="check-label">
              <input
                type="checkbox"
                checked={decisions[row.source_id].fill_missing}
                onChange={(e) =>
                  setDecisions({
                    ...decisions,
                    [row.source_id]: {
                      ...decisions[row.source_id],
                      fill_missing: e.target.checked,
                    },
                  })
                }
              />
              Also fill empty local fields only (never overwrite known values).
            </label>
          )}
        </div>
      ))}
      {!!pending.length && (
        <div className="row wrap">
          <Button
            variant="secondary"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            Previous review page
          </Button>
          <span>
            {page * 20 + 1}–{Math.min((page + 1) * 20, pending.length)} of{" "}
            {pending.length} pending
          </span>
          <Button
            variant="secondary"
            disabled={(page + 1) * 20 >= pending.length}
            onClick={() => setPage(page + 1)}
          >
            Next review page
          </Button>
        </div>
      )}
      {!!active.length && (
        <form
          className="form-stack"
          onSubmit={async (e) => {
            e.preventDefault();
            const r = await action.run(
              () =>
                post(`/workspace-merges/${id}/commit`, {
                  confirmation,
                  decisions: active,
                }),
              "Reviewed records migrated locally; originals preserved",
            );
            if (r) {
              setDecisions({});
              setConfirmation("");
              setPage(0);
            }
          }}
        >
          <Field
            label={`Type MERGE REVIEWED RECORDS for ${active.length} explicit decisions`}
          >
            <input
              required
              pattern="MERGE REVIEWED RECORDS"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
            />
          </Field>
          <Button busy={action.busy} type="submit">
            Approve selected local migration
          </Button>
        </form>
      )}
      {!pending.length && (
        <Notice tone="success">
          Review complete. Both originals and private recovery snapshots are
          retained. Check record counts, restrictions and timelines before any
          future sync.
        </Notice>
      )}
      <details>
        <summary>Preserved source table counts</summary>
        <pre className="source-json">
          {JSON.stringify(job.counts.source_tables, null, 2)}
        </pre>
      </details>
      {action.error && (
        <Notice tone="danger">
          {action.error} Earlier committed records remain preserved; remaining
          decisions can be reviewed/resumed.
        </Notice>
      )}
    </div>
  );
}
