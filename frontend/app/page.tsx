"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ErrorBox, PageHeader, EmptyState } from "@/components/UI";
import { Dashboard, apiGet, fmtDateTime } from "@/lib/api";
import { useAsync } from "@/components/UI";

const TILE_ORDER: { key: string; group: string }[] = [
  { key: "total_leads", group: "Pipeline" },
  { key: "new_leads", group: "Pipeline" },
  { key: "not_contacted", group: "Pipeline" },
  { key: "attempting_contact", group: "Pipeline" },
  { key: "contacted", group: "Pipeline" },
  { key: "qualified", group: "Pipeline" },
  { key: "overdue_followups", group: "Follow-ups" },
  { key: "followups_due_today", group: "Follow-ups" },
  { key: "upcoming_followups", group: "Follow-ups" },
  { key: "unscheduled", group: "Follow-ups" },
  { key: "appointments_scheduled", group: "Appointments" },
  { key: "appointments_today", group: "Appointments" },
  { key: "offers_made", group: "Deals" },
  { key: "negotiations", group: "Deals" },
  { key: "under_contract", group: "Deals" },
  { key: "closed", group: "Deals" },
  { key: "nurture", group: "Other" },
  { key: "disqualified", group: "Other" },
  { key: "missing_critical", group: "Data quality" },
  { key: "leads_without_recent_activity", group: "Data quality" },
];

const GROUP_ACCENT: Record<string, { bar: string; dot: string }> = {
  Pipeline: { bar: "bg-brand-500", dot: "bg-brand-500" },
  "Follow-ups": { bar: "bg-amber-400", dot: "bg-amber-400" },
  Appointments: { bar: "bg-violet-400", dot: "bg-violet-400" },
  Deals: { bar: "bg-sky-400", dot: "bg-sky-400" },
  Other: { bar: "bg-ink-300", dot: "bg-ink-300" },
  "Data quality": { bar: "bg-rose-400", dot: "bg-rose-400" },
};

const ACTIVITY_DOT: Record<string, string> = {
  call: "bg-sky-400",
  text: "bg-brand-500",
  email: "bg-violet-400",
  note: "bg-amber-400",
  task: "bg-rose-400",
  status_change: "bg-ink-400",
  appointment: "bg-fuchsia-400",
};

function DashboardSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading dashboard">
      <div className="flex items-center gap-3">
        <span className="skeleton h-8 w-1.5 rounded-full" />
        <div className="space-y-2">
          <div className="skeleton h-7 w-44" />
          <div className="skeleton h-3.5 w-64" />
        </div>
      </div>
      {[0, 1, 2].map((g) => (
        <div key={g}>
          <div className="skeleton mb-2.5 h-3 w-24" />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="skeleton h-[76px]" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const { data, error, loading, reload } = useAsync<Dashboard>(() => apiGet<Dashboard>("/api/dashboard/metrics"));

  if (loading) return <DashboardSkeleton />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;

  if (data.empty) {
    return (
      <>
        <PageHeader title="Dashboard" subtitle={`Today is ${data.today} (${data.timezone})`} />
        <EmptyState
          title="No seller leads yet"
          description="Import a historical lead list or run a REsimpli synchronisation to populate the dashboard. Every metric below is computed from live records — nothing here is a demo number."
          action={
            <>
              <Link className="btn-primary" href="/import">
                Open Import Center
              </Link>
              <Link className="btn" href="/sync">
                Sync status
              </Link>
            </>
          }
        />
      </>
    );
  }

  const go = (filter: Record<string, unknown>) => {
    const params = new URLSearchParams();
    Object.entries(filter).forEach(([k, v]) => {
      if (v === undefined || v === null || v === "" || v === false) return;
      if (Array.isArray(v)) v.forEach((x) => params.append(k, String(x)));
      else params.set(k, String(v));
    });
    const qs = params.toString();
    router.push(`/leads${qs ? `?${qs}` : ""}`);
  };

  const groups = Array.from(new Set(TILE_ORDER.map((t) => t.group)));

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={`Generated ${fmtDateTime(data.generated_at)} · ${data.timezone}`}
        actions={
          <>
            <Link className="btn" href="/followups">
              Daily follow-ups
            </Link>
            <Link className="btn" href="/sync">
              Sync status
            </Link>
          </>
        }
      />

      {data.sync.health !== "healthy" && (
        <div
          className={`mb-4 rounded-lg border p-3 text-sm ${
            data.sync.mock_mode
              ? "border-amber-200 bg-amber-50 text-amber-900"
              : data.sync.health === "failed"
                ? "border-red-200 bg-red-50 text-red-800"
                : "border-ink-200 bg-white text-ink-600"
          }`}
        >
          <span className="font-semibold">Sync health: {data.sync.health}.</span>{" "}
          {data.sync.mock_mode
            ? "No REsimpli API key is configured, so the sample/mock dataset is in use. Add RESIMPLI_API_KEY in backend/.env to pull real data."
            : "Data may be stale — open Sync Status before making decisions from these numbers."}{" "}
          <Link className="underline" href="/sync">
            Details
          </Link>
        </div>
      )}

      {data.ai && !data.ai.available && (
        <div className="mb-4 rounded-lg border border-ink-200 bg-white p-3 text-sm text-ink-600">
          <span className="font-semibold">Local AI unavailable.</span> {data.ai.message}
        </div>
      )}

      {groups.map((group) => (
        <section key={group} className="mb-6">
          <h2 className="mb-2.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
            <span className={`h-1.5 w-1.5 rounded-full ${GROUP_ACCENT[group]?.dot ?? "bg-ink-300"}`} />
            {group}
          </h2>
          <div className="grid grid-cols-2 gap-3 stagger sm:grid-cols-3 xl:grid-cols-5">
            {TILE_ORDER.filter((t) => t.group === group).map((tile) => {
              const meta = data.tiles[tile.key];
              if (!meta) return null;
              const highlight =
                (tile.key === "overdue_followups" && meta.count > 0) ||
                (tile.key === "missing_critical" && meta.count > 0);
              return (
                <button
                  key={tile.key}
                  onClick={() => go(meta.filter)}
                  className={`card card-hover relative overflow-hidden p-3.5 text-left ${
                    highlight ? "border-rose-300 bg-rose-50/50" : ""
                  }`}
                >
                  <span
                    className={`absolute inset-x-0 top-0 h-1 ${
                      highlight ? "bg-rose-400" : GROUP_ACCENT[group]?.bar ?? "bg-ink-300"
                    }`}
                  />
                  <div className="mt-1 text-[11px] font-medium uppercase tracking-wide text-ink-500">
                    {meta.label}
                  </div>
                  <div
                    className={`mt-1 text-[26px] font-bold leading-tight tracking-tight ${
                      highlight ? "text-rose-700" : "text-ink-950"
                    }`}
                  >
                    {meta.count.toLocaleString()}
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      ))}

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="card p-4 lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold text-ink-800">Pipeline stages</h2>
          <div className="space-y-1.5">
            {data.stages.map((s) => (
              <button
                key={s.key}
                onClick={() => go(s.filter)}
                className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left transition hover:bg-brand-50"
              >
                <span className="w-44 shrink-0 truncate text-sm text-ink-700">{s.label}</span>
                <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-ink-100">
                  <span
                    className="bar-grow block h-full rounded-full bg-gradient-to-r from-brand-400 to-brand-600"
                    style={{ width: `${data.total_leads ? Math.max(2, (s.count / data.total_leads) * 100) : 0}%` }}
                  />
                </span>
                <span className="w-10 shrink-0 text-right text-sm font-semibold tabular-nums">{s.count}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="card p-4">
          <h2 className="mb-3 text-sm font-semibold text-ink-800">Recent activity</h2>
          {data.recent_activity.length === 0 ? (
            <p className="text-sm text-ink-500">No activity recorded yet.</p>
          ) : (
              <ul className="space-y-2 stagger">
                {data.recent_activity.map((a) => (
                  <li key={a.id} className="border-b border-ink-100 pb-2 last:border-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={`h-2 w-2 shrink-0 rounded-full ring-2 ring-white ${ACTIVITY_DOT[a.activity_type ?? ""] ?? "bg-ink-300"}`}
                      />
                      <Link href={`/leads/${a.lead_id}`} className="text-sm font-medium text-ink-900 hover:text-brand-700">
                        {a.lead_name || "Lead"}
                      </Link>
                    </div>
                    <div className="mt-0.5 pl-4 text-xs text-ink-500">
                      {a.activity_type}
                      {a.outcome ? ` · ${a.outcome}` : ""} · {fmtDateTime(a.occurred_at)} · {a.source}
                    </div>
                    {a.summary && <div className="mt-0.5 pl-4 line-clamp-2 text-xs text-ink-600">{a.summary}</div>}
                  </li>
                ))}
              </ul>
          )}
        </section>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        {(["by_source", "by_manager", "by_state"] as const).map((key) => (
          <section key={key} className="card p-4">
            <h2 className="mb-3 text-sm font-semibold text-ink-800">
              {key === "by_source" ? "By source" : key === "by_manager" ? "By manager" : "By state"}
            </h2>
            {data.breakdowns[key].length === 0 ? (
              <p className="text-sm text-ink-500">No data.</p>
            ) : (
              <ul className="space-y-1">
                {data.breakdowns[key].slice(0, 10).map((row) => (
                  <li key={String(row.value)}>
                    <button
                      onClick={() => go(row.filter)}
                      className="flex w-full items-center justify-between rounded px-1.5 py-1 text-left text-sm transition hover:bg-brand-50"
                    >
                      <span className="truncate text-ink-700">{row.value}</span>
                      <span className="tabular-nums text-ink-900">{row.count}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>
    </>
  );
}
