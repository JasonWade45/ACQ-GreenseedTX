"use client";

import { useState } from "react";
import { Badge, ErrorBox, PageHeader, Spinner, useAsync } from "@/components/UI";
import { SyncStatus, apiGet, apiPost, fmtDateTime } from "@/lib/api";

interface Run {
  id: string;
  started_at?: string;
  finished_at?: string;
  duration_seconds?: number | null;
  result: string;
  trigger: string;
  records_fetched: number;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  failed_count: number;
  error?: string | null;
}

const HEALTH: Record<string, { label: string; className: string }> = {
  healthy: { label: "Healthy", className: "bg-green-100 text-green-800" },
  stale: { label: "Stale", className: "bg-amber-100 text-amber-800" },
  partial: { label: "Partial", className: "bg-amber-100 text-amber-800" },
  failed: { label: "Failed", className: "bg-red-100 text-red-800" },
  never_run: { label: "Never run", className: "bg-ink-100 text-ink-700" },
  running: { label: "Running", className: "bg-blue-100 text-blue-800" },
};

export default function SyncPage() {
  const status = useAsync<SyncStatus>(() => apiGet<SyncStatus>("/api/sync/status"));
  const runs = useAsync<{ items: Run[] }>(() => apiGet<{ items: Run[] }>("/api/sync/runs?limit=25"));
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [interval, setInterval_] = useState(30);
  const [enabled, setEnabled] = useState(false);
  const [apiKey, setApiKey] = useState("");

  async function trigger() {
    setBusy("run");
    setError(null);
    try {
      const result = await apiPost<Run>("/api/sync/run");
      setMessage(
        `Sync ${result.result}: ${result.records_fetched} fetched, ${result.created_count} created, ${result.updated_count} updated, ${result.failed_count} failed.${result.error ? ` Error: ${result.error}` : ""}`,
      );
      status.reload();
      runs.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function toggleScheduler() {
    setBusy("scheduler");
    setError(null);
    try {
      await apiPost("/api/sync/scheduler", { enabled: !enabled, interval_minutes: interval });
      setEnabled(!enabled);
      status.reload();
      setMessage(!enabled ? `Periodic sync enabled every ${interval} minutes.` : "Periodic sync disabled.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function testConnection() {
    setBusy("test");
    setError(null);
    try {
      const result = await apiPost<{ ok: boolean; mock: boolean; error?: string; info?: unknown }>(
        "/api/sync/test-connection",
      );
      if (result.ok) {
        setMessage(result.mock ? "Mock mode active (no API key configured). No network calls were made." : "REsimpli API key accepted.");
      } else {
        setError(result.error || "Connection test failed");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const healthMeta = status.data ? HEALTH[status.data.health] || { label: status.data.health, className: "bg-ink-100 text-ink-700" } : null;

  return (
    <>
      <PageHeader
        title="REsimpli sync status"
        subtitle="Read-only synchronisation. This app never writes to REsimpli except for an explicit, user-approved lead import."
        actions={
          <>
            <button className="btn" disabled={busy === "test"} onClick={testConnection}>
              {busy === "test" ? "Testing…" : "Test connection"}
            </button>
            <button className="btn-primary" disabled={busy === "run"} onClick={trigger}>
              {busy === "run" ? "Syncing…" : "Sync now"}
            </button>
          </>
        }
      />

      {message && (
        <div className="mb-4 rounded-lg border border-ink-200 bg-white p-3 text-sm text-ink-700">{message}</div>
      )}
      {error && <ErrorBox message={error} />}

      {status.loading && <Spinner label="Loading sync status…" />}
      {status.error && <ErrorBox message={status.error} onRetry={status.reload} />}

      {status.data && (
        <>
          <div className="grid gap-4 lg:grid-cols-4">
            <div className="card p-4">
              <div className="text-xs uppercase tracking-wide text-ink-500">Health</div>
              <div className="mt-1">
                <Badge className={healthMeta?.className}>{healthMeta?.label}</Badge>
              </div>
              <div className="mt-2 text-xs text-ink-500">
                {status.data.mock_mode
                  ? "Mock mode — sample data, no network calls"
                  : status.data.api_key_configured
                    ? "API key configured"
                    : "No API key configured"}
              </div>
            </div>
            <div className="card p-4">
              <div className="text-xs uppercase tracking-wide text-ink-500">Leads in database</div>
              <div className="text-3xl font-bold">{status.data.leads_in_database.toLocaleString()}</div>
              <div className="text-xs text-ink-500">{status.data.leads_ever_synced} ever synced</div>
            </div>
            <div className="card p-4">
              <div className="text-xs uppercase tracking-wide text-ink-500">Last success</div>
              <div className="text-sm font-medium">
                {status.data.last_success
                  ? fmtDateTime(String(status.data.last_success.finished_at))
                  : "Never"}
              </div>
              {status.data.last_success && (
                <div className="mt-1 text-xs text-ink-500">
                  {String(status.data.last_success.created_count)} created ·{" "}
                  {String(status.data.last_success.updated_count)} updated
                </div>
              )}
              {!status.data.data_is_live && (
                <div className="mt-1 text-xs font-medium text-amber-700">Showing data that is not freshly synced</div>
              )}
            </div>
            <div className="card p-4">
              <div className="text-xs uppercase tracking-wide text-ink-500">Scheduler</div>
              <div className="text-sm font-medium">{status.data.scheduler.enabled ? "Enabled" : "Disabled"}</div>
              <div className="text-xs text-ink-500">every {status.data.interval_minutes} minutes</div>
              {status.data.scheduler.last_job_at && (
                <div className="mt-1 text-xs text-ink-500">
                  last job {fmtDateTime(status.data.scheduler.last_job_at)} · {status.data.scheduler.last_job_result}
                </div>
              )}
            </div>
          </div>

          {status.data.last_run && (
            <section className="card mt-4 p-4">
              <h2 className="mb-2 text-sm font-semibold text-ink-800">Last run</h2>
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-6">
                {[
                  ["Result", String(status.data.last_run.result)],
                  ["Fetched", String(status.data.last_run.records_fetched)],
                  ["Created", String(status.data.last_run.created_count)],
                  ["Updated", String(status.data.last_run.updated_count)],
                  ["Skipped", String(status.data.last_run.skipped_count)],
                  ["Failed", String(status.data.last_run.failed_count)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <div className="text-xs uppercase tracking-wide text-ink-500">{label}</div>
                    <div className="font-semibold">{value}</div>
                  </div>
                ))}
              </div>
              {status.data.last_run && status.data.last_run.error ? (
                <div className="mt-2 rounded-lg border border-red-200 bg-red-50 p-2.5 text-sm text-red-800">
                  {String(status.data.last_run.error)}
                </div>
              ) : null}
            </section>
          )}

          <section className="card mt-4 p-4">
            <h2 className="mb-2 text-sm font-semibold text-ink-800">Configuration</h2>
            {!status.data.api_key_configured && (
              <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                No <code className="font-mono">RESIMPLI_API_KEY</code> is configured, so the app runs in mock mode with
                sample records. Add the key to <code className="font-mono">backend/.env</code> and restart the backend.
                Get the key in REsimpli under{" "}
                <span className="font-medium">Settings → Webhook - API Token → API Token tab</span> (use{" "}
                <span className="font-medium">Generate Open API Token</span> — not the Zapier token).
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className="label">Sync every N minutes</label>
                <input
                  className="input"
                  type="number"
                  min={5}
                  value={interval}
                  onChange={(e) => setInterval_(Number(e.target.value))}
                />
              </div>
              <div className="flex items-end">
                <button className="btn-primary" disabled={busy === "scheduler"} onClick={toggleScheduler}>
                  {enabled ? "Disable periodic sync" : "Enable periodic sync"}
                </button>
              </div>
              <div>
                <label className="label">Set API key (requires restart)</label>
                <div className="flex gap-2">
                  <input
                    className="input"
                    type="password"
                    placeholder="paste key then edit backend/.env"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                  />
                </div>
                <p className="mt-1 text-[11px] text-ink-500">
                  Keys are never stored by the frontend. Edit <code>backend/.env</code> and restart.
                </p>
              </div>
            </div>
            <p className="mt-3 text-xs text-ink-500">
              Rate limit: {status.data.rate_limit_per_minute} requests/minute (client-side throttling + exponential
              backoff on HTTP 429). Synchronisation is a full reconciliation of the lead list because the documented{" "}
              <code className="font-mono">/lead/list</code> endpoint has no “modified since” filter; per-lead detail and
              activity calls are budgeted to the most relevant leads each run.
            </p>
          </section>
        </>
      )}

      <section className="card mt-4 p-4">
        <h2 className="mb-2 text-sm font-semibold text-ink-800">Run history</h2>
        {runs.loading && <Spinner />}
        {runs.error && <ErrorBox message={runs.error} onRetry={runs.reload} />}
        {runs.data && runs.data.items.length === 0 ? (
          <p className="text-sm text-ink-500">No sync runs yet.</p>
        ) : (
          <div className="overflow-x-auto scrollbar-thin">
            <table className="min-w-full">
              <thead className="border-b border-ink-200 bg-ink-50">
                <tr>
                  <th className="th">Started</th>
                  <th className="th">Result</th>
                  <th className="th">Trigger</th>
                  <th className="th">Fetched</th>
                  <th className="th">Created</th>
                  <th className="th">Updated</th>
                  <th className="th">Failed</th>
                  <th className="th">Duration</th>
                  <th className="th">Error</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {(runs.data?.items || []).map((r) => (
                  <tr key={r.id}>
                    <td className="td whitespace-nowrap">{fmtDateTime(r.started_at)}</td>
                    <td className="td">
                      <Badge
                        className={
                          r.result === "success"
                            ? "bg-green-100 text-green-800"
                            : r.result === "failed"
                              ? "bg-red-100 text-red-800"
                              : "bg-amber-100 text-amber-800"
                        }
                      >
                        {r.result}
                      </Badge>
                    </td>
                    <td className="td">{r.trigger}</td>
                    <td className="td tabular-nums">{r.records_fetched}</td>
                    <td className="td tabular-nums">{r.created_count}</td>
                    <td className="td tabular-nums">{r.updated_count}</td>
                    <td className="td tabular-nums">{r.failed_count}</td>
                    <td className="td tabular-nums">{r.duration_seconds != null ? `${r.duration_seconds}s` : "—"}</td>
                    <td className="td max-w-[260px] truncate text-xs text-red-700">{r.error || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
