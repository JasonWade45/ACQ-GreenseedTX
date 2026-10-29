import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BriefingPage } from "./pages/BriefingPage";
import DraftsPage from "./pages/DraftsPage";
import SkipTracePage from "./pages/SkipTracePage";

const briefing = {
  generated_at: "2026-10-29T12:00:00Z",
  compliance_first: [
    {
      id: 91,
      lead_id: 3,
      lead_name: "Dana Seller",
      classification: "STOP",
      confidence: 1,
      evidence: "STOP",
      label: "Add to suppression",
    },
  ],
  replies_needing_action: [
    {
      lead_id: 3,
      name: "Dana Seller",
      classification: "STOP",
      confidence: 1,
      evidence: "STOP",
      suggestion_id: 91,
      kind: "suppress",
      needs_review: false,
      received_at: "2026-10-29T11:00:00Z",
    },
    {
      lead_id: 7,
      name: "Marisol Vega",
      classification: "INTERESTED",
      confidence: 0.86,
      evidence: "Yes, tell me more about the as-is option",
      suggestion_id: 92,
      kind: "review_only",
      needs_review: false,
      received_at: "2026-10-29T10:00:00Z",
    },
  ],
  followups_due: [],
  drafts_awaiting_approval: 1,
  drafts_failing_validation: [
    { id: 44, lead_id: 9, reasons: ["missing street address"] },
  ],
  leads_needing_skip_trace: 1,
  skip_trace_leads: [
    { lead_id: 12, address: "1000 Oak Ridge Dr", heat: "HOT", score: 87.1, priority_tier: "P1" },
  ],
  stalled_leads: 2,
  stalled_window_days: 14,
  sync_conflicts: 0,
  backups: {
    last_backup_at: "2026-10-29T03:00:00Z",
    last_backup_file: "acquisitions-20261029T030000Z-scheduled.db",
    last_backup_reason: "scheduled",
    second_folder: "/Volumes/Backup/acq",
    second_folder_ok: true,
    second_folder_detail: "copied and verified",
    second_folder_checked_at: "2026-10-29T03:00:01Z",
  },
  last_backup: "2026-10-29T03:00:00Z",
  never_sent: true,
};

const drafts = {
  total: 2,
  items: [
    {
      id: 44,
      lead_id: 9,
      body: "Hi there, this is Jason Wade with GreenSeedTX LLC.",
      status: "DRAFT",
      template_id: 2,
      variant: "A",
      validator_result: { ok: false, reasons: ["missing street address"] },
      why_this_template: ["senior owner"],
      created_at: "2026-10-29T09:00:00Z",
      lead_name: "Alice Chen",
    },
    {
      id: 45,
      lead_id: 10,
      body: "Hi Dana, this is Jason Wade with GreenSeedTX LLC about 1000 Oak Ridge Dr.",
      status: "DRAFT",
      template_id: 2,
      variant: "B",
      validator_result: { ok: true, reasons: [] },
      why_this_template: ["tax lien flag"],
      created_at: "2026-10-29T09:30:00Z",
      lead_name: "Dana Seller",
    },
  ],
};

const skipTrace = {
  needs_skip_trace: 1,
  columns: ["lead_key", "address", "city", "state", "zip"],
  accepts: ["lead_key", "owner_name", "phone1"],
};

let routes: Record<string, unknown>;
function mount(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  routes = {
    "/briefing": briefing,
    "/drafts": drafts,
    "/skip-trace/summary": skipTrace,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      // The API helper appends the query string to the path; keys are path-only.
      const path = String(input).replace("/api", "").split("?")[0];
      return new Response(JSON.stringify(routes[path] ?? null), { status: 200 });
    }),
  );
});

it("puts the opt-out first in the briefing and keeps confirm/dismiss human", async () => {
  mount(<BriefingPage />);
  await screen.findByText("Opt-out replies — confirm suppression");
  expect(screen.getAllByRole("button", { name: /Add to suppression/ }).length).toBe(1);
  expect(screen.getByText("Marisol Vega")).toBeInTheDocument();
  // The STOP reply is not repeated in the ordinary reply list.
  expect(screen.getAllByText("Dana Seller").length).toBe(1);
  expect(screen.getByText(/14d\+/)).toBeInTheDocument();
  expect(screen.getByText(/copied and verified/)).toBeInTheDocument();
});

it("blocks approval of a draft that failed the validator", async () => {
  mount(<DraftsPage />);
  await screen.findByText("Alice Chen");
  const failed = screen.getAllByRole("button", { name: /Mark reviewed/ })[0];
  expect(failed).toBeDisabled();
  const passed = screen.getAllByRole("button", { name: /Mark reviewed/ })[1];
  expect(passed).toBeEnabled();
  expect(screen.getByText(/missing street address/)).toBeInTheDocument();
  expect(screen.getByText(/Why this template: senior owner/)).toBeInTheDocument();
  // There is no bulk copy or send control anywhere on the queue.
  expect(screen.queryByRole("button", { name: /copy all|send/i })).toBeNull();
});

it("explains the skip-trace loop without claiming a provider call", async () => {
  mount(<SkipTracePage />);
  await screen.findByText("1");
  expect(
    screen.getByText(/The app never calls a provider itself/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Export addresses/ })).toBeEnabled();
  expect(screen.getByRole("button", { name: /Choose results CSV/ })).toBeEnabled();
});
