import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  CalendarClock,
  Check,
  ChevronRight,
  Clock3,
  MessageSquareText,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  FollowupCreate,
  FollowupDialog,
  Loading,
  Modal,
  Notice,
  PageHeader,
  Pagination,
  RestrictionBadge,
  StageBadge,
  Timestamp,
  useData,
  useWorkspace,
} from "../components";
import { human } from "../api";
import type { Followup, LeadPage, Queue, QueueItem } from "../types";

export default function QueuePage() {
  const { meta } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const section = params.get("section") || "overdue";
  const page = Number(params.get("page") || 1);
  const data = useData<Queue>(
    "queue",
    `/queue?section=${section}&page=${page}&page_size=20`,
  );
  const [selected, setSelected] = useState<{
    f: Followup;
    mode: "complete" | "reschedule" | "cancel";
  } | null>(null);
  const [rules, setRules] = useState(false);
  const [add, setAdd] = useState(false);
  return (
    <>
      <PageHeader
        eyebrow="ONE DAY. THE RIGHT PRIORITIES."
        title="Daily work queue"
        description="Nothing forgotten. Every next step grounded in what you actually know."
        actions={
          <>
            <Button variant="secondary" onClick={() => setRules(!rules)}>
              <SlidersHorizontal size={16} />
              Priority rules
            </Button>
            <Button onClick={() => setAdd(true)}>
              <Plus size={16} />
              Add follow-up
            </Button>
          </>
        }
      />
      <div className="queue-intro">
        <div className="row">
          <span className="queue-intro-icon">
            <CalendarClock size={21} />
          </span>
          <div>
            <strong>Your attention, directed.</strong>
            <p>
              Review first. Contact only through your approved company workflow.
            </p>
          </div>
        </div>
        <Badge tone="green">
          <ShieldCheck size={12} />
          Draft-only workspace
        </Badge>
      </div>
      {rules && (
        <Notice>
          <div className="rules-list">
            <strong>Transparent prioritization</strong>
            <p>{data.data?.definition}</p>
            <div className="row wrap">
              {Object.entries(data.data?.rules || {}).map(([k, v]) => (
                <Badge key={k}>
                  {human(k)}: {v}
                </Badge>
              ))}
            </div>
            <p>
              Task base priority + explicit callback, negotiation and
              appointment-stage bonuses + overdue-day weight, capped at 100. No
              AI date is silently scheduled.{" "}
              <Link to="/settings">Configure rules</Link>
            </p>
          </div>
        </Notice>
      )}
      <div className="queue-layout">
        <aside className="queue-sections">
          <div className="mini-label">WORK SECTIONS</div>
          {Object.entries(
            data.data?.labels || {
              overdue: "Overdue",
              today: "Due Today",
              new: "New Leads Not Contacted",
              callbacks: "Callbacks Requested",
              appointments: "Appointments Today",
              offers: "Offers Awaiting Response",
              negotiations: "Negotiations Requiring Attention",
              upcoming: "Upcoming",
              unscheduled: "Unscheduled Follow-ups",
              missing: "Missing Critical Information",
            },
          ).map(([key, label]) => (
            <button
              key={key}
              className={section === key ? "active" : ""}
              onClick={() => setParams({ section: key })}
            >
              <span>
                <i
                  className={`section-dot ${key === "overdue" ? "red" : key === "today" ? "green" : "gray"}`}
                />
                {label}
              </span>
              <b>{data.data?.counts[key] || 0}</b>
            </button>
          ))}
          <div className="queue-dnc">
            <ShieldCheck size={16} />
            <p>
              <strong>
                {data.data?.excluded_dnc || 0} restricted leads excluded.
              </strong>
              DNC leads never enter ordinary outreach queues.
            </p>
          </div>
        </aside>
        <section className="queue-main">
          <div className="queue-section-heading">
            <div>
              <h2>{data.data?.labels[section] || human(section)}</h2>
              <span>
                {data.data?.counts[section] || 0} items · {meta.timezone}
              </span>
            </div>
            <button className="text-link" onClick={() => data.refetch()}>
              <RefreshCw size={14} />
              Refresh
            </button>
          </div>
          {data.isPending ? (
            <Loading />
          ) : data.isError ? (
            <ErrorState error={data.error} retry={() => data.refetch()} />
          ) : !data.data.sections[section]?.length ? (
            <Empty
              title={
                section === "overdue"
                  ? "No overdue tasks. Keep it that way."
                  : "You’re clear in this section"
              }
              description="Only justified, recorded tasks appear here. An unknown follow-up date is never labeled overdue."
              action={
                <Link className="btn btn-secondary" to="/leads">
                  Review seller leads <ArrowRight size={15} />
                </Link>
              }
            />
          ) : (
            <>
              {data.data.sections[section].map((item, i) => (
                <TaskCard
                  key={item.lead.id + ":" + (item.followup?.id || i)}
                  item={item}
                  onAction={(f, mode) => setSelected({ f, mode })}
                />
              ))}
              <Pagination
                page={page}
                pageSize={20}
                total={data.data.counts[section]}
                onChange={(p) => setParams({ section, page: String(p) })}
              />
            </>
          )}
        </section>
      </div>
      {selected && (
        <FollowupDialog
          followup={selected.f}
          mode={selected.mode}
          onClose={() => setSelected(null)}
        />
      )}
      {add && <ChooseLeadForTask onClose={() => setAdd(false)} />}
    </>
  );
}
function TaskCard({
  item,
  onAction,
}: {
  item: QueueItem;
  onAction: (f: Followup, mode: "complete" | "reschedule" | "cancel") => void;
}) {
  const l = item.lead;
  return (
    <article className={`task-card ${item.priority >= 75 ? "task-high" : ""}`}>
      <div className="task-card-heading">
        <div className="row">
          <span className="seller-avatar color-1">
            {(l.full_name || "?")
              .split(" ")
              .slice(0, 2)
              .map((n) => n[0])
              .join("")}
          </span>
          <div>
            <Link className="seller-name" to={`/leads/${l.id}`}>
              {l.full_name || "Owner identity unknown"}
            </Link>
            <p>
              {l.properties[0]?.street_address ||
                "Property address not recorded"}
              {l.properties[0]?.state ? `, ${l.properties[0].state}` : ""}
            </p>
          </div>
        </div>
        <div className="row wrap">
          <StageBadge code={l.stage_code} />
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
        </div>
      </div>
      <div className="task-metadata">
        <span>
          Phone <strong>{l.primary_phone || "Missing"}</strong>
        </span>
        <span>
          Last contact{" "}
          <strong>
            <Timestamp value={l.last_contact_at} dateOnly />
          </strong>
        </span>
        <span>
          Due{" "}
          <strong className={item.followup?.due_at ? "" : "muted"}>
            {item.followup?.due_at ? (
              <Timestamp value={item.followup.due_at} />
            ) : item.followup ? (
              "Unscheduled"
            ) : (
              "No date inferred"
            )}
          </strong>
        </span>
      </div>
      <div className="task-context">
        <div>
          <span className="mini-label">WHY IT’S HERE</span>
          <p>{item.reason}</p>
        </div>
        <div>
          <span className="mini-label">SUGGESTED NEXT ACTION</span>
          <p>{item.suggested_action}</p>
        </div>
      </div>
      {item.last_activity && (
        <details className="task-activity">
          <summary>
            Last available activity · {item.last_activity.source} · #
            {item.last_activity.id}
          </summary>
          <p>{item.last_activity.summary}</p>
        </details>
      )}
      <div className="task-evidence">
        <span>{item.evidence_quality}</span>
        {item.priority_factors.length > 0 && (
          <details>
            <summary>Why this priority?</summary>
            {item.priority_factors.map((f) => (
              <p key={f}>{f}</p>
            ))}
          </details>
        )}
      </div>
      <div className="task-card-actions">
        <div className="row wrap">
          <Link to={`/leads/${l.id}`} className="btn btn-secondary">
            Open profile <ChevronRight size={14} />
          </Link>
          <Link
            to={`/leads/${l.id}?view=intelligence`}
            className="btn btn-ghost"
          >
            <MessageSquareText size={15} />
            {item.draft_available ? "Review draft" : "Review draft eligibility"}
          </Link>
        </div>
        {item.followup && (
          <div className="row">
            <Button
              variant="ghost"
              onClick={() => onAction(item.followup!, "reschedule")}
            >
              <Clock3 size={14} />
              Reschedule
            </Button>
            <Button
              variant="secondary"
              onClick={() => onAction(item.followup!, "complete")}
            >
              <Check size={15} />
              Complete
            </Button>
            <button
              className="icon-button"
              aria-label="Cancel task"
              onClick={() => onAction(item.followup!, "cancel")}
            >
              <X size={16} />
            </button>
          </div>
        )}
      </div>
      {l.restriction_status === "unknown" && (
        <div className="task-permission">
          <RestrictionBadge status={l.restriction_status} />
          <span>Review restrictions before any outreach.</span>
        </div>
      )}
    </article>
  );
}
function ChooseLeadForTask({ onClose }: { onClose: () => void }) {
  const [search, setSearch] = useState("");
  const [leadId, setLeadId] = useState<number | null>(null);
  const leads = useData<LeadPage>(
    "lead-picker",
    "/leads?page_size=20&search=" + encodeURIComponent(search),
  );
  return leadId ? (
    <FollowupCreate leadId={leadId} onClose={onClose} />
  ) : (
    <Modal
      title="Choose a seller lead"
      subtitle="Create a local, human-managed follow-up."
      onClose={onClose}
    >
      <Field label="Search sellers">
        <div className="search-input">
          <Search size={16} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Name, property or phone"
          />
        </div>
      </Field>
      <div className="lead-picker">
        {leads.data?.items.map((l) => (
          <button key={l.id} onClick={() => setLeadId(l.id)}>
            <div>
              <strong>{l.full_name || "Owner identity unknown"}</strong>
              <span>
                {l.properties[0]?.street_address || "No property recorded"}
              </span>
            </div>
            <ChevronRight size={16} />
          </button>
        ))}
        {leads.data?.items.length === 0 && (
          <Empty
            title="No sellers found"
            description="Import a seller list first."
          />
        )}
      </div>
    </Modal>
  );
}
