import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { WorkspaceContext } from "./components";
import type { Meta } from "./types";
import {
  CrmQueuePage,
  GrokStatusPanel,
  IntegrationWidgets,
  LeadIntegrationCards,
  ProgressRing,
  StatusPill,
} from "./crm";

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

const cards = {
  lead_id: 7,
  full_name: "Dana Reyes",
  next_action: {
    kind: "task",
    title: "Call the title company",
    due_at: null,
    detail: null,
  },
  checklist: {
    done: 1,
    total: 4,
    percent: 25,
    complete: false,
    checklists: [
      {
        key: "lead_manager",
        name: "Lead Manager",
        done: 1,
        total: 2,
        percent: 50,
        complete: false,
        items: [
          {
            id: 11,
            title: "Confirm the property address and county",
            detail: null,
            done: true,
            source: "template",
          },
          {
            id: 12,
            title: "Review contact restrictions",
            detail: "Record the evidence",
            done: false,
            source: "ai",
          },
        ],
      },
      {
        key: "acquisition",
        name: "Acquisition",
        done: 0,
        total: 2,
        percent: 0,
        complete: false,
        items: [
          {
            id: 21,
            title: "Pull comparable sales",
            detail: null,
            done: false,
            source: "template",
          },
          {
            id: 22,
            title: "Prepare the wholesale disclosure",
            detail: null,
            done: false,
            source: "template",
          },
        ],
      },
    ],
  },
  exit_strategy: {
    run_id: "run-1",
    model: "grok-4.7",
    created_at: "2026-10-29T12:00:00Z",
    advice: {
      situation_summary: "Owner has arrears.",
      next_steps: ["Confirm the payoff"],
      do_not: ["Do not quote a price"],
      risks: ["Arrears may exceed equity"],
      exit_strategy: {
        name: "Subject-to",
        reasoning: "The existing loan is assumable.",
        missing_information: ["Loan balance"],
      },
      confidence: "medium" as const,
    },
    disclaimer: "Decision support only. This is not legal advice.",
    compliance: "Compliance reminder: licensing and DNC rules apply.",
  },
  last_conversation: {
    occurred_at: "2026-10-28T15:00:00Z",
    direction: "inbound",
    summary: "Asked about the timeline.",
    outcome: "Connected",
  },
  crm_sync: {
    state: "blocked",
    resimpli_lead_id: null,
    reason: "exists_in_crm",
    message: "A matching lead already exists",
    pushed_at: null,
  },
  notes: [
    {
      id: 3,
      body: "[GreenSeed] Green Seed lead record\nLead type: Probate",
      state: "blocked",
      reason:
        "REsimpli's v6 Open API has no note endpoint; copy this note from the lead profile",
      delivered_via: null,
      created_at: "2026-10-29T12:00:00Z",
    },
  ],
  ai: { enabled: true, remaining_today: 4 },
};

const queue = {
  rows: [
    {
      lead_id: 7,
      full_name: "Dana Reyes",
      address: "1000 Oak Ridge Dr, Arlington, TX",
      state: "pending",
      reason: "needs_phone",
      message: "REsimpli requires a phone to create a lead",
      resimpli_lead_id: null,
      pushed_at: null,
    },
  ],
  counts: { total: 1, ready: 0, blocked: 1 },
  failed: 2,
  mode: "review" as const,
  writes_enabled: true,
};

const pushSettings = {
  settings: {
    mode: "review" as const,
    marketing_campign_id: "",
    market_id: "",
    pipeline_id: "",
    main_status_id: "",
    note_fields: {},
  },
  crm_writes_enabled: true,
  confirmation_phrase: "PUSH TO CRM",
  note_fields: {},
  write_scope: "Create a lead only. No updates, no stage changes, no deletes.",
};

const grokStatus = {
  enabled: true,
  key_configured: true,
  used: 3,
  limit: 20,
  remaining: 17,
  exhausted: false,
  api: "responses",
  models: {
    followup_draft: "grok-4.3",
    checklist_suggest: "grok-4.3",
    advisor: "grok-4.7",
  },
  monthly_estimate: { basis: "planned_volume", monthly_usd: 1.23 },
  fields: [{ key: "property_address", label: "Property address" }],
  enabled_fields: ["property_address", "priority"],
  disclaimer: "Decision support only. This is not legal advice.",
  compliance: "Compliance reminder.",
};

