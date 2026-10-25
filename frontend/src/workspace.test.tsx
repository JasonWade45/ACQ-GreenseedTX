import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { WorkspaceContext, FollowupDialog } from "./components";
import Dashboard from "./pages/Dashboard";
import Leads from "./pages/Leads";
import LeadDetail from "./pages/LeadDetail";
import ImportsPage from "./pages/ImportsPage";
import { ReportsPage, SyncPage } from "./pages/OperationsPages";
import App from "./App";
import type { Followup, Lead, Meta } from "./types";

const meta: Meta = {
  stages: [
    { code: "new", label: "New", position: 0, active: true },
    { code: "negotiation", label: "Negotiation", position: 1, active: true },
  ],
  outcomes: ["Connected", "No Answer", "Administrative / No Contact"],
  import_fields: { full_name: "Full name", primary_phone: "Phone number" },
  timezone: "America/New_York",
  mode: "disabled",
  sources: ["Referral"],
  managers: ["Alex"],
  communication: "Draft only",
};
const lead: Lead = {
  id: 1,
  external_id: "source-1",
  first_name: "Morgan",
  last_name: "Parker",
  full_name: "Morgan Parker",
  primary_phone: "+12025550102",
  email: "morgan@example.test",
  lead_source: "Referral",
  original_created_at: "2026-01-01T12:00:00Z",
  stage_code: "new",
  source_status: "New",
  contact_status: "unknown",
  contact_outcome: null,
  assigned_manager: "Alex",
  last_contact_at: null,
  next_followup_at: null,
  source_kind: "local",
  created_at: "2026-01-01T12:00:00Z",
  updated_at: "2026-01-01T12:00:00Z",
  synced_at: null,
  source_do_not_contact: null,
  local_do_not_contact: false,
  local_stage_override: false,
  restriction_status: "unknown",
  restriction_evidence: null,
  do_not_contact: false,
  properties: [],
  missing_information: ["Property address", "Contact restriction review"],
};
const followup: Followup = {
  id: 1,
  lead_id: 1,
  property_id: null,
  due_at: null,
  priority: 50,
  reason: "Review the explicit callback",
  suggested_action: null,
  status: "pending",
  completed_at: null,
  completion_outcome: null,
  creation_source: "manual",
  ai_suggested: false,
  created_at: "2026-01-01T12:00:00Z",
};
const sync = {
  runs: [],
  health: "never",
  last_success: null,
  last_live_success: null,
  mode: "disabled",
  credentials_configured: false,
  adapter_verified: false,
  external_creation_enabled: false,
  scheduler: { enabled: false, interval_minutes: 30 },
  live_verified: false,
  notice: "No verified account connection",
};
const batch = {
  id: 1,
  filename: "legacy.csv",
  checksum: "test",
  sheets: {
    CSV: {
      headers: ["Seller", "Phone"],
      record_count: 1,
      suggested_mapping: { Seller: "full_name", Phone: "primary_phone" },
    },
  },
  row_count: 1,
  state: "previewed",
  counts: {
    new: 1,
    duplicates: 0,
    warnings: 1,
    invalid: 0,
    imported: 0,
    failed: 0,
  },
  errors: [],
  mapping_config: {
    mapping: { Seller: "full_name", Phone: "primary_phone" },
    sheets: ["CSV"],
    date_order: "reject",
  },
  created_at: "2026-01-01T12:00:00Z",
  finished_at: null,
  total_rows: 1,
  page: 1,
  rows: [
    {
      id: 1,
      sheet: "CSV",
      row_number: 2,
      original: { Seller: "Morgan Parker", Phone: "2025550102" },
      normalized: { full_name: "Morgan Parker", primary_phone: "+12025550102" },
      errors: [],
      warnings: ["Address missing"],
      duplicate_kind: "new_record",
      candidates: [],
      resolution: null,
      state: "ready",
      lead_id: null,
      external_id: null,
      error: null,
    },
  ],
};
const payloads: Record<string, unknown> = {
  "/meta": meta,
  "/auth/status": { required: false },
  "/sync": sync,
  "/dashboard": {
    metrics: [
      { key: "total", label: "Total seller leads", value: 1 },
      { key: "not_contacted", label: "No verified contact", value: 1 },
    ],
    breakdowns: {
      source: [{ label: "Referral", value: 1 }],
      state: [],
      manager: [],
      stage: [],
    },
    recent_activity: [],
    timezone: meta.timezone,
    definitions: { contact: "Verified evidence only" },
  },
  "/queue": {
    sections: {
      overdue: [],
      today: [],
      callbacks: [],
      appointments: [],
      new: [],
    },
    counts: { overdue: 0, today: 0 },
    labels: { overdue: "Overdue" },
    rules: {},
    timezone: meta.timezone,
    excluded_dnc: 0,
    definition: "Explicit dates only",
  },
  "/leads": { items: [lead], total: 1, page: 1, page_size: 25 },
  "/leads/1": {
    ...lead,
    activities: [],
    followups: [],
    appointments: [],
    audit: [],
    source_data: {},
    insight: null,
    insight_stale: false,
    draft: null,
    external_url: null,
    source_notice: "Source summaries are not transcripts",
    stage_history: [],
  },
  "/imports": [],
  "/imports/1": batch,
  "/imports/templates": [],
  "/reports": {
    total: 0,
    rates: [
      {
        label: "Recorded offer rate — all leads",
        numerator: 0,
        denominator: 0,
        percent: null,
        definition: "Observed offers ÷ all leads",
      },
    ],
    stages: {},
    volume: {},
    aging: {},
    unknown_creation_dates: 0,
    stage_duration: [],
    counts: {},
    limitations: ["Only observed data"],
  },
};
let requestMock: ReturnType<typeof vi.fn>;
function mount(content: ReactNode, entry = "/") {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <WorkspaceContext.Provider value={{ meta, toast: vi.fn() }}>
          {content}
        </WorkspaceContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  requestMock = vi.fn(async (input: string, init?: RequestInit) => {
    const path = input.replace("/api", "").split("?")[0];
    if (init?.method && init.method !== "GET")
      return new Response(JSON.stringify({ ok: true, token: "test-session" }), {
        status: 200,
      });
    return new Response(JSON.stringify(payloads[path] ?? {}), { status: 200 });
  });
  vi.stubGlobal("fetch", requestMock);
});

