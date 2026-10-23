const BASE = "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body.detail || JSON.stringify(body);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  return handle<T>(res);
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return handle<T>(res);
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handle<T>(res);
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  return handle<T>(res);
}

export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "POST", body: formData });
  return handle<T>(res);
}

export function qs(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "" || value === false) return;
    if (Array.isArray(value)) {
      value.forEach((v) => search.append(key, String(v)));
    } else {
      search.set(key, String(value));
    }
  });
  const str = search.toString();
  return str ? `?${str}` : "";
}

// --------------------------------------------------------------------------- #
// Types (mirror the backend payloads the UI consumes)
// --------------------------------------------------------------------------- #
export interface PropertyInfo {
  id?: string;
  formatted_address?: string | null;
  address_line1?: string | null;
  city?: string | null;
  state?: string | null;
  zip_code?: string | null;
  property_type?: string | null;
  county?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  lot_acres?: number | null;
  asking_price?: number | null;
  estimated_value?: number | null;
  repair_estimate?: number | null;
  bedrooms?: number | null;
  bathrooms?: number | null;
  square_footage?: number | null;
  year_built?: number | null;
  extra?: Record<string, unknown> | null;
}

export interface CallPlan {
  id: string;
  lead_id: string;
  opener?: string | null;
  talking_points: { text: string; used: boolean }[];
  questions: { text: string; asked: boolean; required: boolean }[];
  do_not_say: string[];
  context_used?: { type: string; value?: string; id?: string }[];
  refusal_reason?: string | null;
  engine: string;
  model?: string | null;
  created_at?: string | null;
}

export interface CompsBrief {
  subject: {
    address?: string;
    city?: string | null;
    state?: string | null;
    zip?: string | null;
    county?: string | null;
    property_type?: string | null;
    beds?: number | null;
    baths?: number | null;
    sqft?: number | null;
    year_built?: number | null;
    lot_acres?: number | null;
    latitude?: number | null;
    longitude?: number | null;
  } | null;
  reason?: string;
  criteria: {
    beds_min?: number | null;
    beds_max?: number | null;
    baths_min?: number | null;
    baths_max?: number | null;
    sqft_min?: number | null;
    sqft_max?: number | null;
    price_min?: number | null;
    price_max?: number | null;
    sold_within_months?: number;
    radius?: string;
    property_type?: string | null;
    min_comps?: number;
  };
  value_refs: { label: string; value: number; source: string }[];
  links: Record<string, string>;
  comps: unknown[];
  notes: string;
  provenance?: string;
}

export interface MissingField {
  field: string;
  label: string;
  severity: string;
}

export interface Lead {
  id: string;
  external_id?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  full_name: string;
  primary_phone?: string | null;
  email?: string | null;
  lead_source?: string | null;
  original_creation_date?: string | null;
  pipeline_stage: string;
  pipeline_stage_label: string;
  source_status?: string | null;
  contact_status: string;
  assigned_manager?: string | null;
  last_contact_at?: string | null;
  next_followup_at?: string | null;
  do_not_contact: boolean;
  is_hot_lead?: boolean;
  tags?: string[];
  notes?: string | null;
  origin: string;
  created_at?: string | null;
  updated_at?: string | null;
  last_synced_at?: string | null;
  property?: PropertyInfo | null;
  missing_fields?: MissingField[];
  has_critical_missing?: boolean;
  activity_count?: number;
  open_followup_count?: number;
}

export interface LeadDetail extends Lead {
  activities: Activity[];
  appointments: Appointment[];
  followups: Followup[];
  insights: Insight[];
  drafts: Draft[];
  call_plan?: CallPlan | null;
  timeline: TimelineItem[];
  resimpli_url?: string | null;
}

export interface Activity {
  id: string;
  activity_type?: string | null;
  direction?: string | null;
  outcome?: string | null;
  occurred_at?: string | null;
  source: string;
  summary?: string | null;
  detail?: string | null;
  external_id?: string | null;
}

