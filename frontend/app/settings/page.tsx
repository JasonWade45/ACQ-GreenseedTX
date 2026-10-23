"use client";

import { useEffect, useState } from "react";
import { ErrorBox, PageHeader, Spinner } from "@/components/UI";
import { apiGet, apiPatch, fmtDateTime } from "@/lib/api";

interface SettingsResponse {
  settings: Record<string, unknown>;
  defaults: { stage_mapping: Record<string, string>; followup_rules: Record<string, unknown> };
  runtime: Record<string, unknown>;
  pipeline: {
    stages: { key: string; label: string }[];
    contact_outcomes: { key: string; label: string }[];
    completion_outcomes: string[];
  };
}

interface AuditEntry {
  id: string;
  action: string;
  entity_type?: string;
  entity_id?: string;
  detail?: Record<string, unknown>;
  created_at?: string;
}

export default function SettingsPage() {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [rules, setRules] = useState<Record<string, unknown>>({});
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const s = await apiGet<SettingsResponse>("/api/settings");
      setData(s);
      setRules((s.settings.followup_rules as Record<string, unknown>) || s.defaults.followup_rules);
      setMapping((s.settings.stage_mapping as Record<string, string>) || {});
      const a = await apiGet<{ items: AuditEntry[] }>("/api/audit?limit=60");
      setAudit(a.items);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save() {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await apiPut("/api/settings", { followup_rules: rules, stage_mapping: mapping });
      setMessage("Settings saved.");
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function apiPut(path: string, body: unknown) {
    const res = await fetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      throw new Error(b.detail || res.statusText);
    }
    return res.json();
  }

  if (loading) return <Spinner label="Loading settings…" />;
  if (error && !data) return <ErrorBox message={error} onRetry={load} />;
  if (!data) return null;

  const ruleKeys = Object.keys(data.defaults.followup_rules);

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Pipeline mapping, follow-up rules, runtime configuration and audit trail"
        actions={
          <button className="btn-primary" disabled={busy} onClick={save}>
            {busy ? "Saving…" : "Save settings"}
          </button>
        }
      />
      {message && (
        <div className="mb-4 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-900">{message}</div>
      )}
      {error && <ErrorBox message={error} />}

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="card p-4">
          <h2 className="mb-1 text-sm font-semibold text-ink-800">Follow-up rules</h2>
          <p className="mb-3 text-xs text-ink-500">
            These control the daily work queue. Overdue tasks are sorted by lateness and priority; callbacks requested
            by a seller get the highest priority by default.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {ruleKeys.map((key) => (
              <div key={key}>
                <label className="label">{key.replace(/_/g, " ")}</label>
                {typeof rules[key] === "boolean" ? (
                  <input
                    type="checkbox"
                    checked={Boolean(rules[key])}
                    onChange={(e) => setRules((r) => ({ ...r, [key]: e.target.checked }))}
                  />
                ) : Array.isArray(rules[key]) ? (
                  <select
                    multiple
                    className="input min-h-[90px]"
                    value={(rules[key] as string[]) || []}
                    onChange={(e) =>
                      setRules((r) => ({
                        ...r,
                        [key]: Array.from(e.target.selectedOptions).map((o) => o.value),
                      }))
                    }
                  >
                    {data.pipeline.stages.map((s) => (
                      <option key={s.key} value={s.key}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="input"
                    type={typeof rules[key] === "number" ? "number" : "text"}
                    value={String(rules[key] ?? "")}
                    onChange={(e) =>
                      setRules((r) => ({
                        ...r,
                        [key]: typeof rules[key] === "number" ? Number(e.target.value) : e.target.value,
                      }))
                    }
                  />
                )}
                <p className="mt-0.5 text-[11px] text-ink-400">
                  default: {JSON.stringify(data.defaults.followup_rules[key])}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="card p-4">
          <h2 className="mb-1 text-sm font-semibold text-ink-800">Source status → local stage mapping</h2>
          <p className="mb-3 text-xs text-ink-500">
            REsimpli status names are preserved on each lead as <span className="font-medium">source status</span>. This
            table only decides which local pipeline stage a source status maps to.
          </p>
          <div className="space-y-2">
            {[
              { source: "New Lead", stage: "new" },
              { source: "Contact Made", stage: "contacted" },
              { source: "Appointment Set", stage: "appointment_set" },
              { source: "Under Contract", stage: "under_contract" },
              { source: "Dead Leads", stage: "dead" },
            ].map((row) => (
              <div key={row.source} className="grid grid-cols-2 items-center gap-2">
                <div className="text-sm text-ink-700">{row.source}</div>
                <select
                  className="input"
                  value={mapping[row.source] || row.stage}
                  onChange={(e) => setMapping((m) => ({ ...m, [row.source]: e.target.value }))}
                >
                  {data.pipeline.stages.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-ink-500">
            Add more rows by editing the <code>stage_mapping</code> object via the API or by adding statuses in REsimpli
            and re-syncing — unmapped statuses fall back to “New”.
          </p>
        </section>
      </div>

      <section className="card mt-4 p-4">
        <h2 className="mb-2 text-sm font-semibold text-ink-800">Runtime configuration</h2>
        <div className="grid gap-3 text-sm sm:grid-cols-3">
          {Object.entries(data.runtime).map(([key, value]) => (
            <div key={key} className="rounded-lg border border-ink-200 p-2.5">
              <div className="text-[11px] uppercase tracking-wide text-ink-500">{key}</div>
              <div className="mt-0.5 break-all font-medium">{String(value)}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-ink-500">
          Secrets live in <code className="font-mono">backend/.env</code> only — copy from{" "}
          <code className="font-mono">.env.example</code>. The API key is never returned to the frontend.
        </p>
      </section>

      <section className="card mt-4 p-4">
        <h2 className="mb-2 text-sm font-semibold text-ink-800">Audit log</h2>
        <p className="mb-2 text-xs text-ink-500">
          Important local actions: stage changes, follow-up completion, import approvals, sync runs, settings changes.
        </p>
        {audit.length === 0 ? (
          <p className="text-sm text-ink-500">No audit entries yet.</p>
        ) : (
          <div className="max-h-[400px] overflow-y-auto scrollbar-thin">
            <table className="min-w-full">
              <thead className="sticky top-0 border-b border-ink-200 bg-ink-50">
                <tr>
                  <th className="th">When</th>
                  <th className="th">Action</th>
                  <th className="th">Entity</th>
                  <th className="th">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {audit.map((a) => (
                  <tr key={a.id}>
                    <td className="td whitespace-nowrap text-xs">{fmtDateTime(a.created_at)}</td>
                    <td className="td font-mono text-xs">{a.action}</td>
                    <td className="td text-xs">
                      {a.entity_type}
                      {a.entity_id ? ` ${a.entity_id.slice(0, 8)}` : ""}
                    </td>
                    <td className="td max-w-[400px] truncate text-xs text-ink-600">
                      {a.detail ? JSON.stringify(a.detail) : ""}
                    </td>
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