const summary = {
  push_queue: { ready: 2, blocked: 1, total: 3 },
  failed_syncs: 1,
  checklists_due: { open_items: 9, leads_due: 4 },
  advisor_ready: 2,
  notes_blocked: 1,
};

const payloads: Record<string, unknown> = {
  "/leads/7/cards": cards,
  "/integrations/resimpli/push/queue": queue,
  "/integrations/resimpli/push/settings": pushSettings,
  "/integrations/grok/status": grokStatus,
  "/dashboard/integrations": summary,
};

let requestMock: ReturnType<typeof vi.fn>;

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
  requestMock = vi.fn(async (input: string, init?: RequestInit) => {
    const path = input.replace("/api", "").split("?")[0];
    if (init?.method && init.method !== "GET" && payloads[path] !== undefined)
      return new Response(JSON.stringify(payloads[path]), { status: 200 });
    if (init?.method && init.method !== "GET")
      return new Response(
        JSON.stringify({
          state: "blocked",
          reason: "confirmation_required",
          message: "Type PUSH TO CRM",
        }),
        { status: 200 },
      );
    return new Response(JSON.stringify(payloads[path] ?? {}), { status: 200 });
  });
  vi.stubGlobal("fetch", requestMock);
});

describe("lead integration cards", () => {
  it("shows all six cards with a status each", async () => {
    mount(<LeadIntegrationCards leadId={7} />);
    expect(await screen.findByText("Next action")).toBeInTheDocument();
    expect(screen.getByText("Checklists")).toBeInTheDocument();
    expect(screen.getByText("Exit strategy")).toBeInTheDocument();
    expect(screen.getByText("Last conversation")).toBeInTheDocument();
    expect(screen.getByText("CRM sync")).toBeInTheDocument();
    expect(screen.getByText("Notes")).toBeInTheDocument();
  });

  it("renders checklist progress as an accessible ring, not colour alone", async () => {
    mount(<LeadIntegrationCards leadId={7} />);
    const ring = await screen.findByRole("img", {
      name: /Total checklist progress: 1 of 4 complete \(25%\)/,
    });
    expect(ring).toBeInTheDocument();
    expect(
      screen.getByText("Confirm the property address and county"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("AI suggestion").length).toBe(1);
  });

  it("ticks an item through the API", async () => {
    mount(<LeadIntegrationCards leadId={7} />);
    const boxes = await screen.findAllByRole("checkbox");
    await userEvent.click(boxes[1]);
    await waitFor(() =>
      expect(requestMock).toHaveBeenCalledWith(
        "/api/checklists/items/12",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ done: true }),
        }),
      ),
    );
  });

  it("explains that an existing CRM match blocks the push", async () => {
    mount(<LeadIntegrationCards leadId={7} />);
    expect(
      await screen.findByText(/A matching lead already exists/),
    ).toBeInTheDocument();
  });

  it("labels the advisor note as decision support", async () => {
    mount(<LeadIntegrationCards leadId={7} />);
    expect(
      await screen.findByText(/Decision support only/),
    ).toBeInTheDocument();
    expect(screen.getByText("Subject-to")).toBeInTheDocument();
    expect(screen.getByText("Loan balance")).toBeInTheDocument();
  });

  it("shows the note with the reason it is only local, and copies it", async () => {
    const writeText = vi.fn();
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    mount(<LeadIntegrationCards leadId={7} />);
    expect(await screen.findByText("Local only")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Copy note/ }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(cards.notes[0].body),
    );
    expect(
      await screen.findByRole("button", { name: /Copied/ }),
    ).toBeInTheDocument();
  });
});

