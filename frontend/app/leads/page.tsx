"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { Badge, EmptyState, ErrorBox, PageHeader, Spinner, useAsync } from "@/components/UI";
import { Lead, ReferenceData, apiGet, fmtDate, isOverdue, qs, stageBadge } from "@/lib/api";

interface LeadListResponse {
  total: number;
  page: number;
  page_size: number;
  pages: number;
  items: Lead[];
}

function LeadsInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const params = useMemo(() => Object.fromEntries(searchParams.entries()), [searchParams]);
  const [search, setSearch] = useState(params.q || "");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data, error, loading, reload } = useAsync<LeadListResponse>(
    () => apiGet<LeadListResponse>(`/api/leads${qs({ page_size: 25, ...params })}`),
    [searchParams.toString()],
  );
  const ref = useAsync<ReferenceData>(() => apiGet<ReferenceData>("/api/leads/meta/reference"));

  const setParam = (key: string, value?: string) => {
    const next = new URLSearchParams(searchParams.toString());
    if (!value) next.delete(key);
    else next.set(key, value);
    if (key !== "page") next.delete("page");
    router.push(`${pathname}?${next.toString()}`);
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const copy = new Set(prev);
      if (copy.has(id)) copy.delete(id);
      else copy.add(id);
      return copy;
    });
  };

  const exportUrl = `/api/leads/export${qs(params)}`;

  return (
    <>
      <PageHeader
        title="Seller leads"
        subtitle={data ? `${data.total.toLocaleString()} leads match the current filters` : "Search, filter and open lead profiles"}
        actions={
          <>
            {selected.size > 0 && (
              <span className="text-sm text-ink-500">{selected.size} selected</span>
            )}
            <Link className="btn" href="/import">
              Upload list
            </Link>
            <a className="btn" href={exportUrl}>
              Export CSV
            </a>
            <Link className="btn-primary" href="/followups">
              Daily queue
            </Link>
          </>
        }
      />

      <div className="card mb-4 p-3">
        <div className="grid gap-3 md:grid-cols-6">
          <div className="md:col-span-2">
            <label className="label">Search</label>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                setParam("q", search);
              }}
            >
              <input
                className="input"
                placeholder="Name, phone, email, address or REsimpli id"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </form>
          </div>
          <div>
            <label className="label">Stage</label>
            <select className="input" value={params.stage || ""} onChange={(e) => setParam("stage", e.target.value)}>
              <option value="">All stages</option>
              {ref.data?.stages.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Follow-up</label>
            <select
              className="input"
              value={params.followup_state || ""}
              onChange={(e) => setParam("followup_state", e.target.value)}
            >
              <option value="">Any</option>
              <option value="overdue">Overdue</option>
              <option value="due_today">Due today</option>
              <option value="upcoming">Upcoming</option>
              <option value="open">Has follow-up</option>
              <option value="unscheduled">Unscheduled</option>
            </select>
          </div>
          <div>
            <label className="label">Source</label>
            <select className="input" value={params.source || ""} onChange={(e) => setParam("source", e.target.value)}>
              <option value="">All sources</option>
              {ref.data?.sources.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Manager</label>
            <select className="input" value={params.manager || ""} onChange={(e) => setParam("manager", e.target.value)}>
              <option value="">Anyone</option>
              {ref.data?.managers.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={params.never_contacted === "true"}
              onChange={(e) => setParam("never_contacted", e.target.checked ? "true" : "")}
            />
            Never contacted
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={params.do_not_contact === "true"}
              onChange={(e) => setParam("do_not_contact", e.target.checked ? "true" : "")}
            />
            Do Not Contact
          </label>
          <select className="input w-auto" value={params.missing || ""} onChange={(e) => setParam("missing", e.target.value)}>
            <option value="">Any data quality</option>
            <option value="critical">Missing critical info</option>
            <option value="none">Complete records</option>
          </select>
          <select className="input w-auto" value={params.sort || "updated"} onChange={(e) => setParam("sort", e.target.value)}>
            <option value="updated">Sort: last updated</option>
            <option value="created">Sort: created</option>
            <option value="name">Sort: name</option>
            <option value="followup">Sort: next follow-up</option>
            <option value="last_contact">Sort: last contact</option>
          </select>
          {(params.q || params.stage || params.followup_state || params.source || params.manager || params.never_contacted || params.do_not_contact || params.missing) && (
            <button className="btn" onClick={() => router.push(pathname)}>
              Clear filters
            </button>
          )}
        </div>
      </div>

      {loading && <Spinner label="Loading leads…" />}
      {error && <ErrorBox message={error} onRetry={reload} />}

      {!loading && !error && data && data.items.length === 0 && (
        <EmptyState
          title="No leads match these filters"
          description="Adjust the filters, or import a list / run a sync to bring seller leads in."
          action={
            <>
              <Link className="btn" href="/import">
                Import Center
              </Link>
              <button className="btn" onClick={reload}>
                Refresh
              </button>
            </>
          }
        />
      )}

      {data && data.items.length > 0 && (
        <div className="card overflow-x-auto scrollbar-thin">
          <table className="min-w-full">
            <thead className="border-b border-ink-200 bg-ink-50">
              <tr>
                <th className="th w-8" />
                <th className="th">Seller</th>
                <th className="th">Property</th>
                <th className="th">Stage</th>
                <th className="th">Contact</th>
                <th className="th">Next follow-up</th>
                <th className="th">Source</th>
                <th className="th">Flags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {data.items.map((lead) => (
                <tr key={lead.id} className="hover:bg-ink-50/60">
                  <td className="td">
                    <input type="checkbox" checked={selected.has(lead.id)} onChange={() => toggleSelect(lead.id)} />
                  </td>
                  <td className="td">
                    <Link href={`/leads/${lead.id}`} className="font-medium text-ink-900 hover:underline">
                      {lead.full_name}
                    </Link>
                    <div className="text-xs text-ink-500">
                      {lead.primary_phone || "no phone"}
                      {lead.email ? ` · ${lead.email}` : ""}
                    </div>
                  </td>
                  <td className="td max-w-[220px]">
                    <div className="truncate">{lead.property?.formatted_address || <span className="text-ink-400">—</span>}</div>
                    {lead.property?.state && <div className="text-xs text-ink-500">{lead.property.state}</div>}
                  </td>
                  <td className="td">
                    <span className={`badge ${stageBadge(lead.pipeline_stage)}`}>{lead.pipeline_stage_label}</span>
                    {lead.source_status && lead.source_status !== lead.pipeline_stage_label && (
                      <div className="mt-1 text-[11px] text-ink-400">CRM: {lead.source_status}</div>
                    )}
                  </td>
                  <td className="td text-xs text-ink-600">
                    {lead.contact_status.replace(/_/g, " ")}
                    <div>{lead.last_contact_at ? fmtDate(lead.last_contact_at) : "never"}</div>
                  </td>
                  <td className="td text-sm">
                    {lead.next_followup_at ? (
                      <span className={isOverdue(lead.next_followup_at) ? "font-semibold text-red-700" : ""}>
                        {fmtDate(lead.next_followup_at)}
                      </span>
                    ) : (
                      <span className="text-ink-400">—</span>
                    )}
                  </td>
                  <td className="td text-xs text-ink-600">{lead.lead_source || "—"}</td>
                  <td className="td">
                    <div className="flex flex-wrap gap-1">
                      {lead.do_not_contact && <Badge className="bg-red-100 text-red-800">DNC</Badge>}
                      {lead.has_critical_missing && <Badge className="bg-amber-100 text-amber-800">Missing info</Badge>}
                      {lead.is_hot_lead && <Badge className="bg-orange-100 text-orange-800">Hot</Badge>}
                      {lead.external_id && <Badge className="bg-ink-100 text-ink-600">CRM</Badge>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-between border-t border-ink-200 px-3 py-2 text-sm">
            <span className="text-ink-500">
              Page {data.page} of {data.pages} · {data.total} total
            </span>
            <div className="flex gap-2">
              <button
                className="btn"
                disabled={data.page <= 1}
                onClick={() => setParam("page", String(data.page - 1))}
              >
                Previous
              </button>
              <button
                className="btn"
                disabled={data.page >= data.pages}
                onClick={() => setParam("page", String(data.page + 1))}
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default function LeadsPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <LeadsInner />
    </Suspense>
  );
}
