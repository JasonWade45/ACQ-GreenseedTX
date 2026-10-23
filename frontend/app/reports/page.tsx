"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorBox, PageHeader, Spinner, useAsync } from "@/components/UI";
import { apiGet } from "@/lib/api";

interface Summary {
  generated_at: string;
  totals: {
    leads: number;
    never_contacted: number;
    contacted: number;
    contact_attempt_leads: number;
    stages: Record<string, { label: string; count: number }>;
  };
  conversion: Record<string, unknown>;
  followups: Record<string, unknown>;
  appointments: Record<string, unknown>;
  aging: { stage: string; label: string; count: number; avg_age_days: number | null; median_age_days: number | null; max_age_days?: number }[];
  unavailable_metrics: string[];
}

interface Volume {
  days: number;
  by_original_creation_date: { date: string; count: number }[];
  by_local_created_at: { date: string; count: number }[];
  note: string;
}

interface BySource {
  items: {
    source: string;
    count: number;
    share: number | null;
    closed: number;
    closed_rate: number | null;
    stages: Record<string, number>;
  }[];
  total: number;
}

function pct(value: unknown): string {
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "number") return `${(value * 100).toFixed(1)}%`;
  return String(value);
}

export default function ReportsPage() {
  const summary = useAsync<Summary>(() => apiGet<Summary>("/api/reports/summary"));
  const volume = useAsync<Volume>(() => apiGet<Volume>("/api/reports/lead-volume?days=90"));
  const bySource = useAsync<BySource>(() => apiGet<BySource>("/api/reports/by-source"));
  const [range, setRange] = useState(90);

  if (summary.loading) return <Spinner label="Loading reports…" />;
  if (summary.error) return <ErrorBox message={summary.error} onRetry={summary.reload} />;
  const data = summary.data;
  if (!data) return null;

  const c = data.conversion;
  const maxCount = Math.max(1, ...volume.data?.by_original_creation_date.map((d) => d.count) || [1]);

  return (
    <>
      <PageHeader
        title="Reports & analytics"
        subtitle="All metrics are computed from local records. Denominators are stated explicitly."
        actions={
          <>
            <a className="btn" href="/api/reports/export/csv?kind=leads">
              Leads CSV
            </a>
            <a className="btn" href="/api/reports/export/csv?kind=aging">
              Aging CSV
            </a>
            <a className="btn" href="/api/reports/export/csv?kind=followups">
              Follow-ups CSV
            </a>
            <a className="btn" href="/api/reports/export/csv?kind=activities">
              Activities CSV
            </a>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-4">
        <div className="card p-4">
          <div className="text-xs uppercase tracking-wide text-ink-500">Total leads</div>
          <div className="text-3xl font-bold">{data.totals.leads.toLocaleString()}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs uppercase tracking-wide text-ink-500">Never contacted</div>
          <div className="text-3xl font-bold text-amber-700">{data.totals.never_contacted.toLocaleString()}</div>
          <div className="text-xs text-ink-500">
            {data.totals.leads ? pct(data.totals.never_contacted / data.totals.leads) : "n/a"} of all leads
          </div>
        </div>
        <div className="card p-4">
          <div className="text-xs uppercase tracking-wide text-ink-500">Contacted</div>
          <div className="text-3xl font-bold">{data.totals.contacted.toLocaleString()}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs uppercase tracking-wide text-ink-500">Contact attempt rate</div>
          <div className="text-3xl font-bold">{pct(c.contact_attempt_rate)}</div>
          <div className="text-xs text-ink-500">{String(c.contact_attempt_rate_definition)}</div>
        </div>
      </div>

      <section className="card mt-4 p-4">
        <h2 className="mb-3 text-sm font-semibold text-ink-800">Conversion funnel</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead className="border-b border-ink-200">
              <tr>
                <th className="th">Metric</th>
                <th className="th">Value</th>
                <th className="th">Definition & denominator</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {[
                ["Contact rate", c.contact_rate, c.contact_rate_definition],
                ["Contact attempt rate", c.contact_attempt_rate, c.contact_attempt_rate_definition],
                ["Qualification rate", c.qualification_rate, c.qualification_rate_definition],
                ["Appointment rate", c.appointment_rate, c.appointment_rate_definition],
                ["Offer rate (of qualified)", c.offer_rate_of_qualified, c.offer_rate_definition],
                ["Offer rate (of all leads)", c.offer_rate_of_all, "Same numerator, all-leads denominator"],
                ["Contract rate (of offers)", c.contract_rate_of_offers, "contract_sent + under_contract / offers"],
                ["Closing rate (of contract)", c.closing_rate_of_contract, c.closing_rate_of_all !== null ? "closed / (contract_sent + under_contract)" : ""],
              ].map((row) => (
                <tr key={String(row[0])}>
                  <td className="td font-medium">{String(row[0])}</td>
                  <td className="td tabular-nums">{pct(row[1])}</td>
                  <td className="td text-xs text-ink-600">{String(row[2] || "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 rounded-lg bg-ink-50 p-3 text-xs text-ink-600">
          <span className="font-semibold text-ink-800">Denominators:</span>{" "}
          {JSON.stringify((c.denominators as Record<string, number>) || {})}
        </div>
      </section>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <section className="card p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ink-800">Lead volume</h2>
            <select className="input w-auto" value={range} onChange={(e) => { setRange(Number(e.target.value)); }}>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
              <option value={180}>Last 180 days</option>
            </select>
          </div>
          {volume.loading && <Spinner />}
          {volume.data && (
            <>
              <div className="flex h-40 items-end gap-1">
                {volume.data.by_original_creation_date.slice(-30).map((d) => (
                  <div key={d.date} className="flex-1 rounded-t bg-gradient-to-t from-brand-500 to-brand-400 transition hover:from-brand-600 hover:to-brand-500" style={{ height: `${(d.count / maxCount) * 100}%` }} title={`${d.date}: ${d.count}`} />
                ))}
                {volume.data.by_original_creation_date.length === 0 && (
                  <p className="text-sm text-ink-500">No dated leads in this range.</p>
                )}
              </div>
              <p className="mt-2 text-[11px] text-ink-500">{volume.data.note}</p>
            </>
          )}
        </section>

        <section className="card p-4">
          <h2 className="mb-3 text-sm font-semibold text-ink-800">Lead aging by stage</h2>
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead className="border-b border-ink-200">
                <tr>
                  <th className="th">Stage</th>
                  <th className="th">Leads</th>
                  <th className="th">Avg age (days)</th>
                  <th className="th">Median</th>
                  <th className="th">Max</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {data.aging.map((row) => (
                  <tr key={row.stage}>
                    <td className="td">{row.label}</td>
                    <td className="td tabular-nums">{row.count}</td>
                    <td className="td tabular-nums">{row.avg_age_days ?? "—"}</td>
                    <td className="td tabular-nums">{row.median_age_days ?? "—"}</td>
                    <td className="td tabular-nums">{row.max_age_days ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="card mt-4 p-4">
        <h2 className="mb-3 text-sm font-semibold text-ink-800">Performance by lead source</h2>
        {bySource.loading && <Spinner />}
        {bySource.error && <ErrorBox message={bySource.error} onRetry={bySource.reload} />}
        {bySource.data && bySource.data.items.length === 0 ? (
          <p className="text-sm text-ink-500">No source data yet.</p>
        ) : (
          bySource.data && (
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead className="border-b border-ink-200">
                  <tr>
                    <th className="th">Source</th>
                    <th className="th">Leads</th>
                    <th className="th">Share</th>
                    <th className="th">Closed</th>
                    <th className="th">Close rate</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100">
                  {bySource.data.items.map((row) => (
                    <tr key={row.source}>
                      <td className="td font-medium">
                        <Link className="hover:underline" href={`/leads?source=${encodeURIComponent(row.source)}`}>
                          {row.source}
                        </Link>
                      </td>
                      <td className="td tabular-nums">{row.count}</td>
                      <td className="td tabular-nums">{pct(row.share)}</td>
                      <td className="td tabular-nums">{row.closed}</td>
                      <td className="td tabular-nums">{pct(row.closed_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </section>

      <section className="card mt-4 p-4">
        <h2 className="mb-2 text-sm font-semibold text-ink-800">Metrics that cannot be calculated</h2>
        <ul className="list-disc pl-5 text-sm text-ink-600">
          {data.unavailable_metrics.map((m, i) => (
            <li key={i}>{m}</li>
          ))}
        </ul>
      </section>
    </>
  );
}
