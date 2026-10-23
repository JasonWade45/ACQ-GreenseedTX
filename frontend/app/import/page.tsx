"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge, ErrorBox, PageHeader, Spinner } from "@/components/UI";
import {
  AiMapResult,
  CommitResult,
  ExternalConfig,
  ImportBatch,
  ImportInspection,
  ImportPreview,
  apiGet,
  apiPost,
  apiUpload,
  fmtDateTime,
} from "@/lib/api";

const STATUS_LABELS: Record<string, { label: string; className: string }> = {
  new: { label: "New", className: "bg-green-100 text-green-800" },
  likely_duplicate: { label: "Likely duplicate", className: "bg-amber-100 text-amber-800" },
  exact_duplicate: { label: "Duplicate", className: "bg-amber-100 text-amber-800" },
  same_seller_diff_property: { label: "Same seller, new property", className: "bg-blue-100 text-blue-800" },
  same_property_diff_seller: { label: "Same property, new seller", className: "bg-blue-100 text-blue-800" },
  existing_resimpli: { label: "Existing CRM record", className: "bg-ink-100 text-ink-700" },
  rejected: { label: "Rejected", className: "bg-red-100 text-red-800" },
  imported: { label: "Imported", className: "bg-green-100 text-green-800" },
  updated: { label: "Updated", className: "bg-blue-100 text-blue-800" },
  failed: { label: "Failed", className: "bg-red-100 text-red-800" },
  skipped: { label: "Skipped", className: "bg-ink-100 text-ink-600" },
};

const EXT_ID_KEYS = ["pipelineId", "mainStatusId", "marketId", "marketingCampignId"] as const;

function badge(status: string) {
  return STATUS_LABELS[status] || { label: status, className: "bg-ink-100 text-ink-700" };
}

