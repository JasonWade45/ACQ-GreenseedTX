import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Check,
  Clipboard,
  Database,
  FileSearch,
  Plus,
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
import { currency, del, human, patch, post } from "./api";
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
  subject: {
    id?: number | string;
    street_address?: string | null;
    city?: string | null;
    state?: string | null;
    zip_code?: string | null;
    square_feet?: number | null;
    bedrooms?: number | null;
    bathrooms?: number | null;
    [key: string]: unknown;
  } | null;
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
  comps?: CompRow[];
  comps_summary?: {
    count: number;
    median_price_per_sqft: number | null;
    suggested_low: number | null;
    suggested_high: number | null;
    note: string;
  };
  notice?: string;
};
type CompRow = {
  id: string;
  address: string;
  sold_price: number;
  price_per_sqft: number | null;
  square_feet: number | null;
  sold_date: string | null;
  bedrooms: number | null;
  bathrooms: number | null;
  distance_miles: number | null;
  source: string | null;
  notes: string | null;
};
type CompForm = {
  address: string;
  sold_price: string;
  square_feet: string;
  sold_date: string;
  source: string;
  notes: string;
};

const EMPTY_COMP: CompForm = {
  address: "",
  sold_price: "",
  square_feet: "",
  sold_date: "",
  source: "",
  notes: "",
};

