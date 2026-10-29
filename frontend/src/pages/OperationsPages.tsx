import { LocalRefreshPanel } from "../unified";
import { navigateTabs } from "../components";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  CloudDownload,
  Database,
  Filter,
  HardDrive,
  Info,
  Play,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Terminal,
} from "lucide-react";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Loading,
  Notice,
  PageHeader,
  Panel,
  StageBadge,
  Timestamp,
  useAction,
  useData,
  useWorkspace,
} from "../components";
import { api, dateTime, download, human, patch, post } from "../api";
import { IntegrationSettings } from "../intelligence";
import { AppointmentCard } from "./LeadDetail";
import type {
  AIStatus,
  Appointment,
  DashboardData,
  Insight,
  ReportsData,
  SettingsData,
  SyncState,
} from "../types";

export function AppointmentsPage() {
  const data = useData<Appointment[]>("appointments", "/appointments");
  const [filter, setFilter] = useState("all");
  const { meta } = useWorkspace();
  const [search, setSearch] = useState("");
  const now = new Date();
  const items = (data.data || []).filter(
    (a) =>
      (filter === "all" ||
        (filter === "upcoming" && new Date(a.starts_at) >= now) ||
        (filter === "past" && new Date(a.starts_at) < now) ||
        (filter === "result" && a.local_result)) &&
      (!search || a.seller?.toLowerCase().includes(search.toLowerCase())),
  );
  return (
    <>
      <PageHeader
        eyebrow="CONFIRMED TIME, CLEAR CONTEXT"
        title="Seller appointments"
        description="A shared view of source appointments and locally recorded outcomes."
        actions={
          <Link className="btn btn-secondary" to="/leads">
            <Plus size={16} />
            Record from a lead
          </Link>
        }
      />
      <div className="calendar-info">
        <CalendarDays size={21} />
        <span>
          All times displayed in <strong>{meta.timezone}</strong>. No
          invitations, calls or reminders are sent.
        </span>
      </div>
      <div className="table-card">
        <div className="leads-toolbar">
          <div className="segmented">
            {[
              ["all", "All appointments"],
              ["upcoming", "Upcoming"],
              ["past", "Past"],
              ["result", "Result recorded"],
            ].map(([key, label]) => (
              <button
                key={key}
                className={filter === key ? "active" : ""}
                onClick={() => setFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>
          <input
            aria-label="Filter appointments by seller"
            placeholder="Filter by seller name"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {data.isPending ? (
          <Loading />
        ) : data.isError ? (
          <ErrorState error={data.error} retry={() => data.refetch()} />
        ) : items.length ? (
          <div className="appointment-cards">
            {items.map((a) => (
              <AppointmentCard key={a.id} appointment={a} />
            ))}
          </div>
        ) : (
          <Empty
            title="No appointments in this view"
            description="Appointments appear when source data is available or you record a confirmed appointment from a seller profile."
            action={
              <Link className="btn btn-secondary" to="/leads">
                Browse sellers <ArrowRight size={15} />
              </Link>
            }
          />
        )}
      </div>
    </>
  );
}

export function ReportsPage() {
  const { meta } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const data = useData<ReportsData>("reports", "/reports?" + params);
  const dashboard = useData<DashboardData>("dashboard", "/dashboard?" + params);
  const action = useAction();
  function filter(k: string, v: string) {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p);
  }
  return (
    <>
      <PageHeader
        eyebrow="MEASURE WHAT’S ACTUALLY RECORDED"
        title="Acquisitions reports"
        description="Transparent definitions. Explicit denominators. No invented conversions."
        actions={
          <Button
            variant="secondary"
            onClick={() =>
              action.run(() =>
                download(
                  "/reports/export?" + params,
                  "acquisitions-report.csv",
                ),
              )
            }
          >
            <ArrowDownToLine size={16} />
            Export report
          </Button>
        }
      />
      <div className="filter-bar report-filters">
        <Filter size={16} />
        <label>
          Source created from
          <input
            type="date"
            value={params.get("from_date") || ""}
            onChange={(e) => filter("from_date", e.target.value)}
          />
        </label>
        <label>
          Through
          <input
            type="date"
            value={params.get("to_date") || ""}
            onChange={(e) => filter("to_date", e.target.value)}
          />
        </label>
        <label>
          Source
          <select
            value={params.get("source") || ""}
            onChange={(e) => filter("source", e.target.value)}
          >
            <option value="">All lead sources</option>
            {meta.sources.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          Manager
          <select
            value={params.get("manager") || ""}
            onChange={(e) => filter("manager", e.target.value)}
          >
            <option value="">All managers</option>
            {meta.managers.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <Button variant="ghost" onClick={() => setParams({})}>
          Reset
        </Button>
      </div>
      {data.isPending ? (
        <Loading />
      ) : data.isError ? (
        <ErrorState error={data.error} retry={() => data.refetch()} />
      ) : (
        <>
          <div className="report-scope">
            <span>
              <Database size={16} />
              <strong>{data.data.total.toLocaleString()}</strong> seller leads
              in this report
            </span>
            <Badge tone="neutral">
              Unknown dates are not filled with import dates
            </Badge>
          </div>
          <div className="report-rates">
            {data.data.rates.map((r) => (
              <div className="rate-card" key={r.label}>
                <span>{r.label}</span>
                <strong>{r.percent === null ? "—" : `${r.percent}%`}</strong>
                <div className="rate-track">
                  <span style={{ width: `${r.percent || 0}%` }} />
                </div>
                <p>
                  {r.numerator.toLocaleString()} /{" "}
                  {r.denominator.toLocaleString()}{" "}
                  {r.denominator === 0 ? "· Not calculable" : ""}
                </p>
                <details>
                  <summary>Metric definition</summary>
                  <p>{r.definition}</p>
                </details>
              </div>
            ))}
          </div>
          <div className="reports-grid">
            <Panel
              title="Lead volume over time"
              subtitle="Monthly counts by original source creation date."
            >
              <div className="volume-chart">
                {Object.keys(data.data.volume).length ? (
                  Object.entries(data.data.volume).map(([month, n]) => (
                    <Link
                      key={month}
                      to={`/leads?from_date=${month}-01&to_date=${month}-${new Date(Number(month.slice(0, 4)), Number(month.slice(5)), 0).getDate()}`}
                    >
                      <strong>{n}</strong>
                      <div>
                        <span
                          style={{
                            height: `${Math.max((n / Math.max(...Object.values(data.data.volume))) * 100, 3)}%`,
                          }}
                        />
                      </div>
                      <small>{month}</small>
                    </Link>
                  ))
                ) : (
                  <div className="mini-empty">
                    No original creation dates recorded.
                  </div>
                )}
              </div>
              <div className="panel-footnote">
                {data.data.unknown_creation_dates} leads have an unknown
                creation date and are excluded from this chart.
              </div>
            </Panel>
            <Panel
              title="Lead aging"
              subtitle="Age from source creation, never from import time."
            >
              <ReportBars values={data.data.aging} />
            </Panel>
          </div>
          <div className="reports-grid three">
            <Panel title="Leads by pipeline stage">
              <div className="report-stage-list">
                {Object.entries(data.data.stages).map(([stage, n]) => (
                  <Link to={`/leads?stage=${stage}`} key={stage}>
                    <StageBadge code={stage} />
                    <strong>{n}</strong>
                    <ArrowUpRight size={13} />
                  </Link>
                ))}
                {!data.data.total && (
                  <div className="mini-empty">No pipeline records.</div>
                )}
              </div>
            </Panel>
            <Panel title="Leads by source">
              <ReportBars
                values={Object.fromEntries(
                  (dashboard.data?.breakdowns.source || []).map((d) => [
                    d.label,
                    d.value,
                  ]),
                )}
                filter="source"
              />
            </Panel>
            <Panel title="Leads by state">
              <ReportBars
                values={Object.fromEntries(
                  (dashboard.data?.breakdowns.state || []).map((d) => [
                    d.label,
                    d.value,
                  ]),
                )}
                filter="state"
              />
            </Panel>
          </div>
          <div className="reports-grid">
            <Panel title="Data & follow-up checks">
              <div className="report-checks">
                {Object.entries(data.data.counts).map(([key, n]) => (
                  <Link
                    key={key}
                    to={`/leads?metric=${({ never_verified_contact: "never_contacted", contact_attempts: "contact_attempts", no_recorded_attempt: "no_recorded_attempt", no_recent_dated_activity_30_days: "stale", stale_activity_leads: "stale_activity_leads", unknown_activity_recency: "unknown_activity_recency", missing_contact_information: "missing_contact", overdue_leads: "overdue" } as Record<string, string>)[key] || "total"}`}
                  >
                    <span>{human(key)}</span>
                    <strong>{n}</strong>
                    <ArrowUpRight size={14} />
                  </Link>
                ))}
              </div>
            </Panel>
            <Panel
              title="Average observed time in stage"
              subtitle="Completed observed intervals only; not fabricated historical durations."
            >
              {data.data.stage_duration.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>STAGE</th>
                        <th>AVERAGE DAYS</th>
                        <th>INTERVALS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.data.stage_duration.map((s) => (
                        <tr key={s.stage}>
                          <td>
                            <StageBadge code={s.stage} />
                          </td>
                          <td>{s.average_days}</td>
                          <td>{s.observed_completed_intervals}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="unavailable">
                  <Info size={22} />
                  <strong>Not enough stage history</strong>
                  <p>
                    Requires an observed stage entry and a subsequent stage
                    transition. Source history is not assumed.
                  </p>
                </div>
              )}
            </Panel>
          </div>
          <Notice>
            {data.data.limitations.map((l) => (
              <p key={l}>{l}</p>
            ))}
          </Notice>
        </>
      )}
    </>
  );
}
function ReportBars({
  values,
  filter,
}: {
  values: Record<string, number>;
  filter?: string;
}) {
  const max = Math.max(...Object.values(values), 1);
  return Object.keys(values).length ? (
    <div className="bars">
      {Object.entries(values).map(([label, n], i) => {
        const content = (
          <>
            <div>
              <span>
                <i className={`bar-color stage-${i % 5}`} />
                {label}
              </span>
              <strong>{n}</strong>
            </div>
            <div className="bar-track">
              <span style={{ width: `${(n / max) * 100}%` }} />
            </div>
          </>
        );
        return filter ? (
          <Link
            key={label}
            to={`/leads?${filter}=${encodeURIComponent(label === "Unknown" ? "__unknown__" : label)}`}
          >
            {content}
          </Link>
        ) : (
          <div key={label} className="report-bar-item">
            {content}
          </div>
        );
      })}
    </div>
  ) : (
    <div className="mini-empty">No recorded data for this breakdown.</div>
  );
}

export function InsightsPage() {
  const insights = useData<Insight[]>("insights", "/insights");
  const status = useData<AIStatus>("ai-status", "/ai/status");
  return (
    <>
      <PageHeader
        eyebrow="EVIDENCE BEFORE ASSUMPTION"
        title="AI & lead intelligence"
        description="Private analysis that knows the difference between a fact and a guess."
        actions={
          <Link className="btn btn-primary" to="/leads">
            <Sparkles size={16} />
            Analyze from a lead
          </Link>
        }
      />
      <div className="ai-status-grid">
        <div className="ai-feature">
          <span className="ai-feature-icon">
            <Sparkles size={25} />
          </span>
          <div>
            <Badge tone={status.data?.available ? "green" : "neutral"}>
              {status.data?.groq?.enabled
                ? "Groq configured · review required"
                : status.data?.available
                  ? "Local model ready"
                  : "Rule-based mode"}
            </Badge>
            <h2>Local clarity. Reviewed cloud intelligence.</h2>
            <p>
              {status.data?.groq?.enabled
                ? "Groq is configured for individually approved redacted requests. Local rules remain available; no cloud processing happens during sync."
                : status.data?.message ||
                  "Checking optional local model availability…"}
            </p>
            <div className="row wrap">
              <Badge tone="green">
                <ShieldCheck size={11} />
                {status.data?.groq?.enabled
                  ? "Cloud requests require your approval"
                  : "Cloud AI disabled"}
              </Badge>
              <Badge>No model downloads</Badge>
              <Badge>Human review required</Badge>
            </div>
          </div>
        </div>
        <div className="ai-setup">
          <Terminal size={21} />
          <strong>Optional local Ollama</strong>
          <p>
            Install Ollama yourself, choose an installed model, then set{" "}
            <code>OLLAMA_ENABLED=true</code> and <code>OLLAMA_MODEL</code> in
            your local environment.
          </p>
          <Link to="/settings" className="text-link">
            Configuration & safety <ArrowRight size={14} />
          </Link>
        </div>
      </div>
      <LocalRefreshPanel />
      <Panel
        title="Latest lead analyses"
        subtitle="Cached by meaningful context changes. Unknown fields stay unknown."
        action={<Badge>{insights.data?.length || 0} analyzed leads</Badge>}
      >
        {insights.isPending ? (
          <Loading />
        ) : insights.isError ? (
          <ErrorState error={insights.error} />
        ) : !insights.data.length ? (
          <Empty
            title="Start with one seller’s story"
            description="Open a lead and analyze the available context. Explicit source facts and missing-information checks work even without a language model."
            action={
              <Link className="btn btn-secondary" to="/leads">
                Browse seller leads <ArrowRight size={14} />
              </Link>
            }
          />
        ) : (
          <div className="insight-list">
            {insights.data.map((i) => (
              <Link key={i.id} to={`/leads/${i.lead_id}?view=intelligence`}>
                <div className="insight-icon">
                  <Sparkles size={20} />
                </div>
                <div>
                  <div className="row wrap">
                    <h3>{i.seller}</h3>
                    <Badge tone={i.stale ? "amber" : "green"}>
                      {i.stale
                        ? "New context — refresh needed"
                        : "Evidence-linked"}
                    </Badge>
                    {i.conflicts.length > 0 && (
                      <Badge tone="red">{i.conflicts.length} conflict(s)</Badge>
                    )}
                  </div>
                  <p>{i.summary}</p>
                  <strong className="insight-next">
                    {i.recommended_action}
                  </strong>
                  <small>
                    {i.model_id} · <Timestamp value={i.analysis_at} />
                  </small>
                </div>
                <ArrowUpRight size={17} />
              </Link>
            ))}
          </div>
        )}
      </Panel>
      <Notice>
        Extracted facts link to source references. A model’s quote match is a
        grounding check, not a guarantee of semantic accuracy. Review all
        inferences and conflicts. Drafts use conservative evidence-based
        templates or explicitly reviewed Groq requests, and are never sent to
        sellers.
      </Notice>
    </>
  );
}

export function SyncPage() {
  const query = useQuery({
    queryKey: ["sync", "/sync"],
    queryFn: () => api<SyncState>("/sync"),
    refetchInterval: (q) => (q.state.data?.health === "running" ? 1500 : 15000),
  });
  const action = useAction();
  const [interval, setInterval] = useState(30);
  if (query.isPending) return <Loading />;
  if (query.isError)
    return <ErrorState error={query.error} retry={() => query.refetch()} />;
  const s = query.data;
  return (
    <>
      <PageHeader
        eyebrow="FRESH DATA. HONEST STATUS."
        title="REsimpli sync status"
        description="Read-only synchronization with an auditable record of every run."
        actions={
          <Button
            busy={action.busy || s.health === "running"}
            onClick={() =>
              action.run(() => post("/sync/run"), "Read-only sync queued")
            }
          >
            <RefreshCw size={16} />
            Sync now
          </Button>
        }
      />
      <div className="sync-overview">
        <div className="sync-main-status">
          <span
            className={`sync-symbol ${s.health === "success" ? "success" : ""}`}
          >
            <CloudDownload size={28} />
          </span>
          <div>
            <div className="row wrap">
              <h2>
                {s.mode === "live"
                  ? "REsimpli · live adapter"
                  : s.mode === "fixture"
                    ? "Synthetic fixture adapter"
                    : "Integration not configured"}
              </h2>
              <Badge
                tone={
                  s.health === "success"
                    ? "green"
                    : s.health === "partial"
                      ? "amber"
                      : s.health === "failed"
                        ? "red"
                        : "neutral"
                }
              >
                {s.health === "never" ? "Never synchronized" : human(s.health)}
              </Badge>
            </div>
            <p>
              {s.mode === "fixture"
                ? "Fictional records for local testing. Not evidence of a working account integration."
                : s.live_verified
                  ? "An account sync has completed. Review run details for scope and freshness."
                  : "No successful live account sync has been verified."}
            </p>
            <div className="row wrap">
              <Badge tone={s.credentials_configured ? "green" : "neutral"}>
                API key {s.credentials_configured ? "configured" : "missing"}
              </Badge>
              <Badge tone={s.adapter_verified ? "green" : "amber"}>
                Response adapter{" "}
                {s.adapter_verified ? "verified" : "unverified"}
              </Badge>
              <Badge tone="green">Read-only allowlist</Badge>
            </div>
          </div>
        </div>
        <div className="sync-last">
          <span>Last successful LIVE sync</span>
          <strong>
            {s.last_live_success
              ? dateTime(s.last_live_success)
              : "Not yet verified"}
          </strong>
          <small>
            Last success in current history:{" "}
            {s.last_success ? dateTime(s.last_success) : "Never"}
          </small>
        </div>
      </div>
      <div className="sync-config-grid">
        <Panel
          title="Periodic synchronization"
          subtitle="Runs only while the application is open/running."
        >
          <div className="scheduler-state">
            <span
              className={`status-dot ${s.scheduler.enabled ? "green" : "gray"}`}
            />
            <strong>
              {s.scheduler.enabled ? "Scheduler running" : "Scheduler stopped"}
            </strong>
            <Badge>Every {s.scheduler.interval_minutes} minutes</Badge>
          </div>
          <div className="row wrap">
            <Field label="Interval in minutes">
              <input
                type="number"
                min="1"
                max="10080"
                value={interval}
                onChange={(e) => setInterval(Number(e.target.value))}
              />
            </Field>
            <Button
              busy={action.busy}
              variant={s.scheduler.enabled ? "secondary" : "primary"}
              onClick={() =>
                action.run(
                  () =>
                    patch("/sync/scheduler", {
                      enabled: !s.scheduler.enabled,
                      interval_minutes: s.scheduler.enabled
                        ? s.scheduler.interval_minutes
                        : interval,
                    }),
                  s.scheduler.enabled
                    ? "Periodic sync stopped"
                    : "Periodic sync started",
                )
              }
            >
              {s.scheduler.enabled ? <Square size={14} /> : <Play size={14} />}
              {s.scheduler.enabled ? "Stop scheduler" : "Start scheduler"}
            </Button>
          </div>
          <p className="panel-description">
            Default target: 30 minutes. Requests are throttled below the
            documented limit. Runs do not overlap; failures retry with bounded
            exponential backoff. Disabling does not cancel an in-flight read.
          </p>
        </Panel>
        <Panel
          title="Verified boundaries"
          action={<ShieldCheck size={18} className="text-green" />}
        >
          <ul className="boundary-list">
            <li>
              <CheckCircle2 size={15} />
              Seller leads, activities, calls and seller appointments only
            </li>
            <li>
              <CheckCircle2 size={15} />
              No CRM edits, deletion, notes or status writes
            </li>
            <li>
              <CheckCircle2 size={15} />
              External lead creation is disabled
            </li>
            <li>
              <CheckCircle2 size={15} />
              No messaging, emailing or dialing endpoints
            </li>
          </ul>
          <Link className="text-link" to="/settings">
            Configure account access locally <ArrowRight size={14} />
          </Link>
        </Panel>
      </div>
      <Notice tone={s.mode === "fixture" ? "warning" : "info"}>
        {s.notice} No reliable modification-date filter is documented, so sync
        uses paginated reconciliation; it never claims unsupported incremental
        updates.
      </Notice>
      <Panel
        title="Synchronization history"
        subtitle="Fetched/created/updated/skipped are lead counts. Failed counts include failed requests/resources."
      >
        {s.runs.length ? (
          <div className="table-wrap">
            <table className="sync-table">
              <thead>
                <tr>
                  <th>RUN / STARTED</th>
                  <th>RESULT</th>
                  <th>FETCHED</th>
                  <th>CREATED</th>
                  <th>UPDATED</th>
                  <th>SKIPPED</th>
                  <th>FAILED</th>
                  <th>DETAILS</th>
                </tr>
              </thead>
              <tbody>
                {s.runs.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <strong>
                        #{r.id} · {r.mode}
                      </strong>
                      <small>
                        <Timestamp value={r.started_at} />
                      </small>
                    </td>
                    <td>
                      <Badge
                        tone={
                          r.result === "success"
                            ? "green"
                            : r.result === "partial"
                              ? "amber"
                              : r.result === "failed"
                                ? "red"
                                : "blue"
                        }
                      >
                        {human(r.result)}
                      </Badge>
                      <small>
                        {r.finished_at
                          ? "Finished " + dateTime(r.finished_at)
                          : "In progress"}
                      </small>
                    </td>
                    <td>{r.fetched}</td>
                    <td>{r.created}</td>
                    <td>{r.updated}</td>
                    <td>{r.skipped}</td>
                    <td className={r.failed ? "text-red" : ""}>{r.failed}</td>
                    <td>
                      <details>
                        <summary>
                          {r.errors.length
                            ? "Review errors"
                            : "Resource counts"}
                        </summary>
                        {r.errors.map((e, i) => (
                          <p className="text-red" key={i}>
                            {e}
                          </p>
                        ))}
                        <pre>{JSON.stringify(r.resources, null, 2)}</pre>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="No synchronization has run"
            description="Configure a verified live adapter in the backend environment, or explicitly use synthetic fixture mode for local testing."
          />
        )}
      </Panel>
    </>
  );
}

export function SettingsPage() {
  const data = useData<SettingsData>("settings", "/settings");
  if (data.isPending) return <Loading />;
  if (data.isError)
    return <ErrorState error={data.error} retry={() => data.refetch()} />;
  return <SettingsForm settings={data.data} />;
}
function SettingsForm({ settings: s }: { settings: SettingsData }) {
  const [sectionParams, setSectionParams] = useSearchParams();
  const section = ["connections", "operations", "runtime"].includes(
    sectionParams.get("section") || "connections",
  )
    ? sectionParams.get("section") || "connections"
    : "connections";
  const { meta } = useWorkspace();
  const action = useAction();
  const [rules, setRules] = useState(s.priority_rules);
  const [mapping, setMapping] = useState(
    JSON.stringify(s.stage_mapping, null, 2),
  );
  const [stageLabel, setStageLabel] = useState("");
  const [stageCode, setStageCode] = useState("");
  const [edited, setEdited] = useState<Record<string, string>>({});
  return (
    <>
      <PageHeader
        eyebrow="LOCAL BY DEFAULT. SAFE BY DESIGN."
        title="Workspace settings"
        description="Configure your rules and mappings. Manage private connections, clear priorities and your source mappings."
      />
      <div className="settings-safety">
        <span>
          <ShieldCheck size={28} />
        </span>
        <div>
          <h2>Human decisions are the control plane.</h2>
          <p>
            This application has no automatic SMS, email, calls, dialer or
            seller outreach functionality. Local task completion never means
            communication occurred.
          </p>
        </div>
        <Badge tone="green">Enforced in code</Badge>
      </div>
      <div
        className="settings-navigation"
        role="tablist"
        aria-label="Workspace settings sections"
        onKeyDown={navigateTabs}
      >
        {[
          ["connections", "Connections & AI"],
          ["operations", "Pipeline & priorities"],
          ["runtime", "Runtime & backups"],
        ].map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={section === key}
            tabIndex={section === key ? 0 : -1}
            onClick={() =>
              setSectionParams(key === "connections" ? {} : { section: key })
            }
            className={section === key ? "active" : ""}
          >
            {label}
          </button>
        ))}
      </div>
      {section === "connections" && <IntegrationSettings />}
      <div
        className="settings-grid settings-focused"
        style={{ display: section === "connections" ? "none" : undefined }}
      >
        <div
          className="stack"
          style={{ display: section !== "operations" ? "none" : undefined }}
        >
          <IdentityCadencePanel settings={s} />
          <Panel
            title="Business priorities"
            subtitle="Transparent deterministic weights for the daily work queue. Heat, sale-likelihood and negative-equity weights are added to the task score, then capped at 100."
            action={<SlidersIcon />}
          >
            <form
              className="settings-form"
              onSubmit={async (e) => {
                e.preventDefault();
                await action.run(
                  () => patch("/settings", { priority_rules: rules }),
                  "Priority rules saved",
                );
              }}
            >
              <div className="info-grid">
                {Object.entries(rules).map(([key, value]) => (
                  <Field label={human(key)} key={key}>
                    <input
                      type="number"
                      min="0"
                      max="365"
                      value={value}
                      onChange={(e) =>
                        setRules((r) => ({
                          ...r,
                          [key]: Number(e.target.value),
                        }))
                      }
                    />
                  </Field>
                ))}
              </div>
              <Button busy={action.busy} type="submit">
                <Save size={15} />
                Save priority rules
              </Button>
            </form>
          </Panel>
          <Panel
            title="Source status mapping"
            subtitle="Preserves the original source status. Unmapped values remain visibly unmapped."
          >
            {s.source_statuses?.length ? (
              <div className="stack">
                <h3>Status titles your CRM actually sent</h3>
                <p className="muted">
                  These are counted from real synced leads. Choose a stage for
                  each one; anything left is shown as unmapped instead of being
                  guessed.
                </p>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Source status</th>
                      <th>Leads</th>
                      <th>Local stage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.source_statuses.map((row) => (
                      <tr key={row.title}>
                        <td>
                          {row.title}
                          {row.mapped ? null : (
                            <Badge tone="amber">unmapped</Badge>
                          )}
                        </td>
                        <td>{row.leads}</td>
                        <td>
                          <select
                            aria-label={`Stage for ${row.title}`}
                            value={row.stage}
                            onChange={(e) =>
                              action.run(
                                () =>
                                  patch("/settings", {
                                    stage_mapping: {
                                      ...s.stage_mapping,
                                      [row.title.trim().toLowerCase()]:
                                        e.target.value,
                                    },
                                  }),
                                "Source status saved",
                              )
                            }
                          >
                            {meta.stages.map((stage) => (
                              <option key={stage.code} value={stage.code}>
                                {stage.label}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Notice>
                No source status has been seen yet. Run a sync and the titles your
                CRM sends will appear here with their counts.
              </Notice>
            )}
            <form
              className="settings-form"
              onSubmit={async (e) => {
                e.preventDefault();
                await action.run(async () => {
                  let parsed: unknown;
                  try {
                    parsed = JSON.parse(mapping);
                  } catch {
                    throw new Error("Status mapping must be valid JSON");
                  }
                  return patch("/settings", { stage_mapping: parsed });
                }, "Source status mapping saved");
              }}
            >
              <Field label="Source status (lowercase) → local stage code">
                <textarea
                  className="code-editor"
                  rows={12}
                  spellCheck={false}
                  value={mapping}
                  onChange={(e) => setMapping(e.target.value)}
                />
              </Field>
              <Notice>
                Mapping changes apply on subsequent refreshed source records;
                existing local overrides are not destroyed. To apply to
                unchanged CRM records, allow the periodic deep refresh or change
                the adapter context deliberately.
              </Notice>
              <Button busy={action.busy}>
                <Save size={15} />
                Save mapping
              </Button>
            </form>
          </Panel>
          <Panel
            title="Pipeline labels & stages"
            subtitle="Rename labels or add stages without destroying source values."
          >
            <div className="pipeline-settings">
              {meta.stages.map((stage) => (
                <div key={stage.code}>
                  <code>{stage.code}</code>
                  <input
                    aria-label={`Label for ${stage.code}`}
                    value={edited[stage.code] ?? stage.label}
                    onChange={(e) =>
                      setEdited((v) => ({ ...v, [stage.code]: e.target.value }))
                    }
                  />
                  <Button
                    variant="ghost"
                    disabled={!edited[stage.code]}
                    busy={action.busy}
                    onClick={() =>
                      action.run(
                        () =>
                          patch(`/pipeline/stages/${stage.code}`, {
                            label: edited[stage.code],
                          }),
                        "Pipeline label saved",
                      )
                    }
                  >
                    <Save size={14} />
                  </Button>
                </div>
              ))}
            </div>
            <form
              className="add-stage-form"
              onSubmit={async (e) => {
                e.preventDefault();
                const r = await action.run(
                  () =>
                    post("/pipeline/stages", {
                      code: stageCode,
                      label: stageLabel,
                    }),
                  "Pipeline stage added",
                );
                if (r) {
                  setStageCode("");
                  setStageLabel("");
                }
              }}
            >
              <Field label="New stage code">
                <input
                  required
                  pattern="[a-z][a-z0-9_]{1,63}"
                  value={stageCode}
                  placeholder="e.g. due_diligence"
                  onChange={(e) => setStageCode(e.target.value)}
                />
              </Field>
              <Field label="Display label">
                <input
                  required
                  value={stageLabel}
                  onChange={(e) => setStageLabel(e.target.value)}
                  placeholder="Due Diligence"
                />
              </Field>
              <Button busy={action.busy} type="submit" variant="secondary">
                <Plus size={15} />
                Add stage
              </Button>
            </form>
          </Panel>
        </div>
        <div
          className="stack"
          style={{ display: section !== "runtime" ? "none" : undefined }}
        >
          <Panel title="Runtime & privacy" action={<HardDrive size={18} />}>
            <div className="settings-facts">
              <div>
                <span>Business timezone</span>
                <strong>{s.timezone}</strong>
              </div>
              <div>
                <span>Integration mode</span>
                <Badge>{s.mode}</Badge>
              </div>
              <div>
                <span>Network binding</span>
                <strong>
                  {s.local_only
                    ? "Loopback only"
                    : "Explicit remote/preview binding"}
                </strong>
              </div>
              <div>
                <span>Workspace authentication</span>
                <Badge tone={s.authentication_enabled ? "green" : "neutral"}>
                  {s.authentication_enabled
                    ? "Enabled"
                    : "Local single-user mode"}
                </Badge>
              </div>
              <div>
                <span>External writes</span>
                <Badge tone="green">Disabled</Badge>
              </div>
              <div>
                <span>Upload limit</span>
                <strong>
                  {s.max_upload_mb} MB · {s.max_import_rows.toLocaleString()}{" "}
                  rows
                </strong>
              </div>
              <div>
                <span>Local model</span>
                <strong>
                  {s.ollama_enabled
                    ? s.ollama_model || "Not selected"
                    : "Optional · disabled"}
                </strong>
              </div>
            </div>
          </Panel>
          <Panel
            title="Connection safeguards"
            subtitle="Keys are configuration, not proof of integration."
          >
            <div className="config-instructions">
              <p>
                Use Connections above to save replacement keys privately. CRM
                reads require an account-verified response adapter; Groq
                requires a reviewed redacted preview for every request.
              </p>
              <p>
                Scheduled sync never invokes Groq. CRM creation, edits and
                seller communication remain disabled.
              </p>
            </div>
            <Link className="text-link" to="/sync">
              Review synchronization health <ArrowRight size={14} />
            </Link>
          </Panel>
          <BackupsPanel />
          <Panel title="Optional local intelligence">
            <div className="config-instructions">
              <p>
                Ollama is optional. The app never downloads a model
                automatically and accepts only a loopback Ollama URL.
              </p>
              <pre>
                OLLAMA_ENABLED=true{`\n`}OLLAMA_URL=http://127.0.0.1:11434{`\n`}
                OLLAMA_MODEL=your_installed_model
              </pre>
              <p>
                Rules and conservative draft templates work without a language
                model. AI output remains reviewable and evidence-linked.
              </p>
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
function SlidersIcon() {
  return <Settings2 size={18} className="muted" />;
}

type BackupItem = {
  name: string;
  size_bytes: number;
  created_at: string;
  reason: "scheduled" | "manual";
};
type BackupOverview = {
  enabled: boolean;
  keep: number;
  hour_utc: number;
  folder: string;
  second_folder: string | null;
  status: {
    ok?: boolean;
    detail?: string;
    copied_at?: string;
    file?: string;
  };
  backups: BackupItem[];
};
function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
export function BackupsPanel() {
  const data = useData<BackupOverview>("backups", "/backups");
  const action = useAction();
  const [deleting, setDeleting] = useState<string | null>(null);
  if (data.isPending) return <Panel title="Backup & restore"><Loading /></Panel>;
  if (data.isError)
    return (
      <Panel title="Backup & restore">
        <ErrorState error={data.error} retry={() => data.refetch()} />
      </Panel>
    );
  const overview = data.data;
  async function remove(name: string) {
    if (
      !window.confirm(
        `Delete ${name}? This removes the copy from this computer and cannot be undone.`,
      )
    )
      return;
    setDeleting(name);
    await action.run(
      () =>
        api(`/backups/${encodeURIComponent(name)}?confirm=${encodeURIComponent("DELETE BACKUP")}`, {
          method: "DELETE",
        }),
      "Backup deleted",
    );
    setDeleting(null);
  }
  return (
    <Panel
      title="Backup & restore"
      subtitle="A verified copy of the database, taken automatically every night."
      className="backup-panel"
      action={<HardDrive size={18} />}
    >
      <div className="settings-facts">
        <div>
          <span>Automatic backups</span>
          <Badge tone={overview.enabled ? "green" : "neutral"}>
            {overview.enabled ? `Daily at ${overview.hour_utc}:00 UTC` : "Disabled"}
          </Badge>
        </div>
        <div>
          <span>Copies kept</span>
          <strong>{overview.keep} scheduled · manual copies never pruned</strong>
        </div>
        <div>
          <span>Stored in</span>
          <strong>{overview.folder}</strong>
        </div>
      </div>
      <SecondFolderForm
        current={overview.second_folder}
        status={overview.status}
        onSaved={() => data.refetch()}
      />
      <div className="toolbar">
        <Button
          busy={action.busy}
          onClick={() =>
            action.run(() => post("/backups"), "Backup created and verified")
          }
        >
          <Save size={15} /> Create a backup now
        </Button>
      </div>
      {overview.backups.length === 0 ? (
        <Empty
          title="No backups yet"
          description="The first automatic copy runs tonight. Create one now before importing or editing records."
        />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Copy</th>
                <th>Taken</th>
                <th>Size</th>
                <th>Reason</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {overview.backups.map((item) => (
                <tr key={item.name}>
                  <td>
                    <code>{item.name}</code>
                  </td>
                  <td>
                    <Timestamp value={item.created_at} />
                  </td>
                  <td>{fileSize(item.size_bytes)}</td>
                  <td>
                    <Badge tone={item.reason === "scheduled" ? "green" : "neutral"}>
                      {item.reason}
                    </Badge>
                  </td>
                  <td className="row-actions">
                    <Button
                      variant="secondary"
                      onClick={() =>
                        action.run(
                          () => download(`/backups/${encodeURIComponent(item.name)}`, item.name),
                          "Backup downloaded",
                        )
                      }
                    >
                      <ArrowDownToLine size={15} /> Download
                    </Button>
                    <Button
                      variant="danger"
                      busy={deleting === item.name}
                      onClick={() => remove(item.name)}
                    >
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="config-instructions">
        <p>
          Restore only while the application is stopped: replace{" "}
          <code>data/acquisitions.db</code> with the downloaded copy, then start
          again. Backups contain seller records, so treat them as confidential
          and keep <code>.env</code> separate.
        </p>
      </div>
    </Panel>
  );
}

function SecondFolderForm({
  current,
  status,
  onSaved,
}: {
  current: string | null;
  status: BackupOverview["status"];
  onSaved: () => void;
}) {
  const action = useAction();
  const [folder, setFolder] = useState(current || "");
  return (
    <form
      className="settings-form"
      onSubmit={async (e) => {
        e.preventDefault();
        const saved = await action.run(
          () =>
            patch<{ second_folder: string | null }>("/backups/config", {
              second_folder: folder.trim() || null,
            }),
          "Second backup folder saved",
        );
        if (saved) onSaved();
      }}
    >
      <Field
        label="Second backup folder (absolute path)"
        hint="An existing folder on another drive, or a folder your sync tool watches. The database copy is still verified after it is written."
      >
        <input
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
          placeholder="/Volumes/Backup/acquisitions"
        />
      </Field>
      <div className="row wrap">
        <Button type="submit" variant="secondary" busy={action.busy}>
          <Save size={15} /> Save folder
        </Button>
        {current ? (
          <Badge tone={status?.ok ? "green" : status?.ok === false ? "amber" : "neutral"}>
            {status?.ok === true
              ? "Last mirrored copy verified"
              : status?.ok === false
                ? "Last mirrored copy failed"
                : "No mirrored copy yet"}
          </Badge>
        ) : (
          <Badge>No second folder configured</Badge>
        )}
      </div>
      {status?.detail && <p className="muted">{status.detail}</p>}
      {action.error && <p className="muted">{action.error}</p>}
    </form>
  );
}

function IdentityCadencePanel({ settings }: { settings: SettingsData }) {
  const action = useAction();
  const [sender, setSender] = useState(settings.sender_name || "");
  const [company, setCompany] = useState(settings.company_name || "");
  const [cadence, setCadence] = useState((settings.cadence || []).join(", "));
  return (
    <>
      <Panel
        title="Sender identity"
        subtitle="The only name and company the draft validator accepts."
      >
        <form
          className="settings-form"
          onSubmit={async (e) => {
            e.preventDefault();
            await action.run(
              () =>
                patch("/settings", {
                  sender_name: sender.trim(),
                  company_name: company.trim(),
                }),
              "Sender identity saved",
            );
          }}
        >
          <div className="info-grid">
            <Field label="Sender name">
              <input value={sender} onChange={(e) => setSender(e.target.value)} />
            </Field>
            <Field label="Company">
              <input value={company} onChange={(e) => setCompany(e.target.value)} />
            </Field>
          </div>
          <p className="muted">
            Checks run in code and reject a draft that does not include this
            identity, the street address and the opt-out sentence.
          </p>
          <Button type="submit" busy={action.busy}>
            <Save size={15} /> Save identity
          </Button>
        </form>
      </Panel>
      <Panel
        title="Follow-up cadence"
        subtitle="Days after the first message. Drafts are prepared; nothing is ever sent."
      >
        <form
          className="settings-form"
          onSubmit={async (e) => {
            e.preventDefault();
            const days = cadence
              .split(",")
              .map((part) => Number(part.trim()))
              .filter((n) => Number.isFinite(n));
            const result = await action.run(
              () => patch("/settings", { cadence: days }),
              "Cadence saved",
            );
            if (result) setCadence(days.join(", "));
          }}
        >
          <Field
            label="Sequence days"
            hint="Whole days after the first outreach, ascending, at most 12 steps (e.g. 0, 3, 7, 14, 30, 60)."
          >
            <input value={cadence} onChange={(e) => setCadence(e.target.value)} />
          </Field>
          <Button type="submit" busy={action.busy}>
            <Save size={15} /> Save cadence
          </Button>
          {action.error && <p className="muted">{action.error}</p>}
        </form>
      </Panel>
    </>
  );
}
