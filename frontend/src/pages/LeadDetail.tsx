import {
  CallPreparation,
  PropertyResearch,
  RichPropertyFacts,
} from "../unified";
import { navigateTabs } from "../components";
import { CloudWorkbench } from "../intelligence";
import { useState, useEffect } from "react";
import type { FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  CalendarDays,
  Check,
  CheckCircle2,
  Clipboard,
  Clock3,
  FileText,
  History,
  House,
  MapPin,
  MessageSquareText,
  MoreHorizontal,
  NotebookPen,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  EvidenceList,
  Field,
  FollowupCreate,
  FollowupDialog,
  Info,
  Loading,
  Modal,
  Notice,
  PageHeader,
  Panel,
  RestrictionBadge,
  StageBadge,
  Timestamp,
  useAction,
  useData,
  useWorkspace,
} from "../components";
import { currency, dateTime, human, isoFromLocal, patch, post } from "../api";
import type {
  Appointment,
  Draft,
  Followup,
  Insight,
  LeadProfile,
} from "../types";

export default function LeadDetail() {
  const { id } = useParams();
  const data = useData<LeadProfile>("profile", `/leads/${id}`);
  const [params] = useSearchParams();
  const [tab, setTab] = useState(
    params.get("view") === "intelligence" ? "intelligence" : "overview",
  );
  const [dialog, setDialog] = useState("");
  const [followup, setFollowup] = useState<{
    f: Followup;
    mode: "complete" | "reschedule" | "cancel";
  } | null>(null);
  const { meta } = useWorkspace();
  const action = useAction();
  if (data.isPending) return <Loading />;
  if (data.isError)
    return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const lead = data.data;
  return (
    <>
      <Link className="back-link" to="/leads">
        <ArrowLeft size={14} />
        All seller leads
      </Link>
      <PageHeader
        eyebrow={`SELLER PROFILE · LOCAL ID ${lead.id}`}
        title={lead.full_name || "Owner identity unknown"}
        description={
          lead.properties.length
            ? lead.properties
                .map((p) =>
                  [p.street_address, p.city, p.state]
                    .filter(Boolean)
                    .join(", "),
                )
                .join(" · ")
            : "Property information has not been supplied."
        }
        actions={
          <>
            <Button variant="secondary" onClick={() => setDialog("note")}>
              <NotebookPen size={16} />
              Record activity
            </Button>
            <Button onClick={() => setDialog("followup")}>
              <Plus size={17} />
              Schedule follow-up
            </Button>
          </>
        }
      />
      <div className="profile-statusbar">
        <StageBadge code={lead.stage_code} />
        <RestrictionBadge status={lead.restriction_status} />
        <Badge tone="neutral">{human(lead.source_kind)}</Badge>
        <span className="muted">
          Source stage: {lead.source_status || "Not supplied"}
        </span>
        {lead.local_stage_override && (
          <Badge tone="purple">Local stage override</Badge>
        )}
        <button className="text-link" onClick={() => setDialog("stage")}>
          Change local stage
        </button>
      </div>
      {lead.do_not_contact ? (
        <Notice tone="danger">
          <strong>Do Not Contact.</strong> This lead is excluded from ordinary
          outreach queues. Draft generation is blocked. Source restrictions
          cannot be cleared locally.
        </Notice>
      ) : lead.restriction_status === "unknown" ? (
        <Notice tone="warning">
          <strong>Contact eligibility is unknown.</strong> Do not assume this
          seller is cleared for outreach.{" "}
          <button
            className="text-link"
            onClick={() => setDialog("restriction")}
          >
            Record an evidence-based review
          </button>
        </Notice>
      ) : null}
      <div
        className="tabs"
        role="tablist"
        aria-label="Lead profile sections"
        onKeyDown={navigateTabs}
      >
        {[
          ["overview", "Overview"],
          ["timeline", `Timeline (${lead.activities.length})`],
          [
            "followups",
            `Follow-ups (${lead.followups.filter((f) => f.status === "pending").length})`,
          ],
          ["appointments", `Appointments (${lead.appointments.length})`],
          ["preparation", "Call preparation"],
          ["research", "Property research"],
          ["intelligence", "Analysis & drafts"],
          ["audit", "Audit trail"],
          ["source", "Source records"],
        ].map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            tabIndex={tab === key ? 0 : -1}
            className={tab === key ? "active" : ""}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "preparation" && <CallPreparation lead={lead} />}
      {tab === "research" && <PropertyResearch lead={lead} />}
      {tab === "overview" && (
        <div className="profile-grid">
          <div className="stack">
            <Panel
              title="Seller details"
              action={<Badge tone="neutral">Source + local review</Badge>}
            >
              <div className="info-grid">
                <Info label="Full name">
                  {lead.full_name || "Not recorded — property-only prospect"}
                </Info>
                <Info label="Phone numbers">
                  {(() => {
                    const phones: any[] = (lead as any).phones || [];
                    if (phones.length) {
                      return phones.map((p: any) => (
                        <div key={p.id || p.position} style={{ marginBottom: 2 }}>
                          {p.phone}
                          {p.phone_type ? ` (${p.phone_type})` : ""}
                          {p.is_primary ? " — primary" : ""}
                        </div>
                      ));
                    }
                    return (
                      <>
                        {lead.primary_phone && <div>{lead.primary_phone}</div>}
                        {lead.phone2 && <div>{lead.phone2}{lead.phone2_type ? ` (${lead.phone2_type})` : ""}</div>}
                        {lead.phone3 && <div>{lead.phone3}{lead.phone3_type ? ` (${lead.phone3_type})` : ""}</div>}
                        {lead.phone4 && <div>{lead.phone4}{lead.phone4_type ? ` (${lead.phone4_type})` : ""}</div>}
                        {lead.phone5 && <div>{lead.phone5}{lead.phone5_type ? ` (${lead.phone5_type})` : ""}</div>}
                        {!lead.primary_phone && !lead.phone2 && !lead.phone3 && !lead.phone4 && !lead.phone5 && "Not recorded"}
                      </>
                    );
                  })()}
                </Info>
                <Info label="Email">{lead.email}</Info>
                <Info label="Assigned manager">{lead.assigned_manager}</Info>
                <Info label="Lead source">{lead.lead_source}</Info>
                <Info label="Original creation date">
                  <Timestamp value={lead.original_created_at} />
                </Info>
                <Info label="Contact evidence">
                  {lead.contact_status === "contacted"
                    ? "Explicit contact evidence recorded"
                    : lead.contact_status === "attempted"
                      ? "Attempt recorded, no verified connection"
                      : "No verified contact evidence"}
                </Info>
                <Info label="Last verified contact">
                  <Timestamp value={lead.last_contact_at} />
                </Info>
                <Info label="Last recorded contact outcome">
                  {lead.contact_outcome}
                </Info>
                <Info label="External REsimpli ID">{lead.external_id}</Info>
              </div>
              <div className="profile-panel-footer">
                <Button
                  variant="ghost"
                  onClick={() => setDialog("restriction")}
                >
                  <ShieldCheck size={14} />
                  Review contact restrictions
                </Button>
                <span className="muted">
                  {lead.restriction_evidence ||
                    "No local permission review recorded."}
                </span>
              </div>
            </Panel>
            {lead.properties.length ? (
              lead.properties.map((p) => (
                <Panel
                  key={p.id}
                  title="Property details"
                  action={
                    <Badge tone="teal">
                      <House size={11} />
                      {p.property_type || "Type unknown"}
                    </Badge>
                  }
                >
                  <div className="property-address">
                    <MapPin size={21} />
                    <div>
                      <h3>{p.street_address}</h3>
                      <p>
                        {[p.city, p.state, p.zip_code]
                          .filter(Boolean)
                          .join(", ")}
                      </p>
                    </div>
                  </div>
                  <div className="property-prices">
                    <Info label="Seller asking price">
                      {currency(p.asking_price)}
                    </Info>
                    <Info label="Estimated value">
                      {currency(p.estimated_value)}
                    </Info>
                    <Info label="Repair estimate">
                      {currency(p.repair_estimate)}
                    </Info>
                  </div>
                  <div className="info-grid info-grid-four">
                    <Info label="Bedrooms">{p.bedrooms ?? "Unknown"}</Info>
                    <Info label="Bathrooms">{p.bathrooms ?? "Unknown"}</Info>
                    <Info label="Square feet">
                      {p.square_feet?.toLocaleString() || "Unknown"}
                    </Info>
                    <Info label="Year built">{p.year_built ?? "Unknown"}</Info>
                  </div>
                  <RichPropertyFacts property={p} />
                </Panel>
              ))
            ) : (
              <Panel title="Property information">
                <Empty
                  title="Property details are missing"
                  description="Review the original source. No address, condition or value will be invented."
                />
              </Panel>
            )}
            <Panel
              title="Latest activity"
              action={
                <button
                  className="text-link"
                  onClick={() => setTab("timeline")}
                >
                  View full timeline <History size={14} />
                </button>
              }
            >
              <Timeline
                lead={{ ...lead, activities: lead.activities.slice(0, 3) }}
              />
            </Panel>
          </div>
          <div className="stack">
            <Panel
              title="Recommended next step"
              action={<Sparkles size={18} className="text-green" />}
            >
              <div className="recommendation">
                <Badge tone={lead.insight_stale ? "amber" : "teal"}>
                  {lead.insight_stale
                    ? "Analysis needs refresh"
                    : lead.insight
                      ? "Evidence-linked analysis"
                      : "Analysis not yet run"}
                </Badge>
                <p>
                  {lead.insight?.recommended_action ||
                    (lead.do_not_contact
                      ? "Preserve the contact restriction. Review internal records only."
                      : "Review source information and contact restrictions before deciding the next action.")}
                </p>
                <Button
                  variant="secondary"
                  busy={action.busy}
                  onClick={() =>
                    action.run(
                      () => post(`/leads/${id}/analyze`),
                      "Evidence analysis updated",
                    )
                  }
                >
                  <Sparkles size={14} />
                  Analyze available context
                </Button>
              </div>
            </Panel>
            <Panel
              title="Data review checklist"
              subtitle="Unknown is better than assumed."
            >
              <ul className="checklist">
                {lead.missing_information.length ? (
                  lead.missing_information.map((m) => (
                    <li key={m}>
                      <span className="check-empty" />
                      {m}
                    </li>
                  ))
                ) : (
                  <li>
                    <CheckCircle2 size={15} className="text-green" />
                    Core fields are present.
                  </li>
                )}
              </ul>
            </Panel>
            <Panel title="Next follow-up">
              <div className="next-followup">
                <Clock3 size={22} />
                <strong>
                  <Timestamp value={lead.next_followup_at} />
                </strong>
                <p>
                  {lead.next_followup_at
                    ? "An explicit schedule is recorded."
                    : "No scheduled date. This is not automatically overdue."}
                </p>
                <Button
                  variant="secondary"
                  onClick={() => setDialog("followup")}
                >
                  Create local follow-up
                </Button>
              </div>
            </Panel>
          </div>
        </div>
      )}
      {tab === "timeline" && (
        <Panel
          title="Activity timeline"
          subtitle="Summaries, user-entered notes and source metadata. These are not complete conversation transcripts."
          action={
            <Button variant="secondary" onClick={() => setDialog("note")}>
              <Plus size={15} />
              Record activity
            </Button>
          }
        >
          <Timeline lead={lead} />
        </Panel>
      )}
      {tab === "followups" && (
        <Panel
          title="Follow-up schedule"
          subtitle="Completion requires an actual outcome. Local changes never update the CRM."
          action={
            <Button variant="secondary" onClick={() => setDialog("followup")}>
              <Plus size={15} />
              Add task
            </Button>
          }
        >
          {lead.followups.length ? (
            <div className="followup-list">
              {lead.followups.map((f) => (
                <div key={f.id} className="followup-item">
                  <span
                    className={`followup-icon ${f.status === "completed" ? "done" : ""}`}
                  >
                    {f.status === "completed" ? (
                      <Check size={19} />
                    ) : (
                      <Clock3 size={19} />
                    )}
                  </span>
                  <div>
                    <div className="row">
                      <strong>{f.reason}</strong>
                      <Badge
                        tone={
                          f.status === "pending"
                            ? "amber"
                            : f.status === "completed"
                              ? "green"
                              : "neutral"
                        }
                      >
                        {human(f.status)}
                      </Badge>
                      {f.ai_suggested && (
                        <Badge tone="purple">AI suggestion</Badge>
                      )}
                    </div>
                    <p>
                      <Timestamp value={f.due_at} /> · Priority {f.priority} ·{" "}
                      {f.creation_source}
                    </p>
                    {f.completion_outcome && (
                      <small>
                        Actual recorded outcome: {f.completion_outcome}
                      </small>
                    )}
                  </div>
                  {f.status === "pending" && (
                    <div className="row followup-actions">
                      <Button
                        variant="secondary"
                        onClick={() => setFollowup({ f, mode: "complete" })}
                      >
                        Complete
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => setFollowup({ f, mode: "reschedule" })}
                      >
                        Reschedule
                      </Button>
                      <button
                        className="icon-button"
                        title="Cancel follow-up"
                        aria-label="Cancel follow-up"
                        onClick={() => setFollowup({ f, mode: "cancel" })}
                      >
                        <X size={16} />
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <Empty
              title="No follow-ups recorded"
              description="Add a justified date or keep a task unscheduled. No artificial overdue date is inferred."
            />
          )}
        </Panel>
      )}
      {tab === "appointments" && (
        <Panel
          title="Seller appointments"
          subtitle="Source statuses are preserved; appointment results are stored locally."
          action={
            <Button
              variant="secondary"
              onClick={() => setDialog("appointment")}
            >
              <Plus size={15} />
              Record appointment
            </Button>
          }
        >
          {lead.appointments.length ? (
            <div className="appointment-cards">
              {lead.appointments.map((a) => (
                <AppointmentCard key={a.id} appointment={a} />
              ))}
            </div>
          ) : (
            <Empty
              title="No appointments recorded"
              description="Import available appointment dates or record a confirmed appointment locally."
            />
          )}
        </Panel>
      )}
      {tab === "intelligence" && (
        <>
          <CloudWorkbench lead={lead} />
          <div className="profile-grid">
            <AnalysisPanel lead={lead} />
            <DraftPanel lead={lead} />
          </div>
        </>
      )}
      {tab === "audit" && (
        <Panel
          title="Local audit trail"
          subtitle="Important actions remain distinguishable from source records."
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>WHEN</th>
                  <th>ACTION</th>
                  <th>ACTOR</th>
                  <th>DETAILS</th>
                </tr>
              </thead>
              <tbody>
                {lead.audit.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <Timestamp value={a.created_at} />
                    </td>
                    <td>{human(a.action)}</td>
                    <td>{a.actor}</td>
                    <td>
                      <code className="wrap-code">
                        {JSON.stringify(a.details)}
                      </code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!lead.audit.length && (
            <Empty
              title="No local actions yet"
              description="Local stage changes, notes, import approvals and task outcomes will be tracked here."
            />
          )}
        </Panel>
      )}
      {tab === "source" && (
        <div className="stack">
          <Notice>
            {lead.source_notice} No REsimpli profile URL has been constructed
            because an account-specific route has not been verified.
          </Notice>
          <Panel title="Source and normalization provenance">
            <div className="info-grid">
              <Info label="Imported / created locally">
                <Timestamp value={lead.created_at} />
              </Info>
              <Info label="Last synchronized">
                <Timestamp value={lead.synced_at} />
              </Info>
              <Info label="Original source status">{lead.source_status}</Info>
              <Info label="Source DNC flag">
                {lead.source_do_not_contact === null
                  ? "Unknown"
                  : String(lead.source_do_not_contact)}
              </Info>
            </div>
            <details className="raw-data">
              <summary>
                View original and normalized values (confidential)
              </summary>
              <pre>{JSON.stringify(lead.source_data, null, 2)}</pre>
            </details>
          </Panel>
          <Panel title="Observed stage history">
            <div className="timeline">
              {lead.stage_history.map((h, i) => (
                <div key={i} className="timeline-item">
                  <span className="timeline-dot" />
                  <div>
                    <strong>
                      {h.from_stage ? human(h.from_stage) + " → " : ""}
                      {human(h.to_stage)}
                    </strong>
                    <small>
                      {dateTime(h.changed_at, meta.timezone)} · {h.source}
                    </small>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      )}
      {dialog === "followup" && (
        <FollowupCreate leadId={lead.id} onClose={() => setDialog("")} />
      )}
      {dialog === "note" && (
        <ActivityDialog lead={lead} onClose={() => setDialog("")} />
      )}
      {dialog === "stage" && (
        <StageDialog lead={lead} onClose={() => setDialog("")} />
      )}
      {dialog === "restriction" && (
        <RestrictionDialog lead={lead} onClose={() => setDialog("")} />
      )}
      {dialog === "appointment" && (
        <AppointmentCreate leadId={lead.id} onClose={() => setDialog("")} />
      )}
      {followup && (
        <FollowupDialog
          followup={followup.f}
          mode={followup.mode}
          onClose={() => setFollowup(null)}
        />
      )}
    </>
  );
}
function Timeline({ lead }: { lead: LeadProfile }) {
  return lead.activities.length ? (
    <div className="timeline">
      {lead.activities.map((a) => (
        <div className="timeline-item" key={a.id}>
          <span
            className={`timeline-icon ${a.source === "local" ? "local" : ""}`}
          >
            {a.activity_type === "note" ? (
              <FileText size={16} />
            ) : (
              <MessageSquareText size={16} />
            )}
          </span>
          <div>
            <div className="row wrap">
              <strong>{human(a.activity_type)}</strong>
              <Badge tone={a.source === "local" ? "purple" : "neutral"}>
                {a.source === "local" ? "Local record" : a.source}
              </Badge>
              {a.outcome && (
                <Badge tone={a.outcome === "Connected" ? "green" : "neutral"}>
                  {a.outcome}
                </Badge>
              )}
            </div>
            <p className="preserve-whitespace">{a.summary}</p>
            <small>
              <Timestamp value={a.occurred_at} /> · Activity #{a.id}
              {a.external_id ? ` · Source ${a.external_id}` : ""}
            </small>
            {!a.occurred_at && (
              <small>
                Original event time unknown. Recorded locally{" "}
                <Timestamp value={a.recorded_at} />.
              </small>
            )}
          </div>
        </div>
      ))}
    </div>
  ) : (
    <Empty
      title="No contact history supplied"
      description="Absence of an activity is not proof of a conversation or a successful contact."
    />
  );
}
function ActivityDialog({
  lead,
  onClose,
}: {
  lead: LeadProfile;
  onClose: () => void;
}) {
  const { meta } = useWorkspace();
  const action = useAction();
  const [type, setType] = useState("note");
  const [outcome, setOutcome] = useState("");
  const [summary, setSummary] = useState("");
  const [confirm, setConfirm] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const r = await action.run(
      () =>
        post(`/leads/${lead.id}/activities`, {
          activity_type: type,
          summary,
          outcome: outcome || null,
          confirm,
        }),
      "Activity recorded locally",
    );
    if (r) onClose();
  }
  return (
    <Modal
      title="Record an actual activity"
      subtitle="Internal record only — this app never places calls or sends messages."
      onClose={onClose}
    >
      <form className="form-stack" onSubmit={submit}>
        <Field label="Record type">
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="note">Internal note</option>
            <option value="call">Call outcome (already occurred)</option>
            <option value="offer">Offer outcome (already occurred)</option>
            <option value="appointment_result">Appointment outcome</option>
          </select>
        </Field>
        {type !== "note" && (
          <Field label="Actual outcome">
            <select
              required
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
            >
              <option value="">Select actual outcome</option>
              {meta.outcomes.map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Notes / factual context">
          <textarea
            required
            rows={5}
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="Record what actually happened. Do not paste API keys or sensitive credentials."
          />
        </Field>
        {type !== "note" && (
          <label className="checkbox-label">
            <input
              required
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            I confirm this outcome actually occurred outside this app.
          </label>
        )}
        <div className="modal-actions">
          <Button variant="secondary" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={action.busy}>Save local record</Button>
        </div>
      </form>
    </Modal>
  );
}
function StageDialog({
  lead,
  onClose,
}: {
  lead: LeadProfile;
  onClose: () => void;
}) {
  const { meta } = useWorkspace();
  const [stage, setStage] = useState(lead.stage_code);
  const [confirm, setConfirm] = useState(false);
  const action = useAction();
  return (
    <Modal
      title="Change local pipeline stage"
      subtitle="REsimpli remains the source of truth. Original source status is preserved."
      onClose={onClose}
    >
      <form
        className="form-stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await action.run(
            () =>
              patch(`/leads/${lead.id}/stage`, { stage_code: stage, confirm }),
            "Local stage updated",
          );
          if (r) onClose();
        }}
      >
        <Field label="Local stage">
          <select value={stage} onChange={(e) => setStage(e.target.value)}>
            {meta.stages.map((s) => (
              <option key={s.code} value={s.code}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>
        <label className="checkbox-label">
          <input
            type="checkbox"
            required
            checked={confirm}
            onChange={(e) => setConfirm(e.target.checked)}
          />
          I confirm this local override. It does not update REsimpli.
        </label>
        <Button busy={action.busy}>Confirm local change</Button>
      </form>
    </Modal>
  );
}
function RestrictionDialog({
  lead,
  onClose,
}: {
  lead: LeadProfile;
  onClose: () => void;
}) {
  const [restricted, setRestricted] = useState(
    lead.do_not_contact ? "true" : "false",
  );
  const [evidence, setEvidence] = useState("");
  const [confirm, setConfirm] = useState(false);
  const action = useAction();
  return (
    <Modal
      title="Review contact restrictions"
      subtitle="Never assume permission. A verified source DNC cannot be cleared locally."
      onClose={onClose}
    >
      <form
        className="form-stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await action.run(
            () =>
              post(`/leads/${lead.id}/restriction`, {
                restricted: restricted === "true",
                evidence,
                confirm,
              }),
            "Restriction review saved",
          );
          if (r) onClose();
        }}
      >
        <Notice tone="warning">
          This review records your verified findings. It is not legal clearance
          or consent and never initiates communication.
        </Notice>
        <Field label="Verified restriction result">
          <select
            value={restricted}
            onChange={(e) => setRestricted(e.target.value)}
          >
            <option value="true">Do Not Contact — restricted</option>
            <option
              value="false"
              disabled={lead.source_do_not_contact === true}
            >
              Restriction reviewed — no DNC found
            </option>
          </select>
        </Field>
        <Field label="Evidence / approved review basis">
          <textarea
            required
            minLength={5}
            value={evidence}
            onChange={(e) => setEvidence(e.target.value)}
            placeholder="Record where and how the restriction was verified."
          />
        </Field>
        <label className="checkbox-label">
          <input
            type="checkbox"
            required
            checked={confirm}
            onChange={(e) => setConfirm(e.target.checked)}
          />
          I verified the evidence and confirm this local review.
        </label>
        <Button busy={action.busy}>Save restriction review</Button>
      </form>
    </Modal>
  );
}
export function AppointmentCreate({
  leadId,
  onClose,
}: {
  leadId: number;
  onClose: () => void;
}) {
  const [at, setAt] = useState("");
  const [notes, setNotes] = useState("");
  const action = useAction();
  return (
    <Modal
      title="Record a seller appointment"
      subtitle="A local calendar record; no invitation or reminder is sent."
      onClose={onClose}
    >
      <form
        className="form-stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await action.run(
            () =>
              post("/appointments", {
                lead_id: leadId,
                starts_at: isoFromLocal(at),
                notes,
              }),
            "Appointment saved locally",
          );
          if (r) onClose();
        }}
      >
        <Field
          label="Confirmed date and time"
          hint="Enter in this browser’s local timezone."
        >
          <input
            required
            type="datetime-local"
            value={at}
            onChange={(e) => setAt(e.target.value)}
          />
        </Field>
        <Field label="Appointment notes">
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
        <Button busy={action.busy}>Save local appointment</Button>
      </form>
    </Modal>
  );
}
export function AppointmentCard({
  appointment: a,
}: {
  appointment: Appointment;
}) {
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState("kept");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const action = useAction();
  return (
    <div className="appointment-card">
      <span className="calendar-tile">
        <CalendarDays size={21} />
      </span>
      <div>
        <strong>
          <Timestamp value={a.starts_at} />
        </strong>
        {a.seller && (
          <Link className="text-link" to={`/leads/${a.lead_id}`}>
            {a.seller}
          </Link>
        )}
        <p>{a.notes || "No appointment notes supplied."}</p>
        <div className="row">
          <Badge tone={a.local_result ? "green" : "blue"}>
            {a.local_result ? human(a.local_result) : human(a.status)}
          </Badge>
          <Badge>{a.source}</Badge>
          {a.local_result && (
            <small>Local result · source status preserved</small>
          )}
        </div>
      </div>
      <Button variant="ghost" onClick={() => setOpen(true)}>
        <MoreHorizontal size={17} />
        Record result
      </Button>
      {open && (
        <Modal
          title="Record appointment result"
          subtitle="This will not update REsimpli or contact the seller."
          onClose={() => setOpen(false)}
        >
          <form
            className="form-stack"
            onSubmit={async (e) => {
              e.preventDefault();
              const r = await action.run(
                () =>
                  post(`/appointments/${a.id}/result`, {
                    result,
                    note,
                    confirm,
                  }),
                "Appointment result recorded",
              );
              if (r) setOpen(false);
            }}
          >
            <Field label="Actual appointment result">
              <select
                value={result}
                onChange={(e) => setResult(e.target.value)}
              >
                {[
                  "kept",
                  "not_kept",
                  "no_answer",
                  "dismissed",
                  "cancelled",
                ].map((r) => (
                  <option key={r} value={r}>
                    {human(r)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Notes">
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>
            <label className="checkbox-label">
              <input
                type="checkbox"
                required
                checked={confirm}
                onChange={(e) => setConfirm(e.target.checked)}
              />
              I confirm this result actually occurred.
            </label>
            <Button busy={action.busy}>Save local result</Button>
          </form>
        </Modal>
      )}
    </div>
  );
}
function AnalysisPanel({ lead }: { lead: LeadProfile }) {
  const action = useAction();
  const insight = lead.insight;
  return (
    <Panel
      title="Evidence-based lead analysis"
      subtitle="Explicit facts, inferences, unknowns and conflicts stay separate."
      action={
        <Button
          variant="secondary"
          busy={action.busy}
          onClick={() =>
            action.run(
              () => post<Insight>(`/leads/${lead.id}/analyze?force=true`),
              "Analysis refreshed",
            )
          }
        >
          <RefreshCw size={14} />
          Analyze
        </Button>
      }
    >
      {insight ? (
        <div className="analysis-content">
          {lead.insight_stale && (
            <Notice tone="warning">
              New context is available. Refresh this analysis before relying on
              it.
            </Notice>
          )}
          <p>{insight.summary}</p>
          <div className="row wrap">
            <Badge tone="purple">{insight.model_id}</Badge>
            <Badge>{insight.confidence}</Badge>
          </div>
          {insight.conflicts.map((c, i) => (
            <Notice key={i} tone="warning">
              {c}
            </Notice>
          ))}
          <div className="facts-list">
            {Object.entries(insight.facts).map(([key, f]) => (
              <div key={key}>
                <div className="row">
                  <strong>{human(key)}</strong>
                  <Badge
                    tone={
                      f.category === "explicit"
                        ? "green"
                        : f.category === "conflict"
                          ? "red"
                          : f.category === "inference"
                            ? "amber"
                            : "neutral"
                    }
                  >
                    {human(f.category)}
                  </Badge>
                </div>
                <p>
                  {f.value ?? "Unknown — more source information is required."}
                </p>
                {f.evidence.length > 0 && (
                  <small>Evidence: {f.evidence.join(", ")}</small>
                )}
                {f.quote && <blockquote>{f.quote}</blockquote>}
              </div>
            ))}
          </div>
          <div className="recommendation">
            <strong>Recommended next action</strong>
            <p>{insight.recommended_action}</p>
            <small>{insight.suggested_timing}</small>
          </div>
          <EvidenceList records={insight.evidence} />
          <small className="analysis-time">
            Analyzed <Timestamp value={insight.analysis_at} />
          </small>
        </div>
      ) : (
        <Empty
          title="Let the available evidence lead"
          description="Run a private, evidence-based analysis. If a local model is unavailable, deterministic source facts and missing-information checks still work."
          action={
            <Button
              busy={action.busy}
              onClick={() =>
                action.run(
                  () => post(`/leads/${lead.id}/analyze`),
                  "Analysis ready",
                )
              }
            >
              <Sparkles size={15} />
              Analyze this lead
            </Button>
          }
        />
      )}
    </Panel>
  );
}
function DraftPanel({ lead }: { lead: LeadProfile }) {
  const action = useAction();
  const { toast } = useWorkspace();
  const [current, setCurrent] = useState<Draft | null>(lead.draft);
  const [body, setBody] = useState(lead.draft?.body || "");
  useEffect(() => {
    if (lead.draft?.id !== current?.id) {
      setCurrent(lead.draft);
      setBody(lead.draft?.body || "");
    }
  }, [lead.draft, current?.id]);
  const blocked = lead.restriction_status !== "reviewed_clear";
  const stale = Boolean(lead.draft_stale && current?.id === lead.draft?.id);
  async function generate() {
    const d = await action.run(
      () => post<Draft>(`/leads/${lead.id}/draft`, { regenerate: true }),
      "Draft prepared for human review",
    );
    if (d) {
      setCurrent(d);
      setBody(d.body);
    }
  }
  return (
    <Panel
      title="Human-reviewed message draft"
      subtitle="Prepare. Edit. Copy. Never automatically sent."
      action={<MessageSquareText size={18} className="text-green" />}
    >
      <div className="draft-content">
        <Notice tone={blocked ? "warning" : "info"}>
          {lead.do_not_contact
            ? "Do Not Contact: marketing follow-up drafts are blocked."
            : blocked
              ? "Contact restrictions are unknown. Record an evidence-based review before preparing a draft."
              : "Drafts use verified source context only. Review all wording and follow your company’s approved communication workflow."}
        </Notice>
        {stale && !blocked && (
          <Notice tone="warning">
            Source context changed since this draft. Regenerate and review it
            before copying.
          </Notice>
        )}
        {current && !blocked ? (
          <>
            <Field label="Editable draft">
              <textarea
                rows={7}
                value={body}
                onChange={(e) => setBody(e.target.value)}
              />
            </Field>
            <div className="row wrap">
              <Button
                variant="secondary"
                busy={action.busy}
                onClick={() =>
                  action.run(
                    () => patch(`/drafts/${current.id}`, { body }),
                    "Draft edits saved locally",
                  )
                }
              >
                <Check size={15} />
                Save edits
              </Button>
              <Button
                disabled={stale}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(body);
                    toast("Draft copied. Nothing was sent.");
                  } catch {
                    toast(
                      "Clipboard unavailable. Select and copy the draft text manually.",
                      "error",
                    );
                  }
                }}
              >
                <Clipboard size={15} />
                Copy Draft
              </Button>
            </div>
            <EvidenceList records={current.context} />
            <small className="muted">
              {current.model_id} · Human review required
            </small>
          </>
        ) : (
          <div className="draft-empty">
            <MessageSquareText size={30} />
            <h3>No draft prepared</h3>
            <p>
              Enough relationship context is required. No generic message is
              created when context is insufficient.
            </p>
          </div>
        )}
        <Button
          variant="secondary"
          className="full-width"
          disabled={blocked}
          busy={action.busy}
          onClick={generate}
        >
          <Sparkles size={15} />
          {current
            ? "Regenerate from source context"
            : "Prepare a review-only draft"}
        </Button>
        {action.error && <Notice tone="warning">{action.error}</Notice>}
        <div className="draft-safety">
          <ShieldAlert size={15} />
          No send controls or automated outreach jobs exist.
        </div>
      </div>
    </Panel>
  );
}
