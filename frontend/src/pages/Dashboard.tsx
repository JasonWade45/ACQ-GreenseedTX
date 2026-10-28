import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Filter,
  RefreshCw,
  Search,
  Sparkles,
  TrendingUp,
  Upload,
  Users,
} from "lucide-react";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Loading,
  Notice,
  PageHeader,
  Panel,
  useAction,
  useData,
  useWorkspace,
} from "../components";
import { dateTime, download, post } from "../api";
import type {
  DashboardData,
  Queue,
  QueueItem,
  SyncState,
  Breakdown,
} from "../types";

function SectionLabel({
  index,
  title,
  hint,
}: {
  index: string;
  title: string;
  hint?: string;
}) {
  return (
    <div className="section-label">
      <span className="section-index">{index}</span>
      <strong>{title}</strong>
      {hint && <span className="section-hint">{hint}</span>}
    </div>
  );
}

export default function Dashboard() {
  const { meta } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const [showFilters, setShowFilters] = useState(false);
  const query = params.toString();
  const data = useData<DashboardData>("dashboard", "/dashboard?" + query);
  const queue = useData<Queue>("queue", "/queue?page_size=5");
  const sync = useData<SyncState>("sync", "/sync");
  const action = useAction();
  if (data.isPending) return <Loading />;
  if (data.isError)
    return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const metrics = data.data.metrics;
  const value = (key: string) => metrics.find((m) => m.key === key)?.value || 0;
  const target = (metric: string) =>
    `/leads?${new URLSearchParams({ ...Object.fromEntries(params), metric }).toString()}`;
  const focus: QueueItem[] = [];
  const seen = new Set<string>();
  for (const key of ["overdue", "today", "callbacks", "appointments", "new"])
    for (const item of queue.data?.sections[key] || []) {
      const id = item.lead.id + ":" + (item.followup?.id || 0);
      if (!seen.has(id)) {
        seen.add(id);
        focus.push(item);
      }
    }
  const nowLabel = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: meta.timezone,
  }).format(new Date());
  function filter(key: string, value: string) {
    const p = new URLSearchParams(params);
    if (value) p.set(key, value);
    else p.delete(key);
    setParams(p);
  }
  const secondary = metrics.filter((m) =>
    [
      "contacted",
      "attempting_contact",
      "upcoming",
      "appointments",
      "missing",
      "dnc",
      "stage:qualified",
      "stage:offer_made",
    ].includes(m.key),
  );
  return (
    <>
      <PageHeader
        eyebrow="YOUR DAILY COMMAND CENTER"
        title="Acquisitions overview"
        description="A clear view of your pipeline. A confident next move."
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() =>
                action.run(() =>
                  download("/leads/export?" + query, "seller-leads.csv"),
                )
              }
            >
              <ArrowDownToLine size={16} />
              Export
            </Button>
            <Link className="btn btn-primary" to="/imports">
              <Upload size={16} />
              Import leads
            </Link>
          </>
        }
      />
      <div className="overview-toolbar">
        <div className="row">
          <CalendarDays size={15} />
          <span>{nowLabel}</span>
          <span className="separator">|</span>
          <span className="muted">{meta.timezone.replace("_", " ")}</span>
        </div>
        <div className="row">
          <Link className="btn btn-ghost" to="/leads">
            <Search size={14} />
            Search leads
          </Link>
          <Button variant="ghost" onClick={() => setShowFilters(!showFilters)}>
            <Filter size={14} />
            Filters
            {params.size > 0 && <Badge tone="green">{params.size}</Badge>}
          </Button>
          <span className="data-live">
            <i className="status-dot green" />
            Database-backed
          </span>
        </div>
      </div>
      {showFilters && (
        <div className="filter-bar">
          <label>
            Created from
            <input
              type="date"
              aria-label="Created from"
              value={params.get("from_date") || ""}
              onChange={(e) => filter("from_date", e.target.value)}
            />
          </label>
          <label>
            Created through
            <input
              type="date"
              aria-label="Created through"
              value={params.get("to_date") || ""}
              onChange={(e) => filter("to_date", e.target.value)}
            />
          </label>
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
            </select>
          </label>
          <Button variant="ghost" onClick={() => setParams({})}>
            Reset
          </Button>
        </div>
      )}

      <SectionLabel
        index="01"
        title="Today at a glance"
        hint="The numbers that decide your day"
      />
      <div className="hero-metrics">
        {[
          {
            key: "total",
            label: "Total seller leads",
            icon: Users,
            tone: "green",
            note: "Your complete seller pipeline",
          },
          {
            key: "today",
            label: "Follow-ups due today",
            icon: CalendarDays,
            tone: "teal",
            note: "Explicitly scheduled for today",
          },
          {
            key: "overdue",
            label: "Overdue follow-ups",
            icon: CircleAlert,
            tone: "orange",
            note: "Due before today · needs review",
          },
          {
            key: "not_contacted",
            label: "No contact / attempt recorded",
            icon: Clock3,
            tone: "blue",
            note: "No verified contact or attempt",
          },
        ].map(({ key, label, icon: Icon, tone, note }) => (
          <Link
            to={target(key)}
            className={`metric-card metric-${tone}`}
            key={key}
          >
            <div className="metric-top">
              <span>{label}</span>
              <span className="metric-icon">
                <Icon size={19} />
              </span>
            </div>
            <div className="metric-value">
              {value(key).toLocaleString()}
              <ArrowUpRight size={20} />
            </div>
            <div className="metric-note">
              <span className={`tiny-dot ${tone}`} />
              {note}
            </div>
          </Link>
        ))}
      </div>
      {secondary.length > 0 && (
        <div className="small-metrics">
          {secondary.map((m) => (
            <Link key={m.key} to={target(m.key)}>
              <span>{m.label}</span>
              <strong>
                {m.value.toLocaleString()}
                <ArrowUpRight size={14} />
              </strong>
            </Link>
          ))}
        </div>
      )}

      <SectionLabel
        index="02"
        title="Action queue & workspace"
        hint="What needs a human decision right now"
      />
      <div className="dashboard-grid">
        <Panel
          title="Today’s focus"
          subtitle="The next right action, with the context behind it."
          action={
            <Link className="text-link" to="/followups">
              Open work queue <ArrowRight size={15} />
            </Link>
          }
          className="focus-panel"
        >
          <div className="focus-summary">
            <span className="focus-mark">
              <Sparkles size={15} />
            </span>
            <span>
              <strong>
                {(queue.data?.counts.overdue || 0) +
                  (queue.data?.counts.today || 0)}
              </strong>{" "}
              scheduled tasks need your review
            </span>
            <Badge tone="neutral">Human action only</Badge>
          </div>
          {focus.length ? (
            <div className="table-wrap">
              <table className="focus-table">
                <thead>
                  <tr>
                    <th>SELLER / PROPERTY</th>
                    <th>PRIORITY</th>
                    <th>NEXT STEP</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {focus.slice(0, 5).map((item, i) => (
                    <tr key={item.lead.id + ":" + i}>
                      <td>
                        <Link
                          className="seller-cell"
                          to={`/leads/${item.lead.id}`}
                        >
                          <span className={`seller-avatar color-${i % 4}`}>
                            {item.lead.full_name
                              .split(" ")
                              .slice(0, 2)
                              .map((n) => n[0])
                              .join("")}
                          </span>
                          <span>
                            <strong>{item.lead.full_name}</strong>
                            <small>
                              {item.lead.properties[0]?.street_address ||
                                "Property not recorded"}
                            </small>
                          </span>
                        </Link>
                      </td>
                      <td>
                        <Badge
                          tone={
                            item.priority >= 75
                              ? "red"
                              : item.priority >= 50
                                ? "amber"
                                : "blue"
                          }
                        >
                          {item.priority >= 75
                            ? "High"
                            : item.priority >= 50
                              ? "Medium"
                              : "Review"}{" "}
                          · {item.priority}
                        </Badge>
                      </td>
                      <td>
                        <strong className="task-reason">
                          {item.followup?.reason || item.reason}
                        </strong>
                        <small>
                          {item.lead.restriction_status === "unknown"
                            ? "Review contact permissions"
                            : dateTime(
                                item.followup?.due_at,
                                meta.timezone,
                                true,
                              )}
                        </small>
                      </td>
                      <td>
                        <Link
                          className="table-arrow"
                          aria-label={`Open ${item.lead.full_name}`}
                          to={`/leads/${item.lead.id}`}
                        >
                          <ChevronRight size={17} />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="A clean slate for your next move"
              description="Import your seller leads or configure a read-only sync to see a prioritized daily queue."
              action={
                <Link className="btn btn-secondary" to="/imports">
                  Get started <ArrowRight size={15} />
                </Link>
              }
            />
          )}
          <div className="panel-footnote">
            <CheckCircle2 size={13} />
            No follow-up date? It’s unscheduled, not overdue.
          </div>
        </Panel>
        <Panel
          title="Workspace health"
          subtitle="Know what’s current. Know what’s missing."
          className="health-panel"
        >
          <div className="health-row">
            <span className="health-icon">
              <RefreshCw size={17} />
            </span>
            <div>
              <strong>REsimpli synchronization</strong>
              <span>
                {sync.data?.mode === "live"
                  ? "Live read-only integration"
                  : sync.data?.mode === "fixture"
                    ? "Synthetic fixtures only"
                    : "Not connected"}
              </span>
            </div>
            <Link to="/sync">
              <Badge
                tone={
                  sync.data?.health === "success"
                    ? "green"
                    : sync.data?.health === "failed"
                      ? "red"
                      : "neutral"
                }
              >
                {sync.data?.health === "never"
                  ? "Never run"
                  : sync.data?.health || "Loading"}
              </Badge>
            </Link>
          </div>
          <div className="health-detail">
            <span>Last successful live sync</span>
            <strong>
              {sync.data?.last_live_success
                ? dateTime(sync.data.last_live_success, meta.timezone)
                : "Not yet verified"}
            </strong>
          </div>
          <Link to={target("missing")} className="health-attention">
            <CircleAlert size={19} />
            <div>
              <strong>{value("missing")} leads need a data review</strong>
              <span>Missing fields or contact restrictions</span>
            </div>
            <ChevronRight size={17} />
          </Link>
          <div className="health-restriction">
            <CheckCircle2 size={16} />
            <span>
              DNC restrictions are enforced.
              <br />
              No automatic communication exists.
            </span>
          </div>
          <Button
            variant="secondary"
            busy={action.busy}
            onClick={() =>
              action.run(() => post("/sync/run"), "Read-only sync requested")
            }
          >
            <RefreshCw size={14} />
            Run read-only sync
          </Button>
        </Panel>
      </div>

      <SectionLabel
        index="03"
        title="Pipeline"
        hint="Stage by stage, from new lead to closed deal"
      />
      <Panel
        title="Pipeline at a glance"
        subtitle="Current local stages · original source statuses are preserved."
        action={
          <Link className="text-link" to="/leads">
            View all leads <ArrowRight size={15} />
          </Link>
        }
      >
        <div className="pipeline-strip">
          {meta.stages
            .filter((s) => s.code !== "unmapped" || value("stage:unmapped") > 0)
            .map((s, i) => (
              <Link
                key={s.code}
                to={target("stage:" + s.code)}
                className="pipeline-item"
              >
                <div>
                  <span className={`pipeline-dot stage-${i % 5}`} />
                  <span>{s.label}</span>
                </div>
                <strong>{value("stage:" + s.code).toLocaleString()}</strong>
                <div className="pipeline-track">
                  <span
                    style={{
                      width: `${value("total") ? Math.max((value("stage:" + s.code) / value("total")) * 100, 2) : 0}%`,
                    }}
                  />
                </div>
              </Link>
            ))}
        </div>
      </Panel>

      <SectionLabel
        index="04"
        title="Insights"
        hint="Where leads come from and what’s happening"
      />
      <div className="dashboard-lower">
        <Panel
          title="Lead sources"
          subtitle="Where your seller opportunities begin."
          action={<TrendingUp size={17} className="muted" />}
        >
          <Bars
            data={data.data.breakdowns.source}
            filter="source"
            params={params}
          />
        </Panel>
        <Panel
          title="By market & owner"
          subtitle="Source-data breakdowns, not assumed assignments."
        >
          <div className="mini-label">PROPERTY STATE</div>
          <Bars
            data={data.data.breakdowns.state}
            filter="state"
            params={params}
            compact
          />
          <div className="mini-label with-border">ASSIGNED MANAGER</div>
          <Bars
            data={data.data.breakdowns.manager}
            filter="manager"
            params={params}
            compact
          />
        </Panel>
        <Panel
          title="Recent activity"
          subtitle="Source records and local decisions."
          action={
            <Link to="/leads" className="text-link">
              View leads <ArrowUpRight size={14} />
            </Link>
          }
        >
          {data.data.recent_activity.length ? (
            <div className="recent-list">
              {data.data.recent_activity.slice(0, 5).map((a) => (
                <Link to={`/leads/${a.lead_id}`} key={a.id}>
                  <span className="timeline-dot" />
                  <div>
                    <strong>{a.seller}</strong>
                    <p>{a.summary}</p>
                    <small>
                      {dateTime(a.occurred_at || a.recorded_at, meta.timezone)}{" "}
                      · {a.source}
                    </small>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="mini-empty">
              Your activity history will appear here after an import or local
              action.
            </div>
          )}
        </Panel>
      </div>
      {value("total") === 0 && (
        <Notice>
          There are no leads in this filtered view.{" "}
          <Link to="/imports">Import a CSV or Excel workbook</Link>, or set up a
          read-only sync. Demonstration counts are never injected into this
          dashboard.
        </Notice>
      )}
      <details className="metric-definitions">
        <summary>How these numbers are calculated</summary>
        {Object.entries(data.data.definitions).map(([k, v]) => (
          <p key={k}>
            <strong>{k}: </strong>
            {v}
          </p>
        ))}
      </details>
    </>
  );
}
function Bars({
  data,
  filter,
  params,
  compact = false,
}: {
  data: Breakdown[];
  filter: string;
  params: URLSearchParams;
  compact?: boolean;
}) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return data.length ? (
    <div className={`bars ${compact ? "bars-compact" : ""}`}>
      {data.slice(0, compact ? 3 : 6).map((d, i) => (
        <Link
          key={d.label}
          to={`/leads?${new URLSearchParams({ ...Object.fromEntries(params), [filter]: d.label === "Unknown" ? "__unknown__" : d.label }).toString()}`}
        >
          <div>
            <span>
              <i className={`bar-color stage-${i % 5}`} />
              {d.label}
            </span>
            <strong>{d.value.toLocaleString()}</strong>
          </div>
          <div className="bar-track">
            <span style={{ width: `${(d.value / max) * 100}%` }} />
          </div>
        </Link>
      ))}
    </div>
  ) : (
    <div className="mini-empty">No source records available yet.</div>
  );
}
