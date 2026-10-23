"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, EmptyState, ErrorBox, PageHeader, Spinner, useAsync } from "@/components/UI";
import { Appointment, apiGet, apiPatch, apiPost, fmtDateTime, stageBadge } from "@/lib/api";

interface AppointmentList {
  items: Appointment[];
  total: number;
  today: string;
}

const STATUS_LABELS: Record<string, string> = {
  scheduled: "Scheduled",
  kept: "Kept",
  not_kept: "Not kept",
  no_answer: "No answer",
  dismissed: "Dismissed",
};

export default function AppointmentsPage() {
  const [filter, setFilter] = useState<"upcoming" | "past" | "all">("upcoming");
  const { data, error, loading, reload } = useAsync<AppointmentList>(
    () => apiGet<AppointmentList>(`/api/appointments?upcoming=${filter === "upcoming" ? "true" : filter === "past" ? "false" : ""}`),
    [filter],
  );

  return (
    <>
      <PageHeader
        title="Appointments"
        subtitle="Seller appointments synced from REsimpli and created locally"
        actions={
          <div className="flex gap-2">
            {(["upcoming", "past", "all"] as const).map((f) => (
              <button
                key={f}
                className={filter === f ? "btn-primary" : "btn"}
                onClick={() => setFilter(f)}
              >
                {f[0].toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        }
      />

      {loading && <Spinner />}
      {error && <ErrorBox message={error} onRetry={reload} />}

      {!loading && !error && data && data.items.length === 0 && (
        <EmptyState
          title="No appointments"
          description="Appointments appear here once they are synced from REsimpli or scheduled on a lead profile."
          action={
            <Link className="btn" href="/leads">
              Browse leads
            </Link>
          }
        />
      )}

      {data && data.items.length > 0 && (
        <div className="card overflow-x-auto scrollbar-thin">
          <table className="min-w-full">
            <thead className="border-b border-ink-200 bg-ink-50">
              <tr>
                <th className="th">When</th>
                <th className="th">Seller</th>
                <th className="th">Property</th>
                <th className="th">Type</th>
                <th className="th">Status</th>
                <th className="th">Notes</th>
                <th className="th">Source</th>
                <th className="th">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {data.items.map((a) => (
                <tr key={a.id} className="hover:bg-ink-50/60">
                  <td className="td whitespace-nowrap">
                    <span className={a.is_today ? "font-semibold text-ink-950" : ""}>{fmtDateTime(a.scheduled_at)}</span>
                    {a.is_today && <Badge className="ml-1 bg-brand-600 text-white">Today</Badge>}
                  </td>
                  <td className="td">
                    {a.lead?.id ? (
                      <Link href={`/leads/${a.lead.id}`} className="font-medium hover:underline">
                        {a.lead.name}
                      </Link>
                    ) : (
                      <span className="text-ink-400">—</span>
                    )}
                    <div className="text-xs text-ink-500">{a.lead?.phone}</div>
                  </td>
                  <td className="td max-w-[200px] truncate">{a.lead?.property_address || "—"}</td>
                  <td className="td text-xs">{a.appointment_type || "—"}</td>
                  <td className="td">
                    <Badge
                      className={
                        a.status === "kept"
                          ? "bg-green-100 text-green-800"
                          : a.status === "scheduled"
                            ? "bg-blue-100 text-blue-800"
                            : "bg-ink-100 text-ink-700"
                      }
                    >
                      {STATUS_LABELS[a.status] || a.status}
                    </Badge>
                  </td>
                  <td className="td max-w-[240px] truncate text-xs text-ink-600">{a.notes || "—"}</td>
                  <td className="td">
                    <Badge
                      className={
                        a.source === "resimpli" ? "bg-blue-100 text-blue-800" : "bg-amber-100 text-amber-800"
                      }
                    >
                      {a.source}
                    </Badge>
                  </td>
                  <td className="td">
                    <div className="flex gap-1.5">
                      <button
                        className="btn px-2 py-1 text-xs"
                        onClick={async () => {
                          await apiPatch(`/api/appointments/${a.id}`, { status: "kept" });
                          reload();
                        }}
                      >
                        Kept
                      </button>
                      <button
                        className="btn px-2 py-1 text-xs"
                        onClick={async () => {
                          await apiPatch(`/api/appointments/${a.id}`, { status: "not_kept" });
                          reload();
                        }}
                      >
                        Not kept
                      </button>
                      <button
                        className="btn px-2 py-1 text-xs"
                        onClick={async () => {
                          await apiPatch(`/api/appointments/${a.id}`, { status: "dismissed" });
                          reload();
                        }}
                      >
                        Dismiss
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
