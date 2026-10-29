export interface Stage {
  code: string;
  label: string;
  position: number;
  active: boolean;
}
export interface Meta {
  stages: Stage[];
  outcomes: string[];
  import_fields: Record<string, string>;
  timezone: string;
  mode: string;
  sources: string[];
  managers: string[];
  communication: string;
}
export interface Property {
  id: number;
  external_id: string | null;
  street_address: string | null;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  property_type: string | null;
  bedrooms: number | null;
  bathrooms: number | null;
  square_feet: number | null;
  year_built: number | null;
  asking_price: number | null;
  estimated_value: number | null;
  repair_estimate: number | null;
  property_metadata: Record<string, unknown>;
}
export interface Activity {
  id: number;
  external_id: string | null;
  lead_id: number;
  activity_type: string;
  direction: string | null;
  outcome: string | null;
  occurred_at: string | null;
  recorded_at: string;
  source: string;
  summary: string;
  source_metadata: Record<string, unknown>;
}
export interface Followup {
  id: number;
  lead_id: number;
  property_id: number | null;
  due_at: string | null;
  priority: number;
  reason: string;
  suggested_action: string | null;
  status: string;
  completed_at: string | null;
  completion_outcome: string | null;
  creation_source: string;
  ai_suggested: boolean;
  created_at: string;
}
export interface Appointment {
  id: number;
  external_id: string | null;
  lead_id: number;
  starts_at: string;
  status: string;
  source_status: string | null;
  local_result: string | null;
  notes: string | null;
  source: string;
  seller?: string;
  restriction_status?: string;
}
export interface Evidence {
  ref: string;
  text: string;
  outcome?: string | null;
  timestamp?: string | null;
}
export interface Fact {
  value: string | number | null;
  category: string;
  evidence: string[];
  quote?: string;
}
export interface Insight {
  id: number;
  lead_id: number;
  seller?: string;
  summary: string;
  facts: Record<string, Fact>;
  conflicts: string[];
  missing_information: string[];
  recommended_action: string;
  suggested_timing: string | null;
  model_id: string;
  confidence: string;
  evidence: Evidence[];
  analysis_at: string;
  context_hash: string;
  stale?: boolean;
  cached?: boolean;
  warning?: string | null;
}
export interface Draft {
  id: number;
  lead_id: number;
  body: string;
  context: Evidence[];
  model_id: string;
  created_at: string;
  updated_at: string;
  kind?: "relationship" | "cold";
  message_id?: number;
  template_id?: number | null;
  variant?: string | null;
  status?: string;
  validator_result?: { ok: boolean; reasons: string[] };
  why_this_template?: string[];
  warnings?: string[];
  category?: string;
}

export interface MessageDraft {
  id: number;
  lead_id: number;
  body: string;
  status: string;
  template_id: number | null;
  variant: string | null;
  validator_result: { ok: boolean; reasons: string[] };
  why_this_template: string[];
  created_at: string | null;
  lead_name?: string | null;
  lead_external_id?: string | null;
  heat?: string | null;
  score?: number | null;
  outreach_mode?: string | null;
}

export interface TemplateSelection {
  category: string;
  label: string;
  tags: string[];
  reason: string;
  variant: string;
  variants_available: string[];
  outreach_mode: string;
  preview: string | null;
  blockers: string[];
  selectable: boolean;
  never_sent: boolean;
}

export interface ReplyScan {
  scanned: number;
  classified: number;
  needs_human: number;
  skipped_empty: number;
  already_seen: number;
  items: { lead_id: number; classification: string; confidence: number }[];
  never_sent: boolean;
}

export interface LeadSequence {
  lead_id: number;
  active: boolean;
  status: string;
  current_step: number;
  total_steps: number;
  next_due_at: string | null;
  stop_reason: string | null;
  started_at: string | null;
  cadence_days: number[];
  steps: { day_offset: number; category: string }[];
  never_sent: boolean;
}

export interface SequenceSummary {
  active: number;
  due_today: number;
  cadence_days: number[];
  runner_hour_utc: number;
  runner_enabled: boolean;
  never_sent: boolean;
}

export interface SuggestedAction {
  id: number;
  lead_id: number;
  lead_name: string | null;
  kind: string;
  classification: string;
  confidence: number;
  evidence: string | null;
  payload: Record<string, unknown>;
  status: string;
  requires_confirmation: boolean;
  created_at: string;
}