export default function ImportPage() {
  const [inspection, setInspection] = useState<ImportInspection | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [sheet, setSheet] = useState<string>("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [batches, setBatches] = useState<ImportBatch[]>([]);
  const [templates, setTemplates] = useState<{ id: string; name: string }[]>([]);
  const [templateName, setTemplateName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<CommitResult | null>(null);
  const [skipDuplicates, setSkipDuplicates] = useState(true);
  const [updateMatched, setUpdateMatched] = useState(true);
  const [aiMap, setAiMap] = useState<AiMapResult | null>(null);
  const [extConfig, setExtConfig] = useState<ExternalConfig | null>(null);
  const [extEnabled, setExtEnabled] = useState(false);
  const [extIds, setExtIds] = useState<Record<string, string>>({});

  useEffect(() => {
    apiGet<ExternalConfig>("/api/imports/external-config")
      .then((config) => {
        setExtConfig(config);
        setExtIds(config.ids);
      })
      .catch(() => undefined);
  }, []);

  async function refreshBatches() {
    const data = await apiGet<{ items: ImportBatch[] }>("/api/imports");
    setBatches(data.items);
    const t = await apiGet<{ items: { id: string; name: string }[] }>("/api/imports/templates/list");
    setTemplates(t.items);
  }

  async function onUpload(file: File) {
    setBusy("upload");
    setError(null);
    setReport(null);
    setPreview(null);
    setAiMap(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const data = await apiUpload<ImportInspection>("/api/imports/upload", fd);
      setInspection(data);
      setMapping(data.auto_mapping);
      setSheet(data.active_sheet || "");
      if (data.unmapped_headers.length > 0) {
        // Alias rules ran during upload — ask the AI model to fill what is left
        // (it validates against the real headers and falls back to rules).
        setBusy("aimap");
        try {
          const mapped = await apiPost<AiMapResult>("/api/imports/ai-map", {
            file: data.stored_path,
            sheet_name: data.active_sheet || null,
            mapping: { ...data.auto_mapping },
          });
          setMapping(mapped.mapping);
          setAiMap(mapped);
        } catch {
          // Keep the rule-based mapping — never block the import on the AI pass.
        }
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function runAiMap() {
    if (!inspection) return;
    setBusy("aimap");
    setError(null);
    try {
      const data = await apiPost<AiMapResult>("/api/imports/ai-map", {
        file: inspection.stored_path,
        sheet_name: sheet || null,
        mapping: { ...mapping },
      });
      setMapping(data.mapping);
      setAiMap(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function runPreview() {
    if (!inspection) return;
    setBusy("preview");
    setError(null);
    setReport(null);
    try {
      const data = await apiPost<ImportPreview>(
        `/api/imports/preview?file=${encodeURIComponent(inspection.stored_path)}${sheet ? `&sheet_name=${encodeURIComponent(sheet)}` : ""}`,
        { mapping },
      );
      setPreview(data);
      refreshBatches();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function saveExtConfig() {
    try {
      const config = await apiPost<ExternalConfig>("/api/imports/external-config", extIds);
      setExtConfig(config);
      setExtIds(config.ids);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function commit() {
    if (!preview) return;
    const crmLine = extEnabled
      ? "They will ALSO be created inside REsimpli (CRM) through /lead/add. This writes to your REsimpli account — it never messages sellers."
      : "This does NOT write to REsimpli — the leads stay local only.";
    if (
      !window.confirm(
        `Import ${preview.counts.new || 0} new seller lead(s)?\n\n${crmLine}\n\n${
          !skipDuplicates
            ? "Duplicate candidates will be imported too."
            : updateMatched
              ? "Duplicate candidates keep their existing data — empty fields (name, phone, prices…) get filled in from this file."
              : "Duplicate candidates will be skipped."
        }`,
      )
    ) {
      return;
    }
    setBusy("commit");
    setError(null);
    setReport(null);
    try {
      const data = await apiPost<CommitResult>(`/api/imports/${preview.batch.id}/commit`, {
        skip_duplicates: skipDuplicates,
        update_matched: updateMatched,
        external: { enabled: extEnabled },
      });
      setReport(data);
      setPreview(null);
      setInspection(null);
      setAiMap(null);
      refreshBatches();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function saveTemplate() {
    if (!templateName || !inspection) return;
    try {
      await apiPost("/api/imports/templates", { name: templateName, mapping });
      setTemplateName("");
      refreshBatches();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function loadTemplate(id: string) {
    const all = await apiGet<{ items: { id: string; name: string; columns: Record<string, string> }[] }>(
      "/api/imports/templates/list",
    );
    const found = all.items.find((t) => t.id === id);
    if (found) setMapping(found.columns);
  }

  const engineBadge =
    aiMap === null
      ? null
      : aiMap.engine === "groq"
        ? { label: "AI mapped · Groq", className: "bg-emerald-100 text-emerald-800" }
        : aiMap.engine === "ollama"
          ? { label: "AI mapped · Ollama", className: "bg-emerald-100 text-emerald-800" }
          : { label: "Rule-based map", className: "bg-ink-100 text-ink-700" };

  return (
    <>
      <PageHeader
        title="Import Center"
        subtitle="Bring historical seller leads in from CSV or Excel. AI column mapping, validation, duplicate review, missing-data report and optional creation in REsimpli."
      />

      {error && <ErrorBox message={error} />}

      {report && (
        <div className="mb-4 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-900">
          <div className="font-semibold">Import report</div>
          <ul className="mt-1 list-disc pl-5">
            <li>{report.imported} lead(s) created in the local database</li>
            {report.updated > 0 && (
              <li>{report.updated} existing lead(s) updated — empty fields filled from this file</li>
            )}
            <li>{report.skipped} row(s) skipped (duplicates / rejected)</li>
            {report.failed > 0 && <li className="text-red-700">{report.failed} row(s) failed — see errors below</li>}
            {report.external.enabled && (
              <li>
                REsimpli (CRM): {report.external.pushed} created via /lead/add
                {report.external.skipped_no_phone > 0 && (
                  <span className="text-ink-600">
                    , {report.external.skipped_no_phone} kept local only (no phone — REsimpli requires one)
                  </span>
                )}
                {report.external.skipped_existing_crm > 0 && (
                  <span className="text-ink-600">
                    , {report.external.skipped_existing_crm} person(s) already in REsimpli (not duplicated)
                  </span>
                )}
                {report.external.failed > 0 && (
                  <span className="text-amber-800">, {report.external.failed} push failed (kept locally)</span>
                )}
              </li>
            )}
          </ul>
          {report.external.enabled && report.external.errors.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-xs text-amber-900">
              {report.external.errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          )}
          {report.errors.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-xs text-red-700">
              {report.errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          )}
          {report.external.enabled && report.external.pushed > 0 && (
            <p className="mt-1.5 text-xs text-ink-600">
              <Link className="underline" href="/sync">
                Run a sync →
              </Link>{" "}
              to pull the CRM records for the new REsimpli leads.
            </p>
          )}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <section className="card p-4 xl:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-ink-800">1 · Upload a file</h2>
          <p className="mb-3 text-xs text-ink-500">
            Accepted: .csv, .xlsx (multiple sheets supported). Files are stored locally in the backend upload folder and
            are never sent anywhere.
          </p>
          <input
            type="file"
            accept=".csv,.xlsx,.xlsm"
            className="block w-full text-sm"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onUpload(file);
            }}
          />
          {busy === "upload" && (
            <div className="mt-3">
              <Spinner label="Reading file…" />
            </div>
          )}

          {inspection && (
            <div className="mt-4 space-y-3">
              <div className="rounded-lg bg-ink-50 p-3 text-sm">
                <div className="font-medium">{inspection.filename}</div>
                <div className="text-xs text-ink-500">
                  {inspection.row_count.toLocaleString()} data rows · checksum {inspection.checksum?.slice(0, 12)}…
                </div>
                {inspection.sheets.length > 1 && (
                  <div className="mt-2 flex items-center gap-2">
                    <label className="text-xs font-semibold">Sheet</label>
                    <select
                      className="input w-auto"
                      value={sheet}
                      onChange={(e) => setSheet(e.target.value)}
                    >
                      {inspection.sheets.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold text-ink-800">2 · Column mapping</h3>
                <button className="btn" disabled={busy === "aimap"} onClick={runAiMap}>
                  {busy === "aimap" ? "AI mapping…" : "AI auto-map"}
                </button>
                {engineBadge && <Badge className={engineBadge.className}>{engineBadge.label}</Badge>}
                {templates.length > 0 && (
                  <select className="input w-auto" value="" onChange={(e) => loadTemplate(e.target.value)}>
                    <option value="">Load saved template…</option>
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                )}
                <input
                  className="input w-48"
                  placeholder="Template name"
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                />
                <button className="btn" onClick={saveTemplate}>
                  Save template
                </button>
              </div>

              {aiMap && (
                <div
                  className={`rounded-lg border p-2.5 text-xs ${
                    aiMap.unmapped_headers.length > 0 || aiMap.error
                      ? "border-amber-200 bg-amber-50 text-amber-900"
                      : "border-emerald-200 bg-emerald-50 text-emerald-900"
                  }`}
                >
                  {aiMap.unmapped_headers.length === 0 && !aiMap.error
                    ? `All headers mapped (${aiMap.mapped_fields} fields).`
                    : `Mapped ${aiMap.mapped_fields} fields.`}
                  {aiMap.unmapped_headers.length > 0 && (
                    <> Unmapped headers: {aiMap.unmapped_headers.join(", ")}.</>
                  )}
                  {aiMap.error && <> AI note: {aiMap.error}.</>}
                </div>
              )}

              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {inspection.field_catalogue.map((field) => (
                  <div key={field.key}>
                    <label className="label">{field.label}</label>
                    <select
                      className="input"
                      value={mapping[field.key] || ""}
                      onChange={(e) => setMapping((m) => ({ ...m, [field.key]: e.target.value || null }))}
                    >
                      <option value="">— not mapped —</option>
                      {inspection.headers.map((h) => (
                        <option key={h} value={h}>
                          {h}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>

              <div className="flex gap-2">
                <button className="btn-primary" disabled={busy === "preview"} onClick={runPreview}>
                  {busy === "preview" ? "Validating…" : "Preview & validate"}
                </button>
                <button
                  className="btn"
                  onClick={() => {
                    setInspection(null);
                    setPreview(null);
                    setAiMap(null);
                  }}
                >
                  Reset
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="card p-4">
          <h2 className="mb-2 text-sm font-semibold text-ink-800">Import history</h2>
          <button className="btn mb-2" onClick={refreshBatches}>
            Refresh
          </button>
          {batches.length === 0 ? (
            <p className="text-sm text-ink-500">No imports yet.</p>
          ) : (
            <ul className="space-y-2">
              {batches.map((b) => (
                <li key={b.id} className="rounded-lg border border-ink-200 p-2.5 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{b.filename}</span>
                    <Badge
                      className={
                        b.status === "committed"
                          ? "bg-green-100 text-green-800"
                          : b.status === "partially_committed"
                            ? "bg-amber-100 text-amber-800"
                            : "bg-ink-100 text-ink-700"
                      }
                    >
                      {b.status}
                    </Badge>
                  </div>
                  <div className="mt-0.5 text-xs text-ink-500">
                    {b.imported_count} imported
                    {b.updated_count ? ` · ${b.updated_count} updated` : ""} · {b.duplicate_count} duplicates ·{" "}
                    {b.rejected_count} rejected · {b.failed_count} failed
                  </div>
                  <div className="mt-0.5 text-[11px] text-ink-400">{fmtDateTime(b.created_at)}</div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    <a className="btn px-2 py-1 text-xs" href={`/api/imports/${b.id}/rejected.csv`}>
                      Rejected CSV
                    </a>
                    <a className="btn px-2 py-1 text-xs" href={`/api/imports/${b.id}/resimpli-template.csv`}>
                      REsimpli CSV
                    </a>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {preview && (
        <section className="card mt-4 p-4">
          <h2 className="mb-1 text-sm font-semibold text-ink-800">3 · Review before importing</h2>
          {preview.already_imported_file && (
            <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-sm text-amber-900">
              This exact file (checksum match) was already imported. Duplicate detection will skip matching records.
            </div>
          )}
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
            {Object.entries(preview.counts).map(([key, count]) => {
              const meta = badge(key);
              return (
                <div key={key} className="rounded-lg border border-ink-200 p-2">
                  <div className="text-[11px] uppercase tracking-wide text-ink-500">{meta.label}</div>
                  <div className="text-xl font-bold">{count}</div>
                </div>
              );
            })}
          </div>

          {preview.missing && (
            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {Object.entries(preview.missing).map(([key, count]) => (
                <div key={key} className="rounded-lg border border-amber-200 bg-amber-50 p-2">
                  <div className="text-[11px] uppercase tracking-wide text-amber-700">Missing {key}</div>
                  <div className="text-xl font-bold text-amber-900">{count}</div>
                </div>
              ))}
            </div>
          )}

          <div className="overflow-x-auto scrollbar-thin">
            <table className="min-w-full">
              <thead className="border-b border-ink-200 bg-ink-50">
                <tr>
                  <th className="th">Row</th>
                  <th className="th">Status</th>
                  <th className="th">Seller</th>
                  <th className="th">Phone</th>
                  <th className="th">Email</th>
                  <th className="th">Property</th>
                  <th className="th">Reason / warnings</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {preview.sample.map((row) => {
                  const meta = badge(row.status);
                  return (
                    <tr key={row.row_number}>
                      <td className="td tabular-nums">{row.row_number}</td>
                      <td className="td">
                        <Badge className={meta.className}>{meta.label}</Badge>
                      </td>
                      <td className="td">{row.name || "—"}</td>
                      <td className="td">{row.phone || "—"}</td>
                      <td className="td">{row.email || "—"}</td>
                      <td className="td">{row.address || "—"}</td>
                      <td className="td max-w-[320px] text-xs text-ink-600">
                        {row.reason}
                        {row.warnings.length > 0 && (
                          <ul className="mt-0.5 list-disc pl-3 text-amber-800">
                            {row.warnings.map((w, i) => (
                              <li key={i}>{w}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-ink-500">
            Showing the first {preview.sample.length} rows. Full per-row results are stored in the batch record.
          </p>

          <div className="mt-3 rounded-lg border border-ink-200 bg-ink-50 p-3 text-xs">
            <label className="flex items-center gap-2 font-semibold text-ink-800">
              <input
                type="checkbox"
                checked={extEnabled}
                disabled={!extConfig?.available}
                onChange={(e) => setExtEnabled(e.target.checked)}
              />
              Also create these leads in REsimpli (CRM) — via the documented <code className="font-mono">/lead/add</code>
            </label>
            <p className="mt-1 text-ink-600">
              Writes to your REsimpli account only. This application still never sends SMS, email or calls to sellers.
              Rows without a valid 10-digit phone stay local (REsimpli requires one).
            </p>
            {extConfig && (
              <details className="mt-2">
                <summary className="cursor-pointer font-medium text-ink-700">
                  Account IDs used ({extConfig.source === "known" ? "built-in defaults" : extConfig.source === "settings" ? "saved settings" : extConfig.source === "mixed" ? "settings + defaults" : "incomplete"})
                </summary>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {EXT_ID_KEYS.map((key) => (
                    <div key={key}>
                      <label className="label">{key}</label>
                      <input
                        className="input font-mono text-xs"
                        value={extIds[key] || ""}
                        onChange={(e) => setExtIds((ids) => ({ ...ids, [key]: e.target.value }))}
                      />
                    </div>
                  ))}
                </div>
                <button className="btn mt-2" onClick={saveExtConfig}>
                  Save IDs
                </button>
              </details>
            )}
            {extConfig && !extConfig.available && (
              <p className="mt-1 text-amber-800">
                External creation is unavailable: account IDs are incomplete. Save all four IDs above.
              </p>
            )}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button className="btn-primary" disabled={busy === "commit"} onClick={commit}>
              {busy === "commit"
                ? "Importing…"
                : `Import ${preview.counts.new || 0} new leads${extEnabled ? " locally + in REsimpli" : " locally"}`}
            </button>
            <label className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={skipDuplicates}
                onChange={(e) => setSkipDuplicates(e.target.checked)}
              />
              Skip all duplicate candidates (recommended)
            </label>
            <label className="flex items-center gap-1.5 text-sm" title="Never overwrites existing values">
              <input
                type="checkbox"
                checked={updateMatched}
                disabled={!skipDuplicates}
                onChange={(e) => setUpdateMatched(e.target.checked)}
              />
              Fill missing fields on matching leads (recommended)
            </label>
            <a className="btn" href={`/api/imports/${preview.batch.id}/rejected.csv`}>
              Download rejected rows
            </a>
            <Link className="btn" href={`/api/imports/${preview.batch.id}/resimpli-template.csv`}>
              Download REsimpli CSV
            </Link>
          </div>
        </section>
      )}
    </>
  );
}
