import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  CalendarClock,
  Check,
  CheckCircle2,
  ClipboardCopy,
  Clock3,
  MessageSquareText,
  Phone,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { api, post, dateTime } from "../api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Loading,
  PageHeader,
  RestrictionBadge,
  StageBadge,
  useAction,
  useWorkspace,
} from "../components";
import type { FollowupWorkbench, FollowupWorkbenchItem } from "../types";

const PAGE_SIZE = 30;

type Filter = "all" | "ready" | "scheduled" | "restricted";

export default function FollowupHub() {
  const [search, setSearch] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<Filter>("ready");
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearchTerm(search.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const path = `/followups/workbench?page=${page}&page_size=${PAGE_SIZE}&search=${encodeURIComponent(searchTerm)}`;
  const data = useQuery({
    queryKey: ["followup-workbench", path],
    queryFn: () => api<FollowupWorkbench>(path),
  });

  const shown = useMemo(() => {
    const items = data.data?.items || [];
    if (filter === "all") return items;
    if (filter === "restricted")
      return items.filter((item) => !canPrepare(item));
    if (filter === "scheduled")
      return items.filter((item) => item.followup && !isDue(item.followup.due_at));
    return items.filter((item) => canPrepare(item) && (!item.followup || isDue(item.followup.due_at)));
  }, [data.data, filter]);

  return (
    <>
      <PageHeader
        eyebrow="HUMAN-REVIEWED SELLER OUTREACH"
        title="Follow-up workspace"
        description="One place for every lead: review the last recorded context, prepare a personal draft, copy it, and log the send yourself."
        actions={
          <Link className="btn btn-secondary" to="/daily-queue">
            <CalendarClock size={16} /> Daily work queue
          </Link>
        }
      />

      <StrategyPanel />

      <div className="followup-hub-controls">
        <div className="followup-search">
          <Search size={18} aria-hidden="true" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label="Search all leads"
            placeholder="Search name, phone, email or source"
          />
        </div>
        <div className="followup-filter-tabs" role="tablist" aria-label="Filter follow-ups">
          {([
            ["ready", "Ready / due"],
            ["scheduled", "Scheduled later"],
            ["restricted", "Needs review"],
            ["all", "All leads"],
          ] as [Filter, string][]).map(([key, label]) => (
            <button
              type="button"
              role="tab"
              aria-selected={filter === key}
              className={filter === key ? "active" : ""}
              key={key}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="followup-total">
          {data.data?.total ?? 0} leads · page {page} of {Math.max(1, Math.ceil((data.data?.total ?? 0) / PAGE_SIZE))}
        </span>
      </div>

      <div className="followup-hub-safety">
        <ShieldCheck size={18} />
        <span>
          <strong>Nothing is sent automatically.</strong> Drafts use recorded activity only. Notes are summaries, not guaranteed verbatim conversation transcripts; review and edit before copying.
        </span>
      </div>

      {data.isPending ? (
        <Loading />
      ) : data.isError ? (
        <ErrorState error={data.error} retry={() => data.refetch()} />
      ) : shown.length ? (
        <div className="followup-hub-list">
          {shown.map((item) => <FollowupCard item={item} key={item.lead.id} />)}
        </div>
      ) : (
        <Empty
          title={filter === "ready" ? "Nothing is due on this page" : "No leads match this view"}
          description={filter === "ready" ? "Future-dated tasks stay in Scheduled later until their due date. Switch to All leads to review every record." : "Try another filter or search term."}
        />
      )}

      {!!data.data?.total && (
        <div className="followup-pagination">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>
            Previous page
          </Button>
          <span>Showing {shown.length} of {data.data.total} matching leads on page {page}</span>
          <Button variant="secondary" disabled={page * PAGE_SIZE >= data.data.total} onClick={() => setPage((value) => value + 1)}>
            Next page
          </Button>
        </div>
      )}
    </>
  );
}

function StrategyPanel() {
  return (
    <details className="followup-strategy" open>
      <summary><Sparkles size={18} /> Global follow-up strategy</summary>
      <div className="followup-strategy-grid">
        <div><b>1 · Respond to context</b><p>Honor an explicit callback request or timing the seller gave. For a connected call, reference the conversation without inventing what was said.</p></div>
        <div><b>2 · Calm cadence</b><p>After you mark a message sent, the next review task is scheduled in 2, 4, 7, 14, 30, then 60 days. It is a reminder only; the app never sends.</p></div>
        <div><b>3 · Keep it useful</b><p>Every touch should make a simple next step easy: answer a question, arrange a call, or let the seller choose a better time.</p></div>
        <div><b>4 · Stop when asked</b><p>Respect Do Not Contact, opt-outs, consent and applicable channel/time restrictions. Stop immediately after an opt-out or clear refusal.</p></div>
      </div>
      <p className="followup-strategy-footnote">This is a practical workflow, not legal advice. Follow your approved compliance process and only contact sellers through permitted channels.</p>
    </details>
  );
}

function FollowupCard({ item }: { item: FollowupWorkbenchItem }) {
  const { toast } = useWorkspace();
  const action = useAction();
  const [message, setMessage] = useState(() => createMessage(item));
  const [copied, setCopied] = useState<"phone" | "message" | "">("");
  const lead = item.lead;
  const phone = lead.phones?.find((entry) => entry.is_primary)?.phone || lead.primary_phone || lead.phone2 || lead.phone3 || lead.phone4 || lead.phone5 || "";
  const eligible = canPrepare(item);

  useEffect(() => {
    setMessage(createMessage(item));
  }, [item]);

  async function copy(value: string, type: "phone" | "message") {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(type);
      window.setTimeout(() => setCopied(""), 1800);
    } catch {
      toast("Clipboard access was blocked by this browser", "error");
    }
  }

  async function markSent() {
    if (!window.confirm("Have you already sent this message yourself? The app will only record it and schedule a reminder.")) return;
    const result = await action.run(
      () => post(`/followups/workbench/${lead.id}/sent`, { message, confirm: true }),
      "Marked as sent. The next review reminder was scheduled.",
    );
    if (result) setCopied("");
  }

  return (
    <article className={`followup-lead-card ${!eligible ? "blocked" : ""}`}>
      <header className="followup-lead-head">
        <div className="followup-lead-title">
          <div className="followup-avatar">{(lead.full_name || "?").slice(0, 1).toUpperCase()}</div>
          <div>
            <Link to={`/leads/${lead.id}`} className="followup-lead-name">{lead.full_name || "Owner identity unknown"}</Link>
            <div className="followup-address">{lead.properties[0]?.street_address || "Property address not recorded"}{lead.properties[0]?.city ? ` · ${lead.properties[0].city}` : ""}{lead.properties[0]?.state ? `, ${lead.properties[0].state}` : ""}</div>
          </div>
        </div>
        <div className="row wrap">
          <StageBadge code={lead.stage_code} />
          <RestrictionBadge status={lead.restriction_status} />
          {item.sent_count > 0 && <Badge tone="green">{item.sent_count} logged touch{item.sent_count === 1 ? "" : "es"}</Badge>}
        </div>
      </header>

      <div className="followup-contact-row">
        <div className="followup-phone">
          <Phone size={16} />
          <strong>{phone || "No phone recorded"}</strong>
          <Button variant="secondary" disabled={!phone} onClick={() => void copy(phone, "phone")}>
            {copied === "phone" ? <Check size={15} /> : <ClipboardCopy size={15} />}
            {copied === "phone" ? "Copied" : "Copy number"}
          </Button>
        </div>
        <div className="followup-next-date">
          {item.followup?.due_at && !isDue(item.followup.due_at) ? <><Clock3 size={15} /> Next reminder · {dateTime(item.followup.due_at)}</> : <><MessageSquareText size={15} /> {item.followup ? "Reminder is due" : "No follow-up is scheduled"}</>}
        </div>
      </div>

      <section className="followup-context">
        <div className="followup-section-label">LATEST RECORDED CONTEXT</div>
        {item.last_activity ? (
          <div className="followup-context-text">
            <span>{item.last_activity.activity_type.replaceAll("_", " ")} · {item.last_activity.occurred_at ? dateTime(item.last_activity.occurred_at) : "date not recorded"}{item.last_activity.outcome ? ` · ${item.last_activity.outcome}` : ""}</span>
            <p>{item.last_activity.summary || "No activity summary was recorded."}</p>
          </div>
        ) : <p className="muted">No conversation/activity has been recorded yet. The suggested draft is intentionally generic.</p>}
      </section>

      {!eligible ? (
        <div className="followup-blocker"><ShieldAlert size={18} /><div><strong>Outreach draft blocked</strong><p>{lead.do_not_contact ? "This lead is marked Do Not Contact." : lead.restriction_status !== "reviewed_clear" ? "Contact permission is not marked reviewed and clear." : lead.needs_skip_trace ? "Complete skip trace before outreach." : "A phone number is needed for this workflow."} Review the lead profile and your approved contact rules.</p></div></div>
      ) : (
        <section className="followup-message-section">
          <div className="followup-message-title"><div><div className="followup-section-label">SUGGESTED MESSAGE · EDIT BEFORE USE</div><span>{item.sent_count === 0 ? "First message: includes your name and role" : "Later touch: company included, your name omitted"}</span></div><Badge tone="purple">{item.last_activity ? "Context-aware draft" : "Starter draft"}</Badge></div>
          <textarea aria-label={`Suggested follow-up message for ${lead.full_name}`} value={message} onChange={(event) => setMessage(event.target.value)} rows={7} />
          <div className="followup-message-actions">
            <Button variant="secondary" disabled={!message.trim()} onClick={() => void copy(message, "message")}>
              {copied === "message" ? <Check size={16} /> : <ClipboardCopy size={16} />}
              {copied === "message" ? "Message copied" : "Copy message"}
            </Button>
            <Button busy={action.busy} disabled={!message.trim()} onClick={() => void markSent()}>
              <CheckCircle2 size={16} /> Mark sent · remove from due
            </Button>
          </div>
          {action.error && <p className="followup-error" role="alert">{action.error}</p>}
        </section>
      )}
    </article>
  );
}

function createMessage(item: FollowupWorkbenchItem) {
  const lead = item.lead;
  const firstName = lead.first_name?.trim() || lead.full_name?.trim().split(/\s+/)[0] || "there";
  const activity = item.last_activity;
  const opening = activity?.outcome === "Callback Requested"
    ? "You had asked me to follow up, so I wanted to check whether now is a good time to reconnect."
    : activity?.source_metadata?.followup_hub_touch === true || activity?.direction === "outbound"
      ? "I’m checking back on my last message. Would you prefer a quick call or a text reply?"
      : activity?.direction === "inbound"
        ? "Thanks for getting back to me. I wanted to follow up and see what would be most helpful for you."
        : activity?.activity_type === "call" && activity.outcome === "Connected"
          ? "I’m following up on our recent call. Do you have any questions I can help answer?"
          : "I’m reaching out to see whether this is a good time to talk about the property.";
  const introduction = item.sent_count === 0
    ? "I’m Jason Wade, the Acquisition Manager with GreenSeedTX LLC."
    : "I’m with GreenSeedTX LLC.";
  return `Hi ${firstName},\n\n${introduction} ${opening}`;
}

function canPrepare(item: FollowupWorkbenchItem) {
  const lead = item.lead;
  const hasPhone = Boolean(lead.primary_phone || lead.phone2 || lead.phone3 || lead.phone4 || lead.phone5 || lead.phones?.length);
  return !lead.do_not_contact && lead.restriction_status === "reviewed_clear" && !lead.needs_skip_trace && hasPhone;
}

function isDue(dueAt: string | null | undefined) {
  return !dueAt || new Date(dueAt).getTime() <= Date.now();
}