export interface Appointment {
  id: string;
  external_id?: string | null;
  scheduled_at?: string | null;
  status: string;
  appointment_type?: string | null;
  notes?: string | null;
  source: string;
  lead?: { id?: string; name?: string; phone?: string; stage?: string; property_address?: string };
  is_today?: boolean;
}

export interface Followup {
  id: string;
  lead_id: string;
  due_at?: string | null;
  priority: number;
  reason?: string | null;
  suggested_next_action?: string | null;
  status: string;
  completed_at?: string | null;
  completion_outcome?: string | null;
  completion_notes?: string | null;
  creation_source: string;
  ai_suggested: boolean;
  lead?: { id?: string; name?: string; phone?: string; stage?: string; property_address?: string; do_not_contact?: boolean };
}

export interface Insight {
  id: string;
  summary?: string | null;
  seller_motivation?: string | null;
  urgency_indicators?: string[];
  price_information?: Record<string, unknown>;
  objections?: string[];
  missing_information?: string[];
  recommended_next_action?: string | null;
  suggested_followup_at?: string | null;
  evidence?: { ref?: string; quote?: string }[];
  confidence?: string | null;
  engine: string;
  model?: string | null;
  created_at?: string | null;
}

export interface Draft {
  id: string;
  channel_hint: string;
  body: string;
  edited_body?: string | null;
  context_used?: { type: string; value?: string; id?: string }[];
  refusal_reason?: string | null;
  engine: string;
  model?: string | null;
  created_at?: string | null;
}

export interface TimelineItem {
  kind: "activity" | "followup" | "appointment";
  occurred_at?: string | null;
  source: string;
  data: Record<string, unknown>;
}

export interface Tile {
  label: string;
  count: number;
  filter: Record<string, unknown>;
}

export interface Dashboard {
  generated_at: string;
  timezone: string;
  today: string;
  total_leads: number;
  empty: boolean;
  tiles: Record<string, Tile>;
  stages: { key: string; label: string; count: number; filter: Record<string, unknown>; color: string }[];
  contact_statuses: { key: string; label: string; count: number; filter: Record<string, unknown> }[];
  followups: Record<string, number | null>;
  appointments: Record<string, number | null>;
  pipeline: Record<string, unknown>;
  breakdowns: {
    by_source: { value: string; count: number; filter: Record<string, unknown> }[];
    by_manager: { value: string; count: number; filter: Record<string, unknown> }[];
    by_state: { value: string; count: number; filter: Record<string, unknown> }[];
  };
  recent_activity: {
    id: string;
    lead_id?: string;
    lead_name?: string;
    activity_type?: string;
    outcome?: string;
    summary?: string;
    source?: string;
    occurred_at?: string;
  }[];
  sync: {
    health: string;
    last_success?: Record<string, unknown> | null;
    mock_mode: boolean;
    data_is_live: boolean;
    api_key_configured: boolean;
  };
  ai: { available: boolean; message: string; engine: string; model_in_use?: string | null };
}

export interface WorkTask {
  lead_id: string;
  seller_name: string;
  phone?: string | null;
  email?: string | null;
  property_address?: string | null;
  stage: string;
  contact_status: string;
  last_contact_at?: string | null;
  last_activity_summary?: string | null;
  next_followup_at?: string | null;
  do_not_contact: boolean;
  reason: string;
  suggested_next_action: string;
  priority: number;
  confidence: string;
  evidence: string[];
  missing_fields: string[];
}

export interface WorkQueue {
  total_tasks: number;
  today: string;
  sections: { key: string; label: string; tasks: WorkTask[] }[];
  rules: Record<string, unknown>;
}

export interface SyncStatus {
  health: string;
  mock_mode: boolean;
  api_key_configured: boolean;
  last_run?: Record<string, unknown> | null;
  last_success?: Record<string, unknown> | null;
  leads_in_database: number;
  leads_ever_synced: number;
  data_is_live: boolean;
  scheduler: { enabled: boolean; interval_minutes: number; last_job_at?: string | null; last_job_result?: string | null; last_error?: string | null };
  rate_limit_per_minute: number;
  interval_minutes: number;
}

