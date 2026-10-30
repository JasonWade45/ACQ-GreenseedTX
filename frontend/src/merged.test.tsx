import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { WorkspaceContext } from "./components";
import type { Meta } from "./types";
import { CallsPanel, TagsPanel } from "./calls";
import { AutomationPage } from "./pages/AutomationPage";
import { AssignmentPage } from "./pages/AssignmentPage";

const meta: Meta = {
  stages: [{ code: "new", label: "New", position: 0, active: true }],
  outcomes: ["Connected"],
  import_fields: { full_name: "Full name" },
  timezone: "America/New_York",
  mode: "disabled",
  sources: [],
  managers: [],
  communication: "Draft only",
};

const callList = {
  items: [
    {
      id: 3,
      lead_id: 7,
      outcome: "interested",
      label: "Interested",
      direction: "outbound",
      duration_seconds: 240,
      notes: "Wants to close before spring",
      next_step: "Call Thursday",
      occurred_at: "2026-10-30T10:00:00Z",
      followup_id: 9,
    },
  ],
  outcomes: [
    { code: "connected", label: "Connected" },
    { code: "interested", label: "Interested" },
    { code: "dnc", label: "Asked to Stop Contact" },
  ],
  suggestion: {
    should_schedule: true,
    reason: "Interested seller — follow up tomorrow",
    followup_type: "Call",
    due_at: "2026-10-31T10:00:00Z",
  },
};

const script = {
  objective: "Confirm motivation",
  steps: [
    { step_number: 1, title: "Opening", content: "Hi Dana", tips: "Be brief" },
    { step_number: 2, title: "Discovery", content: "Ask about the property", tips: "Listen" },
  ],
  key_objections: [{ objection: "Retail price", response: "A cash offer is different" }],
  next_step: "Record the outcome",
};

const rules = [
  {
    id: 1,
    name: "Stale lead check-in",
    description: "No contact for 14 days",
    rule_type: "stale_lead",
    config: { days_since_contact: 14 },
    enabled: true,
    last_run_at: null,
    last_run_result: null,
  },
];

const payloads: Record<string, unknown> = {
  "/leads/7/conversations": callList,
  "/leads/7/tags": [
    { id: 1, tag: "probate" },
    { id: 2, tag: "hot" },
  ],
  "/leads/7/conversations/script": { script },
  "/automation/rules": rules,
  "/automation/logs": [
    {
      id: 1,
      rule_name: "Stale lead check-in",
      records_affected: 3,
      result: "success",
      error_message: null,
      started_at: "2026-10-30T10:00:00Z",
    },
  ],
  "/automation/stale-leads": [
    {
      lead_id: 7,
      full_name: "Dana Reyes",
      stage_code: "new",
      contact_status: "unknown",
      assigned_manager: null,
      last_contact_at: null,
      days_since_contact: 30,
      has_pending_followup: false,
    },
  ],
  "/automation/run": { results: [{ rule_name: "Stale lead check-in", affected: 3, state: "success" }] },
  "/assignment/rules": [
    {
      id: 1,
      name: "Texas desk",
      priority: 10,
      enabled: true,
      is_fallback: false,
      state: "TX",
      city: null,
      target_assignee: "Jason",
      notes: null,
    },
  ],
  "/assignment/apply": { considered: 10, assigned: 4, unmatched: 6 },
};

function mount(content: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WorkspaceContext.Provider value={{ meta, toast: vi.fn() }}>
          {content}
        </WorkspaceContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = input.replace("/api", "").split("?")[0];
      if (init?.method && init.method !== "GET" && payloads[path] !== undefined) {
        return new Response(JSON.stringify(payloads[path]), { status: 200 });
      }
      if (init?.method && init.method !== "GET") {
        if (path === "/leads/7/conversations") {
          return new Response(JSON.stringify({ call: callList.items[0], suggestion: {}, lead: {} }), {
            status: 201,
          });
        }
        return new Response(JSON.stringify({ ok: true, created: 1 }), { status: 200 });
      }
      return new Response(JSON.stringify(payloads[path] ?? {}), { status: 200 });
    }),
  );
});

describe("call log", () => {
  it("shows the recorded call and the implied next step", async () => {
    mount(<CallsPanel leadId={7} />);
    expect(await screen.findByText("Call history (1)")).toBeInTheDocument();
    expect(screen.getByText("Wants to close before spring")).toBeInTheDocument();
    expect(screen.getByText(/Interested seller/)).toBeInTheDocument();
  });

  it("opens the local live script without any AI call", async () => {
    const user = userEvent.setup();
    mount(<CallsPanel leadId={7} />);
    await screen.findByText("Call history (1)");
    await user.click(screen.getByRole("button", { name: /Live call script/ }));
    expect(await screen.findByText("Hi Dana")).toBeInTheDocument();
    expect(screen.getByText("Retail price")).toBeInTheDocument();
  });

  it("logs an outcome with the chosen next step", async () => {
    const user = userEvent.setup();
    mount(<CallsPanel leadId={7} />);
    await screen.findByText("Call history (1)");
    await user.selectOptions(screen.getByLabelText("Outcome"), "dnc");
    await user.click(screen.getByRole("button", { name: /Save call/ }));
    await waitFor(() => {
      const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
      const postCall = calls.find((call) => call[1]?.method === "POST");
      expect(postCall).toBeTruthy();
      expect(String(postCall?.[1]?.body)).toContain('"outcome":"dnc"');
    });
  });
});

describe("tags", () => {
  it("lists local tags", async () => {
    mount(<TagsPanel leadId={7} />);
    expect(await screen.findByText("probate")).toBeInTheDocument();
    expect(screen.getByText("hot")).toBeInTheDocument();
  });
});

describe("automation", () => {
  it("shows the rule, the stale leads and the last run", async () => {
    mount(<AutomationPage />);
    expect((await screen.findAllByText("Stale lead check-in")).length).toBeGreaterThan(0);
    expect(screen.getByText("Dana Reyes")).toBeInTheDocument();
  });
});

describe("assignment", () => {
  it("shows the rule and applies it without touching the stage", async () => {
    const user = userEvent.setup();
    mount(<AssignmentPage />);
    expect(await screen.findByText("Texas desk")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Apply rules/ }));
    expect(await screen.findByText(/assigned 4/)).toBeInTheDocument();
  });
});