export interface BriefingData {
  generated_at: string;
  compliance_first: {
    id: number;
    lead_id: number;
    lead_name: string | null;
    classification: string;
    confidence: number;
    evidence: string | null;
    label: string;
  }[];
  replies_needing_action: {
    lead_id: number;
    name: string | null;
    classification: string;
    confidence: number;
    evidence: string | null;
    suggestion_id: number;
    kind: string;
    needs_review: boolean;
    received_at: string | null;
  }[];
  followups_due: { lead_id: number; name: string; due_at: string | null }[];
  drafts_awaiting_approval: number;
  drafts_failing_validation: { id: number; lead_id: number; reasons: string[] }[];
  leads_needing_skip_trace: number;
  skip_trace_leads: {
    lead_id: number;
    address: string | null;
    heat: string | null;
    score: number | null;
    priority_tier: string | null;
  }[];
  stalled_leads: number;
  stalled_window_days: number;
  sync_conflicts: number;
  backups: {
    last_backup_at: string | null;
    last_backup_file: string | null;
    last_backup_reason: string | null;
    second_folder: string | null;
    second_folder_ok: boolean | null;
    second_folder_detail: string | null;
    second_folder_checked_at: string | null;
  };
  last_backup: string | null;
  never_sent: boolean;
}
export interface Audit {
  id: number;
  action: string;
  details: Record<string, unknown>;
  created_at: string;
  actor: string;
}
export interface Lead {
  id: number;
  external_id: string | null;
  first_name: string | null;
  last_name: string | null;
  full_name: string;
  primary_phone: string | null;
  primary_phone_type: string | null;
  phone2: string | null;
  phone2_type: string | null;
  phone3: string | null;
  phone3_type: string | null;
  phone4: string | null;
  phone4_type: string | null;
  phone5: string | null;
  phone5_type: string | null;
  phones: { id: number; phone: string; phone_normalized: string | null; phone_type: string | null; is_primary: boolean; position: number }[];
  email: string | null;
  lead_source: string | null;
  original_created_at: string | null;
  stage_code: string;
  source_status: string | null;
  contact_status: string;
  contact_outcome: string | null;
  assigned_manager: string | null;
  last_contact_at: string | null;
  next_followup_at: string | null;
  source_kind: string;
  created_at: string;
  updated_at: string;
  synced_at: string | null;
  source_do_not_contact: boolean | null;
  local_do_not_contact: boolean;
  local_stage_override: boolean;
  restriction_status: string;
  restriction_evidence: string | null;
  do_not_contact: boolean;
  properties: Property[];
  missing_information: string[];
  // Data Syndicate context (internal only; never appears in outgoing text).
  // Optional so an older payload or a test fixture stays assignable.
  recorded_date?: string | null;
  score?: number | null;
  heat?: "NONE" | "HOT" | "VERY_HOT" | null;
  equity_pct?: number | null;
  county?: string | null;
  lead_type?: string | null;
  priority_tier?: string | null;
  priority_rank?: number | null;
  needs_skip_trace?: boolean;
  outreach_status?: string;
  ds_flags?: Record<string, boolean>;
  ds_flags_raw?: string | null;
  ds_extra_flags?: string[];
  ds_compatible_offers?: string[];
  outreach_mode?: "relationship" | "cold";
  user_edited_fields?: string[];
  import_batch_id?: string | null;
}
export interface LeadProfile extends Lead {
  activities: Activity[];
  followups: Followup[];
  appointments: Appointment[];
  audit: Audit[];
  source_data: Record<string, unknown>;
  insight: Insight | null;
  insight_stale: boolean;
  draft: Draft | null;
  draft_stale?: boolean;
  external_url: string | null;
  source_notice: string;
  stage_history: {
    from_stage: string | null;
    to_stage: string;
    changed_at: string;
    source: string;
  }[];
}
export interface LeadPage {
  items: Lead[];
  total: number;
  page: number;
  page_size: number;
}
export interface QueueItem {
  lead: Lead;
  followup: Followup | null;
  last_activity: Activity | null;
  reason: string;
  suggested_action: string;
  priority: number;
  priority_factors: string[];
  evidence_quality: string;
  draft_available: boolean;
}
export interface Queue {
  sections: Record<string, QueueItem[]>;
  counts: Record<string, number>;
  labels: Record<string, string>;
  rules: Record<string, number>;
  timezone: string;
  excluded_dnc: number;
  definition: string;
}
export interface Breakdown {
  label: string;
  value: number;
  code?: string;
}
export interface DashboardData {
  metrics: { key: string; label: string; value: number }[];
  breakdowns: Record<string, Breakdown[]>;
  recent_activity: {
    id: number;
    lead_id: number;
    seller: string;
    summary: string;
    source: string;
    outcome: string | null;
    recorded_at: string;
    occurred_at: string | null;
  }[];
  timezone: string;
  definitions: Record<string, string>;
}
export interface SyncRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  result: string;
  mode: string;
  fetched: number;
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  errors: string[];
  resources: Record<string, number>;
}
export interface SyncState {
  runs: SyncRun[];
  health: string;
  last_success: string | null;
  last_live_success: string | null;
  mode: string;
  credentials_configured: boolean;
  adapter_verified: boolean;
  external_creation_enabled: boolean;
  scheduler: { enabled: boolean; interval_minutes: number };
  live_verified: boolean;
  notice: string;
}
export interface AIStatus {
  available: boolean;
  enabled: boolean;
  model: string | null;
  message: string;
  models?: string[];
  groq?: CloudPolicy;
}
export interface BatchRow {
  id: number;
  sheet: string;
  row_number: number;
  original: Record<string, unknown>;
  normalized: Record<string, unknown>;
  errors: string[];
  warnings: string[];
  duplicate_kind: string;
  candidates: { lead_id?: number; row_id?: number; full_name: string }[];
  resolution: string | null;
  state: string;
  lead_id: number | null;
  external_id: string | null;
  error: string | null;
}
export interface ImportBatch {
  id: number;
  filename: string;
  checksum: string;
  sheets: Record<
    string,
    {
      headers: string[];
      record_count: number;
      suggested_mapping: Record<string, string>;
    }
  >;
  row_count: number;
  state: string;
  counts: Record<string, number>;
  errors: string[];
  mapping_config: {
    mapping?: Record<string, string>;
    sheets?: string[];
    date_order?: string;
  };
  created_at: string;
  finished_at: string | null;
  repeated_file?: boolean;
  rows?: BatchRow[];
  total_rows?: number;
  page?: number;
}
export interface MappingTemplate {
  id: number;
  name: string;
  mapping: Record<string, string>;
  date_order: string;
}
export interface ReportRate {
  label: string;
  numerator: number;
  denominator: number;
  percent: number | null;
  definition: string;
}
export interface ReportsData {
  total: number;
  rates: ReportRate[];
  stages: Record<string, number>;
  volume: Record<string, number>;
  aging: Record<string, number>;
  unknown_creation_dates: number;
  stage_duration: {
    stage: string;
    average_days: number;
    observed_completed_intervals: number;
  }[];
  counts: Record<string, number>;
  limitations: string[];
}
export interface SettingsData {
  timezone: string;
  mode: string;
  stage_mapping: Record<string, string>;
  source_statuses?: {
    title: string;
    leads: number;
    stage: string;
    mapped: boolean;
  }[];
  priority_rules: Record<string, number>;
  sender_name: string;
  company_name: string;
  // The environment can pin the opener identity, in which case this screen cannot edit it.
  sender_name_locked?: boolean;
  company_name_locked?: boolean;
  identity_source?: string;
  cadence: number[];
  local_only: boolean;
  authentication_enabled: boolean;
  max_upload_mb: number;
  max_import_rows: number;
  ollama_enabled: boolean;
  ollama_model: string;
  api_key_configured: boolean;
  adapter_verified: boolean;
  external_writes: boolean;
  automatic_communication: boolean;
}