export interface ImportInspection {
  filename: string;
  sheets: string[];
  active_sheet?: string | null;
  headers: string[];
  row_count: number;
  sample_rows: Record<string, unknown>[];
  auto_mapping: Record<string, string | null>;
  unmapped_headers: string[];
  checksum: string;
  stored_path: string;
  field_catalogue: { key: string; label: string }[];
  error?: string | null;
}

export interface ImportPreview {
  batch: Record<string, unknown> & { id: string };
  counts: Record<string, number>;
  missing?: { phone: number; email: number; address: number; name: number };
  already_imported_file: boolean;
  previous_batch_id?: string;
  sample: {
    row_number: number;
    status: string;
    reason?: string;
    warnings: string[];
    name?: string;
    phone?: string;
    email?: string;
    address?: string;
  }[];
}

export interface AiMapResult {
  mapping: Record<string, string | null>;
  engine: string;
  error: string | null;
  mapped_fields: number;
  unmapped_headers: string[];
  unmapped_fields: string[];
}

export interface ExternalConfig {
  ids: Record<string, string>;
  source: string;
  available: boolean;
}

export interface CommitResult {
  imported: number;
  failed: number;
  skipped: number;
  errors: string[];
  external_enabled: boolean;
  external: {
    enabled: boolean;
    pushed: number;
    failed: number;
    skipped_no_phone: number;
    errors: string[];
    ids: Record<string, string> | null;
  };
}

export interface ImportBatch {
  id: string;
  filename: string;
  status: string;
  total_rows: number;
  new_count: number;
  duplicate_count: number;
  warning_count: number;
  rejected_count: number;
  imported_count: number;
  failed_count: number;
  created_at?: string;
  finished_at?: string;
  record_status_counts?: Record<string, number>;
  records?: Record<string, unknown>[];
}

export interface ReferenceData {
  stages: { key: string; label: string; order: number; color: string }[];
  contact_outcomes: { key: string; label: string }[];
  completion_outcomes: string[];
  sources: string[];
  managers: string[];
}

export interface AiStatus {
  available: boolean;
  configured_model: string;
  model_in_use?: string | null;
  models: string[];
  base_url: string;
  error?: string | null;
  engine: string;
  message: string;
  disclaimer: string;
  groq?: { configured: boolean; model: string; base_url: string };
}

export interface BatchProgress {
  running: boolean;
  total: number;
  done: number;
  groq: number;
  rules: number;
  skipped: number;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  already_running?: boolean;
}

export const STAGE_COLORS: Record<string, string> = {
  new: "bg-slate-100 text-slate-700",
  not_contacted: "bg-gray-100 text-gray-700",
  attempting_contact: "bg-amber-100 text-amber-800",
  contacted: "bg-blue-100 text-blue-800",
  qualified: "bg-cyan-100 text-cyan-800",
  follow_up: "bg-indigo-100 text-indigo-800",
  appointment_set: "bg-violet-100 text-violet-800",
  offer_made: "bg-purple-100 text-purple-800",
  negotiation: "bg-fuchsia-100 text-fuchsia-800",
  contract_sent: "bg-pink-100 text-pink-800",
  under_contract: "bg-emerald-100 text-emerald-800",
  closed: "bg-green-100 text-green-800",
  nurture: "bg-teal-100 text-teal-800",
  dead: "bg-red-100 text-red-800",
};

export function stageBadge(stage: string): string {
  return STAGE_COLORS[stage] || "bg-ink-100 text-ink-700";
}

export function fmtDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function fmtDateTime(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function isOverdue(value?: string | null): boolean {
  if (!value) return false;
  const d = new Date(value).getTime();
  return !Number.isNaN(d) && d < Date.now();
}