describe("push queue page", () => {
  it("shows the counts, the reason each lead waits and the create-only scope", async () => {
    mount(<CrmQueuePage />);
    expect(
      await screen.findByText(
        "Create a lead only. No updates, no stage changes, no deletes.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Needs a phone")).toBeInTheDocument();
    expect(
      screen.getByText(/Every lead that is not yet in the CRM/),
    ).toBeInTheDocument();
  });

  it("previews the exact body and refuses to push before the phrase is typed", async () => {
    payloads["/leads/7/crm/preview"] = {
      lead_id: 7,
      eligible: true,
      reason: null,
      message: "Ready to create in REsimpli",
      body: { propertyType: "residential" },
      payload_hash: "abc123",
      warnings: [],
      matches: [],
      note: "[GreenSeed] note",
      writes_nothing: true,
    };
    mount(<CrmQueuePage />);
    await userEvent.click(
      await screen.findByRole("button", { name: /Preview/ }),
    );
    const button = await screen.findByRole("button", {
      name: /Create in REsimpli/,
    });
    expect(button).toBeDisabled();

    const input = screen.getByLabelText(
      /Type PUSH TO CRM to create this one lead/,
    );
    await userEvent.type(input, "PUSH TO CRM");
    expect(button).toBeEnabled();
    await userEvent.click(button);
    await waitFor(() =>
      expect(requestMock).toHaveBeenCalledWith(
        "/api/leads/7/crm/push",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            confirmation: "PUSH TO CRM",
            include_note: true,
          }),
        }),
      ),
    );
  });

  it("does not offer a push button when the preview says the lead is blocked", async () => {
    payloads["/leads/7/crm/preview"] = {
      lead_id: 7,
      eligible: false,
      reason: "exists_in_crm",
      message: "A matching lead already exists in REsimpli",
      body: null,
      payload_hash: null,
      warnings: [],
      matches: [
        {
          resimpli_lead_id: "crm-1",
          full_name: "Dana Reyes",
          address: "1000 Oak Ridge Dr",
          matched_on: "phone",
        },
      ],
      note: null,
      writes_nothing: true,
    };
    mount(<CrmQueuePage />);
    await userEvent.click(
      await screen.findByRole("button", { name: /Preview/ }),
    );
    expect(
      await screen.findByText(/Possible match already in the CRM/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Create in REsimpli/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps the four account ids, spelled the way the API spells them", async () => {
    mount(<CrmQueuePage />);
    expect(
      await screen.findByLabelText(/Marketing campaign id/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Market id/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Pipeline id/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Main status id/)).toBeInTheDocument();
  });
});

describe("grok status", () => {
  it("shows the cap, the models and the monthly estimate", async () => {
    mount(<GrokStatusPanel />);
    expect(await screen.findByText("3/20")).toBeInTheDocument();
    expect(screen.getByText("$1.23")).toBeInTheDocument();
    expect(screen.getByText("grok-4.7")).toBeInTheDocument();
    expect(screen.getByText(/Drafts are copy-only/)).toBeInTheDocument();
  });
});

describe("dashboard widgets", () => {
  it("counts the push queue, failed syncs, checklists and advisor notes", async () => {
    mount(<IntegrationWidgets />);
    expect(await screen.findByText("Push queue ready")).toBeInTheDocument();
    expect(screen.getByText("Failed syncs")).toBeInTheDocument();
    expect(screen.getByText("Checklists due")).toBeInTheDocument();
    expect(screen.getByText("Advisor ready")).toBeInTheDocument();
    expect(screen.getByText("Notes blocked")).toBeInTheDocument();
  });
});

describe("status vocabulary", () => {
  it("always pairs a colour with a word", () => {
    render(<StatusPill tone="danger">Blocked</StatusPill>);
    expect(screen.getByRole("status")).toHaveTextContent("Blocked");
    expect(screen.getByRole("status").className).toContain("crm-status-danger");
  });

  it("gives the ring a text label a screen reader can read", () => {
    render(
      <ProgressRing percent={50} done={2} total={4} label="Lead Manager" />,
    );
    expect(
      screen.getByRole("img", { name: "Lead Manager: 2 of 4 complete (50%)" }),
    ).toBeInTheDocument();
  });
});