function CompsWorksheet({
  lead,
  propertyId,
  rows,
  summary,
  subjectSqft,
}: {
  lead: LeadProfile;
  propertyId: number | null;
  rows: CompRow[];
  summary?: Brief["comps_summary"];
  subjectSqft: number | null;
}) {
  const action = useAction();
  const [subjectArea, setSubjectArea] = useState("");
  const [apn, setApn] = useState("");
  const [form, setForm] = useState<CompForm>(EMPTY_COMP);
  const [showForm, setShowForm] = useState(false);
  const set = (key: keyof CompForm, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));
  const price = Number(form.sold_price);
  const sqft = Number(form.square_feet);
  const preview =
    price > 0 && sqft > 0 ? `$${(price / sqft).toFixed(2)} per sq ft` : "";
  const valid = propertyId !== null && form.address.trim().length >= 4 && price > 0;

  return (
    <Panel
      title="Sold comparables"
      subtitle="Your own researched sold prices. Nothing here is generated or imported."
      action={
        <Button
          variant="secondary"
          disabled={propertyId === null}
          onClick={() => setShowForm((open) => !open)}
        >
          <Plus size={14} /> Add comparable
        </Button>
      }
    >
      {propertyId === null ? (
        <Empty
          title="Choose the subject property first"
          description="Pick the exact subject above so every comparable is attached to the right property."
        />
      ) : (
        <>
          {summary && summary.count > 0 ? (
            <div className="research-grid">
              <div>
                <h3>What these numbers say</h3>
                <div className="info-grid">
                  <Info label="Comparables">{String(summary.count)}</Info>
                  <Info label="Median $ / sq ft">
                    {summary.median_price_per_sqft != null
                      ? `$${summary.median_price_per_sqft.toFixed(2)}`
                      : "Unknown"}
                  </Info>
                  <Info label="Range from median">
                    {summary.suggested_low != null && summary.suggested_high != null
                      ? `${currency(summary.suggested_low)} – ${currency(summary.suggested_high)}`
                      : "Add this property's living area"}
                  </Info>
                </div>
                <p className="muted">{summary.note}</p>
              </div>
              <div>
                <h3>How the range is built</h3>
                <p className="muted">
                  Median of the price per square foot of your comps, multiplied by
                  this property's living area, then widened by five percent either
                  way. Change a comp and the range changes with it.
                </p>
              </div>
            </div>
          ) : null}

          {showForm ? (
            <div className="stack">
              <div className="form-grid">
                <Field label="Comparable address">
                  <input
                    value={form.address}
                    onChange={(e) => set("address", e.target.value)}
                    placeholder="14 Example St, Austin, TX"
                  />
                </Field>
                <Field label="Sold price (USD)">
                  <input
                    type="number"
                    min={0}
                    value={form.sold_price}
                    onChange={(e) => set("sold_price", e.target.value)}
                    placeholder="300000"
                  />
                </Field>
                <Field label="Living area (sq ft)">
                  <input
                    type="number"
                    min={0}
                    value={form.square_feet}
                    onChange={(e) => set("square_feet", e.target.value)}
                    placeholder="2000"
                  />
                </Field>
                <Field label="Sold date">
                  <input
                    type="date"
                    value={form.sold_date}
                    onChange={(e) => set("sold_date", e.target.value)}
                  />
                </Field>
                <Field label="Where you saw it">
                  <input
                    value={form.source}
                    onChange={(e) => set("source", e.target.value)}
                    placeholder="County deed, Zillow, agent"
                  />
                </Field>
                <Field label="Note (optional)">
                  <input
                    value={form.notes}
                    onChange={(e) => set("notes", e.target.value)}
                    placeholder="Renovated kitchen"
                  />
                </Field>
              </div>
              {preview ? <p className="muted">{preview}</p> : null}
              <div className="row wrap">
                <Button
                  disabled={!valid || action.busy}
                  onClick={() =>
                    action.run(async () => {
                      await post(`/leads/${lead.id}/comps`, {
                        property_id: propertyId,
                        address: form.address.trim(),
                        sold_price: price,
                        square_feet: sqft > 0 ? Math.round(sqft) : null,
                        sold_date: form.sold_date || null,
                        source: form.source.trim() || null,
                        notes: form.notes.trim() || null,
                      });
                      setForm(EMPTY_COMP);
                      setShowForm(false);
                    }, "Comparable saved")
                  }
                >
                  Save comparable
                </Button>
                <Button variant="secondary" onClick={() => setShowForm(false)}>
                  Cancel
                </Button>
              </div>
              {action.error ? <Notice>{action.error}</Notice> : null}
            </div>
          ) : null}

          <details className="stack crm-apn">
            <summary>Assessor&apos;s parcel number (APN)</summary>
            <p className="muted">
              REsimpli requires an APN for a land lead, so a land lead without one is
              held back from the CRM. Type it from the county record or the deed; it is
              saved once and a value from the source always wins.
            </p>
            <div className="row wrap">
              <Field label="APN">
                <input
                  value={apn}
                  dir="ltr"
                  onChange={(e) => setApn(e.target.value)}
                  placeholder="123-456-789"
                />
              </Field>
              <Button
                disabled={!apn.trim() || action.busy}
                onClick={() =>
                  action.run(async () => {
                    await patch(
                      `/leads/${lead.id}/properties/${propertyId}`,
                      { apn: apn.trim() },
                    );
                    setApn("");
                  }, "APN saved")
                }
              >
                Save APN
              </Button>
            </div>
          </details>

          {subjectSqft === null ? (
            <div className="stack">
              <h3>This property has no living area</h3>
              <p className="muted">
                The range needs it. Type the subject&apos;s living area once and it
                is saved; if your CRM later sends its own value, that value wins.
              </p>
              <div className="row wrap">
                <Field label="Subject living area (sq ft)">
                  <input
                    type="number"
                    min={100}
                    max={100000}
                    value={subjectArea}
                    onChange={(e) => setSubjectArea(e.target.value)}
                    placeholder="2000"
                  />
                </Field>
                <Button
                  disabled={
                    !Number(subjectArea) ||
                    Number(subjectArea) < 100 ||
                    action.busy
                  }
                  onClick={() =>
                    action.run(async () => {
                      await patch(
                        `/leads/${lead.id}/properties/${propertyId}`,
                        { square_feet: Math.round(Number(subjectArea)) },
                      );
                      setSubjectArea("");
                    }, "Living area saved")
                  }
                >
                  Save living area
                </Button>
              </div>
              {action.error ? <Notice>{action.error}</Notice> : null}
            </div>
          ) : null}

          {rows.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>Address</th>
                  <th>Sold</th>
                  <th>Living area</th>
                  <th>$ / sq ft</th>
                  <th>Source</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((comp) => (
                  <tr key={comp.id}>
                    <td>{comp.address}</td>
                    <td>
                      {currency(comp.sold_price)}
                      {comp.sold_date ? <small> · {comp.sold_date}</small> : null}
                    </td>
                    <td>
                      {comp.square_feet ? `${comp.square_feet.toLocaleString()} sq ft` : "Unknown"}
                    </td>
                    <td>
                      {comp.price_per_sqft != null
                        ? `$${comp.price_per_sqft.toFixed(2)}`
                        : "Add living area"}
                    </td>
                    <td>{comp.source || "—"}</td>
                    <td>
                      <Button
                        variant="secondary"
                        onClick={() =>
                          action.run(async () => {
                            await del(`/leads/${lead.id}/comps/${comp.id}`);
                          }, "Comparable removed")
                        }
                      >
                        Remove
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty
              title="No comparables yet"
              description="Add the sold records you found in a source you trust. The range appears as soon as one comp has a price and a living area."
            />
          )}
        </>
      )}
    </Panel>
  );
}

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
      <CompsWorksheet
        lead={lead}
        propertyId={data.data?.subject ? Number(data.data.subject.id) : null}
        rows={data.data?.comps || []}
        summary={data.data?.comps_summary}
        subjectSqft={data.data?.subject?.square_feet ?? null}
      />
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
            Run <code>legacy/windows/MERGE-WORKSPACES.cmd</code> in the updated unified
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