describe("database-backed dashboard", () => {
  it("shows a loading state before data arrives", () => {
    requestMock.mockImplementation(() => new Promise(() => {}));
    mount(<Dashboard />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading your workspace",
    );
  });
  it("loads real metric responses and links to filtered lead lists", async () => {
    mount(<Dashboard />);
    expect(
      await screen.findByRole("heading", { name: "Acquisitions overview" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Total seller leads").closest("a")).toHaveAttribute(
      "href",
      "/leads?metric=total",
    );
    expect(
      screen.getByText("A clean slate for your next move"),
    ).toBeInTheDocument();
  });
  it("displays network failure rather than fake numbers", async () => {
    requestMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "Database unavailable" }), {
        status: 503,
      }),
    );
    mount(<Dashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Database unavailable",
    );
  });
});
it("searches and filters the seller table", async () => {
  const user = userEvent.setup();
  mount(<Leads />, "/leads");
  expect(await screen.findByText("Morgan Parker")).toBeInTheDocument();
  await user.type(
    screen.getByRole("textbox", { name: "Search seller leads" }),
    "Morgan",
  );
  await waitFor(() =>
    expect(
      requestMock.mock.calls.some((c) =>
        String(c[0]).includes("search=Morgan"),
      ),
    ).toBe(true),
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Pipeline stage" }),
    "negotiation",
  );
  await waitFor(() =>
    expect(
      requestMock.mock.calls.some((c) =>
        String(c[0]).includes("stage=negotiation"),
      ),
    ).toBe(true),
  );
});
it("opens a lead profile without inventing contact history", async () => {
  mount(
    <Routes>
      <Route path="/leads/:id" element={<LeadDetail />} />
    </Routes>,
    "/leads/1",
  );
  expect(
    await screen.findByRole("heading", { name: "Morgan Parker" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Contact eligibility is unknown."),
  ).toBeInTheDocument();
  expect(screen.getByText("No verified contact evidence")).toBeInTheDocument();
});
it("blocks draft preparation for unknown contact restrictions", async () => {
  const user = userEvent.setup();
  mount(
    <Routes>
      <Route path="/leads/:id" element={<LeadDetail />} />
    </Routes>,
    "/leads/1",
  );
  await screen.findByRole("heading", { name: "Morgan Parker" });
  await user.click(screen.getByRole("tab", { name: "Analysis & drafts" }));
  expect(
    screen.getByRole("button", { name: "Prepare a review-only draft" }),
  ).toBeDisabled();
});
it("renders the normalized import preview and requires explicit approval", async () => {
  const user = userEvent.setup();
  mount(<ImportsPage />, "/imports?batch=1");
  expect(
    await screen.findByRole("heading", { name: "Review normalized records" }),
  ).toBeInTheDocument();
  expect(screen.getByText("+12025550102")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Review & approve local import" }),
  ).toBeDisabled();
  await user.click(
    screen.getByRole("checkbox", { name: "Select import row 2" }),
  );
  await user.click(
    screen.getByRole("button", { name: "Review & approve local import" }),
  );
  const dialog = screen.getByRole("dialog", {
    name: "Approve this local import",
  });
  expect(
    within(dialog).getByRole("textbox", {
      name: "Type IMPORT LOCAL to confirm",
    }),
  ).toBeInTheDocument();
});
it("distinguishes a sync that has never run from a successful one", async () => {
  mount(<SyncPage />, "/sync");
  expect(await screen.findByText("Never synchronized")).toBeInTheDocument();
  expect(screen.getByText("No synchronization has run")).toBeInTheDocument();
  expect(
    screen.getByText("External lead creation is disabled"),
  ).toBeInTheDocument();
});
it("follow-up completion requires and sends only the recorded local outcome", async () => {
  const user = userEvent.setup();
  mount(
    <FollowupDialog followup={followup} mode="complete" onClose={vi.fn()} />,
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Actual outcome" }),
    "No Answer",
  );
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Confirm complete" }));
  await waitFor(() =>
    expect(
      requestMock.mock.calls.some(
        (c) => String(c[0]) === "/api/followups/1/action",
      ),
    ).toBe(true),
  );
  const call = requestMock.mock.calls.find(
    (c) => String(c[0]) === "/api/followups/1/action",
  )!;
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({
    outcome: "No Answer",
    action: "complete",
    confirm: true,
  });
  expect(
    requestMock.mock.calls.every((c) => !String(c[0]).includes("/send")),
  ).toBe(true);
});
it("reports an unavailable percentage instead of dividing by zero", async () => {
  mount(<ReportsPage />, "/reports");
  expect(
    await screen.findByText("Recorded offer rate — all leads"),
  ).toBeInTheDocument();
  expect(screen.getByText(/Not calculable/)).toBeInTheDocument();
  expect(screen.getByText("Not enough stage history")).toBeInTheDocument();
});
it("requires a workspace password when remote access authentication is enabled", async () => {
  requestMock.mockImplementation(
    async (input: string) =>
      new Response(
        JSON.stringify(input === "/api/auth/status" ? { required: true } : {}),
        { status: 200 },
      ),
  );
  mount(<App />);
  expect(
    await screen.findByRole("heading", { name: "Welcome back." }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Workspace password")).toHaveAttribute(
    "type",
    "password",
  );
});

it("requires regeneration before copying a stale source-context draft", async () => {
  const user = userEvent.setup();
  const original = requestMock.getMockImplementation()! as (
    input: string,
    init?: RequestInit,
  ) => Promise<Response>;
  requestMock.mockImplementation(async (input: string, init?: RequestInit) => {
    if (input === "/api/leads/1" && (!init?.method || init.method === "GET")) {
      return new Response(
        JSON.stringify({
          ...(payloads["/leads/1"] as object),
          source_do_not_contact: false,
          restriction_status: "reviewed_clear",
          draft_stale: true,
          draft: {
            id: 1,
            lead_id: 1,
            body: "Earlier callback draft needing fresh context review.",
            context: [],
            model_id: "review-only-template",
            created_at: "2026-01-01T12:00:00Z",
            updated_at: "2026-01-01T12:00:00Z",
          },
        }),
        { status: 200 },
      );
    }
    return original(input, init);
  });
  mount(
    <Routes>
      <Route path="/leads/:id" element={<LeadDetail />} />
    </Routes>,
    "/leads/1",
  );
  await screen.findByRole("heading", { name: "Morgan Parker" });
  await user.click(screen.getByRole("tab", { name: "Analysis & drafts" }));
  expect(
    screen.getByText(
      "Source context changed since this draft. Regenerate and review it before copying.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy Draft" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Regenerate from source context" }),
  ).toBeEnabled();
});
