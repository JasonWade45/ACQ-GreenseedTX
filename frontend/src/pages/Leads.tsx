import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowDownToLine,
  ArrowDownUp,
  ArrowRight,
  Bookmark,
  Check,
  Filter,
  Plus,
  Search,
  ShieldAlert,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Loading,
  Modal,
  Notice,
  PageHeader,
  Pagination,
  RestrictionBadge,
  StageBadge,
  Timestamp,
  useAction,
  useData,
  useWorkspace,
} from "../components";
import { dateTime, download, human, post } from "../api";
import type { LeadPage } from "../types";

export default function Leads() {
  const { meta, toast } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("search") || "");
  const [advanced, setAdvanced] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [bulk, setBulk] = useState(false);
  const [review, setReview] = useState(false);
  const action = useAction();
  const [saved, setSaved] = useState<{ name: string; query: string }[]>(() => {
    try {
      return JSON.parse(
        localStorage.getItem("acquisition-saved-filters") || "[]",
      );
    } catch {
      return [];
    }
  });
  const page = Number(params.get("page") || 1);
  const pageSize = 25;
  const query = new URLSearchParams(params);
  query.set("page_size", String(pageSize));
  const data = useData<LeadPage>("leads", "/leads?" + query.toString());
  useEffect(() => {
    const timer = setTimeout(() => {
      if (search !== (params.get("search") || "")) {
        const p = new URLSearchParams(params);
        if (search) p.set("search", search);
        else p.delete("search");
        p.delete("page");
        setParams(p, { replace: true });
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [search, params, setParams]);
  useEffect(() => {
    setSelected([]);
  }, [params]);
  function filter(key: string, value: string) {
    const p = new URLSearchParams(params);
    if (value) p.set(key, value);
    else p.delete(key);
    p.delete("page");
    setParams(p);
  }
  const [saveName, setSaveName] = useState("");
  const [saving, setSaving] = useState(false);
  function saveFilter() {
    if (!saveName.trim()) return;
    const entry = { name: saveName.trim(), query: params.toString() };
    const next = [...saved.filter((s) => s.name !== entry.name), entry].slice(
      -20,
    );
    setSaved(next);
    localStorage.setItem("acquisition-saved-filters", JSON.stringify(next));
    setSaving(false);
    toast("Filter saved in this browser");
  }
  return (
    <>
      <PageHeader
        eyebrow="SELLER RELATIONSHIPS"
        title="Seller leads"
        description="Every seller. Every property. All the context in one place."
        actions={
          <>
            <Button
              variant="secondary"
              busy={action.busy}
              onClick={() =>
                action.run(() =>
                  download(
                    "/leads/export?" + params.toString(),
                    "seller-leads.csv",
                  ),
                )
              }
            >
              <ArrowDownToLine size={16} />
              Export CSV
            </Button>
            <Link className="btn btn-primary" to="/imports">
              <Plus size={17} />
              Import seller leads
            </Link>
          </>
        }
      />
      <div className="table-card">
        <div className="leads-toolbar">
          <div className="search-input">
            <Search size={17} />
            <input
              aria-label="Search seller leads"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name, phone, email, address or CRM ID"
            />
            {search && (
              <button aria-label="Clear search" onClick={() => setSearch("")}>
                <X size={15} />
              </button>
            )}
          </div>
          <select
            aria-label="Pipeline stage"
            value={params.get("stage") || ""}
            onChange={(e) => filter("stage", e.target.value)}
          >
            <option value="">All pipeline stages</option>
            {meta.stages.map((s) => (
              <option key={s.code} value={s.code}>
                {s.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Follow-up state"
            value={params.get("followup") || ""}
            onChange={(e) => filter("followup", e.target.value)}
          >
            <option value="">All follow-ups</option>
            <option value="overdue">Overdue</option>
            <option value="today">Due today</option>
            <option value="upcoming">Upcoming</option>
            <option value="unscheduled">Unscheduled</option>
          </select>
          <Button variant="secondary" onClick={() => setAdvanced(!advanced)}>
            <Filter size={15} />
            More filters
          </Button>
          <Button
            variant="ghost"
            aria-label="Save current filter"
            onClick={() => setSaving(true)}
          >
            <Bookmark size={17} />
          </Button>
        </div>
        {advanced && (
          <div className="filter-bar">
            <label>
              Lead source
              <select
                value={params.get("source") || ""}
                onChange={(e) => filter("source", e.target.value)}
              >
                <option value="">All sources</option>
                {meta.sources.map((s) => (
                  <option key={s}>{s}</option>
                ))}
                <option value="__unknown__">Unknown source</option>
              </select>
            </label>
            <label>
              Manager
              <select
                value={params.get("manager") || ""}
                onChange={(e) => filter("manager", e.target.value)}
              >
                <option value="">All managers</option>
                {meta.managers.map((m) => (
                  <option key={m}>{m}</option>
                ))}
                <option value="__unknown__">Unassigned</option>
              </select>
            </label>
            <label>
              State
              <input
                aria-label="Property state"
                maxLength={2}
                placeholder="e.g. TX"
                value={params.get("state") || ""}
                onChange={(e) => filter("state", e.target.value.toUpperCase())}
              />
            </label>
            <label>
              Created from
              <input
                type="date"
                value={params.get("from_date") || ""}
                onChange={(e) => filter("from_date", e.target.value)}
              />
            </label>
            <label>
              Created through
              <input
                type="date"
                value={params.get("to_date") || ""}
                onChange={(e) => filter("to_date", e.target.value)}
              />
            </label>
            <label>
              Contact evidence
              <select
                value={params.get("contact_status") || ""}
                onChange={(e) => filter("contact_status", e.target.value)}
              >
                <option value="">Any contact status</option>
                <option value="unknown">Unknown</option>
                <option value="not_contacted">Explicitly not contacted</option>
                <option value="attempted">Attempted, not connected</option>
                <option value="contacted">Verified contact</option>
              </select>
            </label>
            <label>
              Heat
              <select
                value={params.get("heat") || ""}
                onChange={(e) => filter("heat", e.target.value)}
              >
                <option value="">Any heat</option>
                <option value="VERY_HOT">Very hot</option>
                <option value="HOT">Hot</option>
                <option value="NONE">No heat signal</option>
              </select>
            </label>
            <label>
              Priority tier
              <select
                value={params.get("tier") || ""}
                onChange={(e) => filter("tier", e.target.value)}
              >
                <option value="">Any tier</option>
                {["P1", "P2", "P3", "P4"].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Lead type
              <select
                value={params.get("lead_type") || ""}
                onChange={(e) => filter("lead_type", e.target.value)}
              >
                <option value="">Any lead type</option>
                <option value="SENIOR_OWNER">Senior owner</option>
                <option value="TAX_LIEN_LISPENDENS_HOA">Tax lien / lis pendens / HOA</option>
                <option value="ABSENTEE">Absentee</option>
                <option value="INHERITED">Inherited</option>
              </select>
            </label>
            <label>
              County
              <input
                value={params.get("county") || ""}
                onChange={(e) => filter("county", e.target.value)}
                placeholder="e.g. Dallas"
              />
            </label>
            <label>
              Minimum score
              <input
                type="number"
                min="0"
                max="100"
                value={params.get("min_score") || ""}
                onChange={(e) => filter("min_score", e.target.value)}
              />
            </label>
            <label>
              Minimum equity %
              <input
                type="number"
                value={params.get("min_equity") || ""}
                onChange={(e) => filter("min_equity", e.target.value)}
              />
            </label>
            <label>
              Outreach context
              <select
                value={params.get("outreach_mode") || ""}
                onChange={(e) => filter("outreach_mode", e.target.value)}
              >
                <option value="">Any context</option>
                <option value="relationship">Relationship (warm history)</option>
                <option value="cold">Cold (no prior relationship)</option>
              </select>
            </label>
            <label>
              Skip trace
              <select
                value={params.get("needs_skip_trace") || ""}
                onChange={(e) => filter("needs_skip_trace", e.target.value)}
              >
                <option value="">Any lead</option>
                <option value="true">Needs a skip trace</option>
                <option value="false">Has a verified contact</option>
              </select>
            </label>
          </div>
        )}
        <div className="filter-chips">
          {[...params.entries()]
            .filter(
              ([k]) => !["page", "sort", "direction", "search"].includes(k),
            )
            .map(([k, v]) => (
              <button key={k} onClick={() => filter(k, "")}>
                {human(k)}:{" "}
                {v.startsWith("stage:") ? human(v.slice(6)) : human(v)}
                <X size={12} />
              </button>
            ))}
          {params.size > 0 && (
            <button
              className="clear-filters"
              onClick={() => {
                setSearch("");
                setParams({});
              }}
            >
              Clear all
            </button>
          )}
          {saved.length > 0 && (
            <select
              aria-label="Saved filters"
              value=""
              onChange={(e) => {
                const item = saved.find((s) => s.name === e.target.value);
                if (item) {
                  setSearch(
                    new URLSearchParams(item.query).get("search") || "",
                  );
                  setParams(item.query);
                }
              }}
            >
              <option value="">Saved views ({saved.length})</option>
              {saved.map((s) => (
                <option key={s.name}>{s.name}</option>
              ))}
            </select>
          )}
        </div>
        {selected.length > 0 && (
          <div className="bulk-bar">
            <Check size={16} />
            <strong>{selected.length} selected</strong>
            <Button variant="secondary" onClick={() => setBulk(true)}>
              Change local stage
            </Button>
            <Button variant="secondary" onClick={() => setReview(true)}>
              <ShieldCheck size={15} /> Review contact restrictions
            </Button>
            <button className="text-link" onClick={() => setSelected([])}>
              Clear selection
            </button>
            <span>No CRM writes</span>
          </div>
        )}
        {data.isPending ? (
          <Loading />
        ) : data.isError ? (
          <ErrorState error={data.error} retry={() => data.refetch()} />
        ) : data.data.items.length === 0 ? (
          <Empty
            title={
              params.size
                ? "No matching sellers"
                : "Your seller pipeline starts here"
            }
            description={
              params.size
                ? "Try a different search or remove a filter."
                : "Import a historical lead list or connect a verified read-only CRM integration. No sample data is added automatically."
            }
            action={
              <Link className="btn btn-secondary" to="/imports">
                <Upload size={16} />
                Open Import Center
              </Link>
            }
          />
        ) : (
          <>
            <div className="table-wrap">
              <table className="lead-table">
                <thead>
                  <tr>
                    <th className="check-column">
                      <input
                        aria-label="Select page"
                        type="checkbox"
                        checked={data.data.items.every((l) =>
                          selected.includes(l.id),
                        )}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? data.data.items.map((l) => l.id)
                              : [],
                          )
                        }
                      />
                    </th>
                    <th>
                      <button
                        onClick={() => {
                          filter("sort", "full_name");
                          const p = new URLSearchParams(params);
                          p.set("sort", "full_name");
                          p.set(
                            "direction",
                            params.get("direction") === "asc" ? "desc" : "asc",
                          );
                          setParams(p);
                        }}
                      >
                        SELLER / PROPERTY <ArrowDownUp size={12} />
                      </button>
                    </th>
                    <th>CONTACT</th>
                    <th>PIPELINE STAGE</th>
                    <th>SOURCE / MANAGER</th>
                    <th>
                      <button
                        onClick={() => filter("sort", "next_followup_at")}
                      >
                        NEXT FOLLOW-UP <ArrowDownUp size={12} />
                      </button>
                    </th>
                    <th>DS CONTEXT</th>
                    <th>DATA HEALTH</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.data.items.map((l, i) => (
                    <tr
                      key={l.id}
                      className={selected.includes(l.id) ? "selected-row" : ""}
                    >
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Select ${l.full_name || "Owner identity unknown"}`}
                          checked={selected.includes(l.id)}
                          onChange={(e) =>
                            setSelected((s) =>
                              e.target.checked
                                ? [...s, l.id]
                                : s.filter((id) => id !== l.id),
                            )
                          }
                        />
                      </td>
                      <td>
                        <Link className="seller-cell" to={`/leads/${l.id}`}>
                          <span className={`seller-avatar color-${i % 4}`}>
                            {(l.full_name || "?")
                              .split(" ")
                              .slice(0, 2)
                              .map((n) => n[0])
                              .join("")}
                          </span>
                          <span>
                            <strong>
                              {l.full_name || "Owner identity unknown"}
                            </strong>
                            <small>
                              {l.properties[0]?.street_address ||
                                "No property address"}
                            </small>
                            <small>
                              {[
                                l.properties[0]?.city,
                                l.properties[0]?.state,
                                l.properties[0]?.zip_code,
                              ]
                                .filter(Boolean)
                                .join(", ")}
                            </small>
                          </span>
                        </Link>
                      </td>
                      <td>
                        <span className="contact-value">
                          {l.primary_phone || "Phone missing"}
                        </span>
                        <small>{l.email || "Email not recorded"}</small>
                        <span className="contact-evidence">
                          {l.contact_status === "contacted"
                            ? "Verified contact"
                            : l.contact_status === "attempted"
                              ? "Attempted, not connected"
                              : "No verified contact"}
                        </span>
                      </td>
                      <td>
                        <StageBadge code={l.stage_code} />
                        {l.local_stage_override && (
                          <small>Local override</small>
                        )}
                        {l.do_not_contact && (
                          <div className="mt-6">
                            <RestrictionBadge status={l.restriction_status} />
                          </div>
                        )}
                      </td>
                      <td>
                        {l.lead_source || (
                          <span className="muted">Unknown source</span>
                        )}
                        <small>{l.assigned_manager || "Unassigned"}</small>
                      </td>
                      <td>
                        <span
                          className={
                            l.next_followup_at &&
                            new Date(l.next_followup_at) < new Date()
                              ? "text-amber"
                              : ""
                          }
                        >
                          <Timestamp value={l.next_followup_at} />
                        </span>
                        <small>
                          Last contact:{" "}
                          {dateTime(l.last_contact_at, meta.timezone, true)}
                        </small>
                      </td>
                      <td>
                        <div className="row wrap">
                          {l.heat && l.heat !== "NONE" ? (
                            <Badge tone={l.heat === "VERY_HOT" ? "red" : "amber"}>
                              {l.heat === "VERY_HOT" ? "Very hot" : "Hot"}
                            </Badge>
                          ) : null}
                          {l.priority_tier ? <Badge>{l.priority_tier}</Badge> : null}
                          {typeof l.score === "number" ? (
                            <Badge tone="blue">Score {l.score}</Badge>
                          ) : null}
                        </div>
                        <small>
                          {[
                            l.lead_type,
                            l.county,
                            typeof l.equity_pct === "number"
                              ? `${l.equity_pct}% equity`
                              : null,
                          ]
                            .filter(Boolean)
                            .join(" · ") || "No vendor context"}
                        </small>
                        {l.needs_skip_trace ? (
                          <small className="text-amber">Needs skip trace</small>
                        ) : null}
                      </td>
                      <td>
                        {l.do_not_contact ? (
                          <Badge tone="red">
                            <ShieldAlert size={11} />
                            Restricted
                          </Badge>
                        ) : (
                          <Badge
                            tone={
                              l.missing_information.length ? "amber" : "green"
                            }
                          >
                            {l.missing_information.length
                              ? `${l.missing_information.length} to review`
                              : "Complete"}
                          </Badge>
                        )}
                      </td>
                      <td>
                        <Link
                          className="table-arrow"
                          to={`/leads/${l.id}`}
                          aria-label={`Open ${l.full_name || "Owner identity unknown"}`}
                        >
                          <ArrowRight size={16} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              total={data.data.total}
              page={page}
              pageSize={pageSize}
              onChange={(p) => {
                const next = new URLSearchParams(params);
                next.set("page", String(p));
                setParams(next);
              }}
            />
          </>
        )}
      </div>
      <div className="table-note">
        All operations on this page are local. CRM IDs and original source
        statuses are preserved. Contact restrictions must be reviewed before
        outreach.
      </div>
      {saving && (
        <Modal
          title="Save this view"
          subtitle="Filter settings, including search terms, are saved in this browser. Use a private company device."
          onClose={() => setSaving(false)}
        >
          <div className="form-stack">
            <Field label="View name">
              <input
                autoFocus
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder="e.g. My overdue Ohio leads"
              />
            </Field>
            <Button onClick={saveFilter}>Save filter</Button>
          </div>
        </Modal>
      )}
      {bulk && <BulkStage ids={selected} onClose={() => setBulk(false)} />}
      {review && (
        <BulkRestrictionReview
          ids={selected}
          onClose={() => setReview(false)}
          onDone={() => data.refetch()}
        />
      )}
    </>
  );
}
function BulkStage({ ids, onClose }: { ids: number[]; onClose: () => void }) {
  const { meta } = useWorkspace();
  const action = useAction();
  const [stage, setStage] = useState("");
  const [confirm, setConfirm] = useState(false);
  return (
    <Modal
      title={`Update ${ids.length} local lead stages`}
      subtitle="This does not change any records in REsimpli."
      onClose={onClose}
    >
      <form
        className="form-stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await action.run(
            () =>
              post("/leads/bulk-stage", {
                lead_ids: ids,
                stage_code: stage,
                confirm,
              }),
            "Local stages updated",
          );
          if (r) onClose();
        }}
      >
        <Notice>
          Source statuses remain unchanged. A local override will be displayed.
        </Notice>
        <Field label="New local pipeline stage">
          <select
            required
            value={stage}
            onChange={(e) => setStage(e.target.value)}
          >
            <option value="">Select a stage</option>
            {meta.stages.map((s) => (
              <option key={s.code} value={s.code}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>
        <label className="checkbox-label">
          <input
            required
            type="checkbox"
            checked={confirm}
            onChange={(e) => setConfirm(e.target.checked)}
          />
          I confirm the local-only stage change.
        </label>
        <Button busy={action.busy}>Apply local change</Button>
      </form>
    </Modal>
  );
}

function BulkRestrictionReview({
  ids,
  onClose,
  onDone,
}: {
  ids: number[];
  onClose: () => void;
  onDone: () => void;
}) {
  const action = useAction();
  const [evidence, setEvidence] = useState("");
  const [phrase, setPhrase] = useState("");
  const [restricted, setRestricted] = useState(false);
  const [result, setResult] = useState<{
    reviewed: number;
    already_reviewed: number;
    blocked: { id: number; reason: string }[];
    missing: number[];
  } | null>(null);
  const PHRASE = "REVIEW RESTRICTIONS";
  const ready = evidence.trim().length >= 10 && phrase.trim().toUpperCase() === PHRASE;
  return (
    <Modal
      title={`Review contact permission for ${ids.length} lead(s)`}
      subtitle="One sentence of evidence, recorded on each lead separately. No CRM writes."
      onClose={onClose}
    >
      {result ? (
        <div className="form-stack">
          <Notice tone={result.blocked.length ? "warning" : "info"}>
            <strong>{result.reviewed} reviewed</strong>, {result.already_reviewed} already
            reviewed
            {result.blocked.length
              ? `, ${result.blocked.length} kept blocked by a source Do Not Contact`
              : ""}
            {result.missing.length ? `, ${result.missing.length} no longer exist` : ""}.
          </Notice>
          <p className="muted">
            Each lead now has its own audit row with the evidence you typed. Drafting is
            still gated by the skip trace, suppression and licence checks.
          </p>
          <Button
            onClick={() => {
              onDone();
              onClose();
            }}
          >
            Done
          </Button>
        </div>
      ) : (
        <form
          className="form-stack"
          onSubmit={async (e) => {
            e.preventDefault();
            const r = await action.run(
              () =>
                post<any>("/leads/restrictions/bulk", {
                  lead_ids: ids,
                  restricted,
                  evidence: evidence.trim(),
                  confirm: true,
                  confirmation: phrase.trim(),
                }),
              "Contact permission reviewed for the selected leads",
            );
            if (r) setResult(r);
          }}
        >
          <Notice tone="warning">
            A batch review is still a review. Only use this when the same recorded check
            genuinely applies to every selected lead — for example a vendor list that
            carries no opt-out and was screened before import.
          </Notice>
          <Field
            label="What did you check, and where?"
            hint="At least 10 characters. Stored verbatim on every lead in this batch."
          >
            <textarea
              rows={3}
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
              placeholder="Source list screened for opt-outs on 2026-10-29; no STOP/DNC entries."
            />
          </Field>
          <Field label="Outcome">
            <select
              value={restricted ? "restricted" : "clear"}
              onChange={(e) => setRestricted(e.target.value === "restricted")}
            >
              <option value="clear">Cleared for outreach (reviewed)</option>
              <option value="restricted">Restrict: do not contact</option>
            </select>
          </Field>
          <Field
            label={`Type ${PHRASE} to confirm`}
            hint="A lead whose source says Do Not Contact is never cleared here."
          >
            <input value={phrase} onChange={(e) => setPhrase(e.target.value)} />
          </Field>
          <Button type="submit" busy={action.busy} disabled={!ready}>
            Apply to {ids.length} lead(s)
          </Button>
          {action.error && <Notice tone="warning">{action.error}</Notice>}
        </form>
      )}
    </Modal>
  );
}
