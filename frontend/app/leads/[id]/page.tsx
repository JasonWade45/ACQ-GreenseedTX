"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, CopyButton, ErrorBox, PageHeader, Spinner, useAsync } from "@/components/UI";
import {
  AiStatus,
  CallPlan,
  CompsBrief,
  Draft,
  Insight,
  LeadDetail,
  ReferenceData,
  apiGet,
  apiPatch,
  apiPost,
  fmtDate,
  fmtDateTime,
  isOverdue,
  stageBadge,
} from "@/lib/api";

const OUTCOME_OPTIONS = [
  { value: "connected", label: "Connected" },
  { value: "no_answer", label: "No answer" },
  { value: "left_voicemail", label: "Left voicemail" },
  { value: "callback_requested", label: "Callback requested" },
  { value: "seller_not_interested", label: "Seller not interested" },
  { value: "appointment_scheduled", label: "Appointment scheduled" },
  { value: "wrong_number", label: "Wrong number" },
  { value: "do_not_contact", label: "Do not contact" },
  { value: "other", label: "Other" },
];

const COMP_PORTAL_LABELS: Record<string, string> = {
  zillow: "Zillow",
  redfin: "Redfin",
  realtor: "Realtor.com",
};

function composeCallScript(plan: CallPlan): string {
  const lines: string[] = [plan.opener || "", "", "— Talking points —"];
  plan.talking_points.forEach((p) => lines.push(`[${p.used ? "x" : " "}] ${p.text}`));
  lines.push("", "— Questions —");
  plan.questions.forEach((q) => lines.push(`[${q.asked ? "x" : " "}]${q.required ? " *" : ""} ${q.text}`));
  if (plan.do_not_say.length > 0) {
    lines.push("", "— Do not say —");
    plan.do_not_say.forEach((d) => lines.push(`- ${d}`));
  }
  return lines.join("\n");
}