export interface CloudPolicy {
  provider: string;
  enabled: boolean;
  key_configured: boolean;
  model: string;
  daily_limit: number;
  used_today: number;
  max_output_tokens: number;
  consent_mode: string;
  external_data_flow: string;
  automatic_processing: boolean;
  automatic_communication: boolean;
  crm_writes: boolean;
  validated?: boolean;
  checked_at?: string | null;
  supported_models?: { id: string; label: string }[];
}
export interface IntegrationStatus {
  groq: CloudPolicy;
  resimpli: {
    key_configured: boolean;
    mode: string;
    adapter_verified: boolean;
    adapter_configured: boolean;
    writes_enabled: boolean;
    validated: boolean;
    checked_at: string | null;
  };
  environment_overrides: { groq: boolean; resimpli: boolean };
  secret_storage: string;
  consent_policy: string;
  automatic_communication: boolean;
}
export interface GroundedText {
  text: string;
  evidence: string[];
  quote: string | null;
}
export type CloudPurpose = "analyze" | "notes" | "draft";
export interface CloudReview {
  id: string;
  lead_id: number;
  purpose: CloudPurpose;
  provider: string;
  model_id: string;
  state: string;
  payload_hash: string;
  records: (Evidence & { label?: string })[];
  source_context_stale?: boolean;
  result: {
    constraints?: Record<string, string | boolean>;
    redactions?: number;
    truncated?: boolean;
    summary?: GroundedText;
    organized_notes?: GroundedText[];
    facts?: Record<string, Fact>;
    missing_information?: string[];
    conflicts?: GroundedText[];
    body?: string;
    draft_id?: number;
    insight_id?: number;
    review_note?: string;
    cached_from?: string;
    saved_note_id?: number;
    draft_blocked_by_current_restriction?: boolean;
  };
  usage: Record<string, number>;
  error: string | null;
  created_at: string;
  expires_at: string;
  started_at: string | null;
  completed_at: string | null;
}