export default function LeadDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const leadId = params.id;

  const { data, error, loading, reload } = useAsync<LeadDetail>(
    () => apiGet<LeadDetail>(`/api/leads/${leadId}`),
    [leadId],
  );
  const ref = useAsync<ReferenceData>(() => apiGet<ReferenceData>("/api/leads/meta/reference"));
  const ai = useAsync<AiStatus>(() => apiGet<AiStatus>("/api/ai/status"));
  const comps = useAsync<CompsBrief>(() => apiGet<CompsBrief>(`/api/leads/${leadId}/comps`), [leadId]);

  const [insight, setInsight] = useState<Insight | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [plan, setPlan] = useState<CallPlan | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState("connected");
  const [completeOpen, setCompleteOpen] = useState(false);
  const [nextAt, setNextAt] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setPlan(data?.call_plan ?? null);
  }, [data]);

  if (loading) return <Spinner label="Loading lead…" />;
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return null;

  const openFollowups = data.followups.filter((f) => f.status === "open");

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setMessage(null);
    try {
      await fn();
      setMessage(null);
      reload();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  function toggleQuestion(index: number) {
    if (!plan) return;
    const questions = plan.questions.map((q, i) => (i === index ? { ...q, asked: !q.asked } : q));
    setPlan({ ...plan, questions });
    apiPatch<CallPlan>(`/api/ai/call-plan/${leadId}`, { questions }).catch((e) => setMessage((e as Error).message));
  }

  function togglePoint(index: number) {
    if (!plan) return;
    const talking_points = plan.talking_points.map((p, i) => (i === index ? { ...p, used: !p.used } : p));
    setPlan({ ...plan, talking_points });
    apiPatch<CallPlan>(`/api/ai/call-plan/${leadId}`, { talking_points }).catch((e) =>
      setMessage((e as Error).message),
    );
  }

  return (
    <>
      <PageHeader
        title={data.full_name}
        subtitle={`${data.pipeline_stage_label}${data.source_status ? ` · CRM status: ${data.source_status}` : ""} · origin: ${data.origin}`}
        actions={
          <>
            <Link className="btn" href="/leads">
              Back to leads
            </Link>
            <Link className="btn" href={`/followups?lead=${data.id}`}>
              Follow-ups
            </Link>
          </>
        }
      />

      {message && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{message}</div>
      )}
      {data.do_not_contact && (
        <div className="mb-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          <span className="font-semibold">Do Not Contact.</span> Marketing drafts are blocked and this lead is excluded
          from ordinary outreach queues. The restriction came from the source record and is preserved.
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        {/* Contact + property */}
        <section className="card p-4">
          <h2 className="mb-3 text-sm font-semibold text-ink-800">Seller</h2>
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-ink-500">Phone</dt>
              <dd className="text-right font-medium">{data.primary_phone || "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-500">Email</dt>
              <dd className="break-all text-right font-medium">{data.email || "—"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-500">Contact status</dt>
              <dd className="text-right">{data.contact_status.replace(/_/g, " ")}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-500">Last contact</dt>
              <dd>{fmtDateTime(data.last_contact_at)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-500">Created (source)</dt>
              <dd>{fmtDate(data.original_creation_date)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-500">Local created</dt>
              <dd>{fmtDateTime(data.created_at)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-500">Last synced</dt>
              <dd>{fmtDateTime(data.last_synced_at)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-500">REsimpli id</dt>
              <dd className="break-all text-right font-mono text-xs">{data.external_id || "—"}</dd>
            </div>
            {data.resimpli_url && (
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">CRM link</dt>
                <a className="text-blue-700 underline" href={data.resimpli_url}>
                  Open in REsimpli
                </a>
              </div>
            )}
          </dl>
          <div className="mt-3 flex flex-wrap gap-1">
            {(data.tags || []).map((t) => (
              <Badge key={t} className="bg-ink-100 text-ink-700">
                {t}
              </Badge>
            ))}
            {data.is_hot_lead && <Badge className="bg-orange-100 text-orange-800">Hot lead</Badge>}
          </div>

          {data.missing_fields && data.missing_fields.length > 0 && (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-amber-800">Missing information</div>
              <ul className="mt-1.5 space-y-1 text-sm text-amber-900">
                {data.missing_fields.map((m) => (
                  <li key={m.field}>
                    <span className="font-medium">{m.label}</span>
                    <span className="text-amber-700"> ({m.severity})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        {/* Property */}
        <section className="card p-4">
          <h2 className="mb-3 text-sm font-semibold text-ink-800">Property</h2>
          {data.property ? (
            <dl className="space-y-2 text-sm">
              <div>
                <dt className="text-ink-500">Address</dt>
                <dd className="font-medium">{data.property.formatted_address || data.property.address_line1 || "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Type</dt>
                <dd>{data.property.property_type || "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Beds / baths</dt>
                <dd>
                  {data.property.bedrooms ?? "—"} / {data.property.bathrooms ?? "—"}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Sq ft</dt>
                <dd>{data.property.square_footage ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Year built</dt>
                <dd>{data.property.year_built ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">County</dt>
                <dd>{data.property.county || "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Lot</dt>
                <dd>{data.property.lot_acres ? `${data.property.lot_acres} acres` : "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Asking price</dt>
                <dd>{data.property.asking_price ? `$${data.property.asking_price.toLocaleString()}` : "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Est. value</dt>
                <dd>{data.property.estimated_value ? `$${data.property.estimated_value.toLocaleString()}` : "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-500">Repair estimate</dt>
                <dd>{data.property.repair_estimate ? `$${data.property.repair_estimate.toLocaleString()}` : "—"}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-sm text-ink-500">No property linked to this lead.</p>
          )}

          <h2 className="mb-2 mt-5 text-sm font-semibold text-ink-800">Stage</h2>
          <select
            className="input"
            value={data.pipeline_stage}
            onChange={(e) =>
              run("stage", () => apiPatch(`/api/leads/${data.id}`, { pipeline_stage: e.target.value }))
            }
          >
            {ref.data?.stages.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
          <label className="label mt-3">Assigned manager</label>
          <input
            className="input"
            defaultValue={data.assigned_manager || ""}
            onBlur={(e) =>
              run("manager", () => apiPatch(`/api/leads/${data.id}`, { assigned_manager: e.target.value }))
            }
          />
          <label className="label mt-3">Internal notes</label>
          <textarea
            className="input min-h-[90px]"
            defaultValue={data.notes || ""}
            onBlur={(e) => run("notes", () => apiPatch(`/api/leads/${data.id}`, { notes: e.target.value }))}
          />
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={data.do_not_contact}
              onChange={(e) => run("dnc", () => apiPatch(`/api/leads/${data.id}`, { do_not_contact: e.target.checked }))}
            />
            Do Not Contact
          </label>
        </section>

        {/* Follow-ups + AI */}
        <div className="space-y-4">
          <section className="card p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-ink-800">Follow-ups</h2>
              <button className="btn" onClick={() => setCompleteOpen((v) => !v)}>
                {completeOpen ? "Close" : "Complete / schedule"}
              </button>
            </div>
            {openFollowups.length === 0 ? (
              <p className="text-sm text-ink-500">No open follow-up scheduled.</p>
            ) : (
              <ul className="space-y-2">
                {openFollowups.map((f) => (
                  <li key={f.id} className="rounded-lg border border-ink-200 p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className={`text-sm font-medium ${isOverdue(f.due_at) ? "text-red-700" : ""}`}>
                        {fmtDateTime(f.due_at)}
                      </span>
                      <Badge className="bg-ink-100 text-ink-700">P{f.priority}</Badge>
                    </div>
                    <div className="mt-1 text-xs text-ink-600">{f.reason}</div>
                    {f.suggested_next_action && <div className="mt-1 text-xs text-ink-500">{f.suggested_next_action}</div>}
                    <div className="mt-2 flex gap-2">
                      <button
                        className="btn"
                        disabled={busy === `fu-${f.id}`}
                        onClick={() => run(`fu-${f.id}`, () => apiPost(`/api/followups/${f.id}/cancel`))}
                      >
                        Cancel
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            {completeOpen && (
              <div className="mt-3 rounded-lg border border-ink-200 bg-ink-50 p-3">
                <label className="label">Outcome of what you actually did</label>
                <select className="input" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                  {OUTCOME_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <label className="label mt-2">Notes</label>
                <textarea className="input min-h-[60px]" value={note} onChange={(e) => setNote(e.target.value)} />
                <label className="label mt-2">Next follow-up (optional)</label>
                <input type="datetime-local" className="input" value={nextAt} onChange={(e) => setNextAt(e.target.value)} />
                <div className="mt-2 flex gap-2">
                  <button
                    className="btn-primary"
                    disabled={busy === "complete"}
                    onClick={() =>
                      run("complete", async () => {
                        const fus = openFollowups;
                        if (fus.length > 0) {
                          await apiPost(`/api/followups/${fus[0].id}/complete`, {
                            outcome,
                            notes: note || undefined,
                            schedule_next_at: nextAt ? new Date(nextAt).toISOString() : undefined,
                          });
                        } else {
                          await apiPost(`/api/leads/${data.id}/activities`, {
                            activity_type: "call",
                            direction: "outbound",
                            outcome,
                            summary: `Recorded outcome: ${outcome}`,
                            detail: note || undefined,
                          });
                          if (nextAt) {
                            await apiPost("/api/followups", {
                              lead_id: data.id,
                              due_at: new Date(nextAt).toISOString(),
                              reason: "Next step",
                              priority: 3,
                            });
                          }
                        }
                        setNote("");
                        setNextAt("");
                        setCompleteOpen(false);
                      })
                    }
                  >
                    Save outcome
                  </button>
                </div>
                <p className="mt-2 text-[11px] leading-snug text-ink-500">
                  This records what <span className="font-semibold">you</span> did. The application does not place the
                  call or send the message.
                </p>
              </div>
            )}
          </section>

          <section className="card p-4">
            <h2 className="mb-1 text-sm font-semibold text-ink-800">AI analysis</h2>
            <p className="mb-2 text-xs text-ink-500">
              {ai.data?.available
                ? `Local model: ${ai.data.model_in_use}`
                : "Local AI unavailable — rule-based analysis is used."}
            </p>
            <button
              className="btn-primary"
              disabled={busy === "analyze"}
              onClick={() =>
                run("analyze", async () => {
                  const result = await apiPost<Insight>(`/api/ai/analyze/${data.id}?force=true`);
                  setInsight(result);
                })
              }
            >
              {busy === "analyze" ? "Analyzing…" : "Analyze lead"}
            </button>
            {(insight || data.insights?.[0]) && (
              <div className="mt-3 space-y-2 text-sm">
                {(() => {
                  const ins = insight || data.insights![0];
                  return (
                    <>
                      <div className="rounded-lg bg-ink-50 p-2.5 text-ink-800">{ins.summary}</div>
                      <div>
                        <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">Motivation</span>
                        <div>{ins.seller_motivation}</div>
                      </div>
                      {ins.urgency_indicators && ins.urgency_indicators.length > 0 && (
                        <div>
                          <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">Urgency</span>
                          <ul className="list-disc pl-4 text-xs">
                            {ins.urgency_indicators.map((u, i) => (
                              <li key={i}>{u}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {ins.objections && ins.objections.length > 0 && (
                        <div>
                          <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">Objections</span>
                          <ul className="list-disc pl-4 text-xs">
                            {ins.objections.map((u, i) => (
                              <li key={i}>{u}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {ins.missing_information && ins.missing_information.length > 0 && (
                        <div>
                          <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">Missing</span>
                          <ul className="list-disc pl-4 text-xs">
                            {ins.missing_information.map((u, i) => (
                              <li key={i}>{u}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {ins.recommended_next_action && (
                        <div>
                          <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                            Recommended next action
                          </span>
                          <div className="font-medium">{ins.recommended_next_action}</div>
                        </div>
                      )}
                      {ins.evidence && ins.evidence.length > 0 && (
                        <div>
                          <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">Evidence</span>
                          <ul className="space-y-0.5 text-xs text-ink-600">
                            {ins.evidence.slice(0, 6).map((ev, i) => (
                              <li key={i} className="truncate">
                                {ev.quote || ev.ref}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      <div className="text-[11px] text-ink-400">
                        engine: {ins.engine}
                        {ins.model ? ` · ${ins.model}` : ""} · confidence: {ins.confidence || "n/a"} ·{" "}
                        {fmtDateTime(ins.created_at)}
                      </div>
                    </>
                  );
                })()}
              </div>
            )}
          </section>

          <section className="card p-4">
            <h2 className="mb-1 text-sm font-semibold text-ink-800">Message draft</h2>
            <p className="mb-2 text-[11px] leading-snug text-ink-500">
              Drafts are advisory. Nothing is ever sent from this application — copy the text into your company&apos;s
              approved workflow.
            </p>
            <button
              className="btn-primary"
              disabled={busy === "draft"}
              onClick={() =>
                run("draft", async () => {
                  const result = await apiPost<Draft>(`/api/ai/draft/${data.id}`, { channel: "text", force: true });
                  setDraft(result);
                })
              }
            >
              {busy === "draft" ? "Generating…" : "Generate draft"}
            </button>
            {(draft || data.drafts?.[0]) && (
              <div className="mt-3">
                {(() => {
                  const d = draft || data.drafts![0];
                  if (d.refusal_reason) {
                    return (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-sm text-amber-900">
                        Draft not generated: {d.refusal_reason}
                      </div>
                    );
                  }
                  const body = d.edited_body ?? d.body;
                  return (
                    <>
                      <textarea
                        className="input min-h-[140px] font-mono text-xs"
                        defaultValue={body}
                        key={d.id + (d.edited_body || d.body)}
                        onBlur={(e) =>
                          run(`edit-${d.id}`, () => apiPatch(`/api/ai/drafts/${d.id}`, { edited_body: e.target.value }))
                        }
                      />
                      <div className="mt-2 flex flex-wrap gap-2">
                        <CopyButton text={body} />
                        <button
                          className="btn"
                          disabled={busy === `regen-${d.id}`}
                          onClick={() =>
                            run(`regen-${d.id}`, async () => {
                              const result = await apiPost<Draft>(`/api/ai/draft/${data.id}`, {
                                channel: "text",
                                force: true,
                              });
                              setDraft(result);
                            })
                          }
                        >
                          Regenerate
                        </button>
                      </div>
                      {d.context_used && d.context_used.length > 0 && (
                        <div className="mt-2">
                          <div className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                            Context used
                          </div>
                          <ul className="mt-0.5 space-y-0.5 text-[11px] text-ink-600">
                            {d.context_used.map((c, i) => (
                              <li key={i}>
                                <span className="font-medium">{c.type}</span>: {c.value || c.id}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            )}
          </section>
        </div>
      </div>

      {/* Call plan + comps */}
      <div className="anim-in mt-4 grid gap-4 xl:grid-cols-2">
        <section className="card p-4">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-ink-800">Call plan — script & question checklist</h2>
              <p className="text-[11px] leading-snug text-ink-500">
                Built from this lead&apos;s records. Tick questions as you ask them — state saves automatically.
                Nothing is dialed from this app.
              </p>
            </div>
            <button
              className="btn-primary"
              disabled={busy === "plan"}
              onClick={() =>
                run("plan", async () => {
                  const result = await apiPost<CallPlan>(
                    `/api/ai/call-plan/${data.id}?force=${plan ? "true" : "false"}`,
                  );
                  setPlan(result);
                })
              }
            >
              {busy === "plan" ? "Preparing…" : plan ? "Regenerate" : "Generate call plan"}
            </button>
          </div>

          {plan ? (
            plan.refusal_reason ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                Call plan not generated: {plan.refusal_reason}
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">Opener</span>
                  <textarea
                    className="input mt-1 min-h-[64px]"
                    key={`${plan.id}-opener-${plan.opener || ""}`}
                    defaultValue={plan.opener || ""}
                    onBlur={(e) =>
                      apiPatch<CallPlan>(`/api/ai/call-plan/${data.id}`, { opener: e.target.value }).then(setPlan)
                    }
                  />
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <div className="mb-1.5 flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                        Questions to ask
                      </span>
                      <span className="text-[11px] text-ink-400">
                        {plan.questions.filter((q) => q.asked).length}/{plan.questions.length} asked
                      </span>
                    </div>
                    <ul className="stagger space-y-1.5">
                      {plan.questions.map((q, i) => (
                        <li key={`q-${i}`}>
                          <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-ink-200 p-2 text-sm transition hover:border-brand-300 hover:bg-brand-50/50">
                            <input
                              type="checkbox"
                              className="mt-0.5"
                              checked={q.asked}
                              onChange={() => toggleQuestion(i)}
                            />
                            <span className={q.asked ? "text-ink-400 line-through" : "text-ink-700"}>
                              {q.required && (
                                <span className="mr-1 font-semibold text-brand-700" title="Required question">
                                  *
                                </span>
                              )}
                              {q.text}
                            </span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div>
                    <div className="mb-1.5 flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                        Talking points
                      </span>
                      <span className="text-[11px] text-ink-400">
                        {plan.talking_points.filter((p) => p.used).length}/{plan.talking_points.length} covered
                      </span>
                    </div>
                    <ul className="stagger space-y-1.5">
                      {plan.talking_points.map((p, i) => (
                        <li key={`p-${i}`}>
                          <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-ink-200 p-2 text-sm transition hover:border-brand-300 hover:bg-brand-50/50">
                            <input
                              type="checkbox"
                              className="mt-0.5"
                              checked={p.used}
                              onChange={() => togglePoint(i)}
                            />
                            <span className={p.used ? "text-ink-400 line-through" : "text-ink-700"}>{p.text}</span>
                          </label>
                        </li>
                      ))}
                    </ul>

                    {plan.do_not_say.length > 0 && (
                      <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-2.5">
                        <span className="text-xs font-semibold uppercase tracking-wide text-red-700">Do not say</span>
                        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-red-800">
                          {plan.do_not_say.map((d, i) => (
                            <li key={`d-${i}`}>{d}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <CopyButton text={composeCallScript(plan)} />
                  <span className="text-[11px] text-ink-400">
                    engine: {plan.engine}
                    {plan.model ? ` · ${plan.model}` : ""} · {fmtDateTime(plan.created_at)}
                  </span>
                </div>
              </div>
            )
          ) : (
            <p className="text-sm text-ink-500">
              No call plan yet — generate one to get an opener, talking points and a tickable question checklist for
              this seller.
            </p>
          )}
        </section>

        <section className="card p-4">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-ink-800">Comps — subject & search criteria</h2>
              <p className="text-[11px] leading-snug text-ink-500">
                This app has no MLS feed, so comp addresses and sold prices are never invented here. Use the criteria
                below inside the portal links — they open with this property&apos;s address.
              </p>
            </div>
            <button className="btn" disabled={comps.loading} onClick={() => comps.reload()}>
              {comps.loading ? "Loading…" : "Refresh"}
            </button>
          </div>

          {comps.error ? (
            <ErrorBox message={comps.error} onRetry={comps.reload} />
          ) : !comps.data ? (
            <Spinner label="Loading comps brief…" />
          ) : comps.data.subject ? (
            (() => {
              const s = comps.data!.subject!;
              const crit = comps.data!.criteria;
              const chips: string[] = [];
              if (s.beds != null) chips.push(`${s.beds} bd`);
              if (s.baths != null) chips.push(`${s.baths} ba`);
              if (s.sqft != null) chips.push(`${s.sqft.toLocaleString()} sq ft`);
              if (s.year_built != null) chips.push(`built ${s.year_built}`);
              if (s.lot_acres != null) chips.push(`${s.lot_acres} ac lot`);
              if (s.county) chips.push(s.county);
              if (s.property_type) chips.push(s.property_type);
              const money = (v?: number | null) => (v ? `$${v.toLocaleString()}` : null);
              return (
                <>
                  <div className="rounded-lg bg-brand-50 p-2.5">
                    <div className="text-sm font-semibold text-brand-900">{s.address}</div>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {chips.map((c) => (
                        <span
                          key={c}
                          className="rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-brand-700 ring-1 ring-brand-200"
                        >
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="mt-3">
                    <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                      Comp search criteria
                    </span>
                    <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                      <div className="flex justify-between gap-2">
                        <dt className="text-ink-500">Beds</dt>
                        <dd>
                          {crit.beds_min ?? "?"}–{crit.beds_max ?? "?"}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-ink-500">Baths</dt>
                        <dd>
                          {crit.baths_min ?? "?"}–{crit.baths_max ?? "?"}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-ink-500">Sq ft</dt>
                        <dd>
                          {crit.sqft_min ? crit.sqft_min.toLocaleString() : "?"}–
                          {crit.sqft_max ? crit.sqft_max.toLocaleString() : "?"}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-ink-500">Price</dt>
                        <dd>
                          {money(crit.price_min) || "?"}–{money(crit.price_max) || "?"}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-ink-500">Sold within</dt>
                        <dd>{crit.sold_within_months} months</dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-ink-500">Area</dt>
                        <dd>{crit.radius}</dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-ink-500">Min comps</dt>
                        <dd>{crit.min_comps}</dd>
                      </div>
                      <div className="flex justify-between gap-2">
                        <dt className="text-ink-500">Type</dt>
                        <dd>{crit.property_type || "any"}</dd>
                      </div>
                    </dl>
                  </div>

                  {comps.data.value_refs.length > 0 && (
                    <div className="mt-3">
                      <span className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                        Recorded values (source records)
                      </span>
                      <ul className="mt-1 space-y-0.5 text-sm">
                        {comps.data.value_refs.map((v) => (
                          <li key={v.label} className="flex items-baseline justify-between gap-2">
                            <span className="text-ink-600">
                              {v.label} <span className="text-[11px] text-ink-400">· {v.source}</span>
                            </span>
                            <span className="font-medium tabular-nums">${v.value.toLocaleString()}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="mt-3 flex flex-wrap gap-2">
                    {Object.entries(comps.data.links).map(([key, url]) => (
                      <a
                        key={key}
                        className="btn"
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Open {COMP_PORTAL_LABELS[key] || key} ↗
                      </a>
                    ))}
                  </div>

                  <p className="mt-2 text-[11px] leading-snug text-ink-500">{comps.data.notes}</p>
                </>
              );
            })()
          ) : (
            <p className="text-sm text-ink-500">{comps.data.reason}</p>
          )}
        </section>
      </div>

      {/* Timeline */}
      <section className="card mt-4 p-4">
        <h2 className="mb-3 text-sm font-semibold text-ink-800">Activity timeline</h2>
        {data.timeline.length === 0 ? (
          <p className="text-sm text-ink-500">No activity recorded yet.</p>
        ) : (
          <ol className="relative space-y-3 border-l border-ink-200 pl-4">
            {data.timeline.map((item, idx) => (
              <li key={idx} className="relative">
                <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-ink-400" />
                <div className="flex flex-wrap items-center gap-2 text-xs text-ink-500">
                  <span className="font-semibold uppercase tracking-wide">{item.kind}</span>
                  <span>{fmtDateTime(item.occurred_at)}</span>
                  <Badge
                    className={
                      item.source === "resimpli"
                        ? "bg-blue-100 text-blue-800"
                        : item.source === "import"
                          ? "bg-amber-100 text-amber-800"
                          : "bg-ink-100 text-ink-700"
                    }
                  >
                    {item.source}
                  </Badge>
                </div>
                <div className="mt-0.5 text-sm text-ink-800">
                  {String(item.data.summary || item.data.reason || item.data.status || item.data.type || "")}
                </div>
                {item.data.detail ? <div className="text-xs text-ink-600">{String(item.data.detail)}</div> : null}
                {item.data.outcome ? (
                  <div className="text-xs text-ink-500">outcome: {String(item.data.outcome)}</div>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="card mt-4 p-4">
        <h2 className="mb-3 text-sm font-semibold text-ink-800">Raw source detail</h2>
        <div className="grid gap-4 text-sm md:grid-cols-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">Appointments</div>
            {data.appointments.length === 0 ? (
              <p className="text-ink-500">None</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {data.appointments.map((a) => (
                  <li key={a.id}>
                    {fmtDateTime(a.scheduled_at)} · {a.status}
                    {a.notes ? ` · ${a.notes}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">Activities (source)</div>
            {data.activities.length === 0 ? (
              <p className="text-ink-500">None</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {data.activities.slice(0, 15).map((a) => (
                  <li key={a.id}>
                    {fmtDateTime(a.occurred_at)} · {a.activity_type}
                    {a.outcome ? `/${a.outcome}` : ""} · {a.source}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">All follow-ups</div>
            {data.followups.length === 0 ? (
              <p className="text-ink-500">None</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {data.followups.map((f) => (
                  <li key={f.id}>
                    {fmtDateTime(f.due_at)} · {f.status}
                    {f.completion_outcome ? ` · ${f.completion_outcome}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
