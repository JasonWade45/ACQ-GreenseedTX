import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CallPreparation, PropertyResearch, WorkspaceBridge } from "./unified";
import type { LeadProfile, Property } from "./types";
import type { ReactNode } from "react";
const lead = {
  id: 1,
  properties: [
    {
      id: 2,
      street_address: "35 Fictional Lane",
      property_metadata: {},
    } as Property,
  ],
} as LeadProfile;
const plan = {
  id: 1,
  source: "grounded-local-prep-v1",
  opener: null,
  talking_points: [],
  questions: [
    {
      key: "motivation",
      text: "Review motivation internally",
      reviewed: false,
      answer: "",
    },
  ],
  guardrails: ["No communication occurs"],
  internal_only: true,
  reason: "Restrictions incomplete",
  stale: false,
  updated_at: "2026-10-25T10:00:00Z",
};
let responses: Record<string, unknown>;
let requests: ReturnType<typeof vi.fn>;
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
  responses = {};
  requests = vi.fn(async (input: string, init?: RequestInit) => {
    const path = input.replace("/api", "");
    if (init?.method === "PATCH") {
      const body = JSON.parse(init.body as string);
      responses["/leads/1/call-plan"] = {
        ...plan,
        questions: [
          {
            ...plan.questions[0],
            reviewed: body.checks.motivation,
            answer: body.answers.motivation,
          },
        ],
      };
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }
    return new Response(JSON.stringify(responses[path] ?? null), {
      status: 200,
    });
  });
  vi.stubGlobal("fetch", requests);
});

it("withholds restricted openers and persists reviewed preparation, never a contact event", async () => {
  responses["/leads/1/call-plan"] = plan;
  mount(<CallPreparation lead={lead} />);
  await screen.findByText("Restrictions incomplete");
  expect(
    screen.queryByRole("button", { name: "Copy opener" }),
  ).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Review motivation internally" }),
  );
  await userEvent.type(
    screen.getByLabelText("Internal preparation notes: Motivation"),
    "Verify internally only",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Save preparation" }),
  );
  await waitFor(() =>
    expect(
      requests.mock.calls.some(
        ([path, init]) =>
          path === "/api/call-plans/1" && init?.method === "PATCH",
      ),
    ).toBe(true),
  );
  expect(
    requests.mock.calls.some(([path]) =>
      /activities|send|cloud|groq/i.test(path),
    ),
  ).toBe(false);
});

it("requires an explicit creation click and an explicit stale-plan regeneration", async () => {
  responses["/leads/1/call-plan"] = { ...plan, stale: true };
  mount(<CallPreparation lead={lead} />);
  await screen.findByText(/The seller context changed/);
  expect(
    screen.getByRole("button", { name: "Save preparation" }),
  ).toBeDisabled();
  expect(requests.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  await userEvent.click(
    screen.getByRole("button", { name: "Regenerate plan" }),
  );
  expect(
    screen.getByRole("dialog", { name: "Create a new preparation version?" }),
  ).toBeInTheDocument();
  expect(requests.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});

it("research opens no external portal automatically and fabricates no sold comps", async () => {
  responses["/leads/1/comps-brief?property_id=2"] = {
    subject: {
      street_address: "35 Fictional Lane",
      city: "Austin",
      state: "TX",
    },
    references: [],
    criteria: { price_min: null },
    portals: [{ label: "Zillow", url: "https://www.zillow.com/" }],
    notice: "Not actual sold comparables",
  };
  mount(<PropertyResearch lead={lead} />);
  await screen.findByText("No comparables yet");
  expect(
    await screen.findByRole("link", { name: "Open Zillow" }),
  ).toHaveAttribute("href", "https://www.zillow.com/");
  expect(screen.getByText("Unknown — verify first")).toBeInTheDocument();
  expect(requests.mock.calls.every(([path]) => path.startsWith("/api/"))).toBe(
    true,
  );
});

it("adds a comparable, shows the arithmetic, and never invents a sold price", async () => {
  responses["/leads/1/comps-brief?property_id=2"] = {
    subject: {
      id: 2,
      street_address: "35 Fictional Lane",
      city: "Austin",
      state: "TX",
      square_feet: 2000,
    },
    references: [],
    criteria: {},
    portals: [],
    comps: [
      {
        id: "abc123",
        address: "37 Fictional Lane",
        sold_price: 300000,
        price_per_sqft: 150,
        square_feet: 2000,
        sold_date: "2026-08-01",
        source: "County deed",
      },
    ],
    comps_summary: {
      count: 1,
      median_price_per_sqft: 150,
      suggested_low: 285000,
      suggested_high: 315000,
      note: "Arithmetic on your comparables, not an appraisal.",
    },
    notice: "Comparables here are the ones you entered yourself.",
  };
  mount(<PropertyResearch lead={lead} />);

  await screen.findByText("37 Fictional Lane");
  // The median and the row's own rate are both shown and must agree.
  expect(screen.getAllByText("$150.00")).toHaveLength(2);
  expect(screen.getByText("$285,000 – $315,000")).toBeInTheDocument();

  await userEvent.click(
    screen.getByRole("button", { name: "Add comparable" }),
  );
  await userEvent.type(
    screen.getByLabelText("Comparable address"),
    "39 Fictional Lane",
  );
  await userEvent.type(screen.getByLabelText("Sold price (USD)"), "250000");
  await userEvent.type(screen.getByLabelText("Living area (sq ft)"), "1800");
  expect(screen.getByText("$138.89 per sq ft")).toBeInTheDocument();

  await userEvent.click(
    screen.getByRole("button", { name: "Save comparable" }),
  );
  await waitFor(() =>
    expect(
      requests.mock.calls.some(
        ([path, init]) =>
          path === "/api/leads/1/comps" && init?.method === "POST",
      ),
    ).toBe(true),
  );
  const [, init] = requests.mock.calls.find(
    ([path]) => path === "/api/leads/1/comps",
  )!;
  const body = JSON.parse(init.body as string);
  expect(body).toMatchObject({
    property_id: 2,
    address: "39 Fictional Lane",
    sold_price: 250000,
    square_feet: 1800,
  });
  // The screen cannot pass anything the server has to trust blindly beyond these fields.
  expect(Object.keys(body).sort()).toEqual(
    [
      "address",
      "notes",
      "property_id",
      "sold_date",
      "sold_price",
      "source",
      "square_feet",
    ].sort(),
  );
});

it("migration decisions are blank by default and source DB upload is never offered", async () => {
  const job = {
    id: "test-review",
    source_name: "synthetic.db",
    status: "prepared",
    pending: 1,
    counts: {
      source_leads: 1,
      created: 0,
      linked: 0,
      skipped: 0,
      source_tables: { leads: 1 },
    },
    records: [
      {
        source_id: "legacy-1",
        name: "Legacy Example",
        address: "35 Fictional Lane",
        external_id: null,
        kind: "same_property_different_seller",
        status: "pending",
        candidates: [
          {
            lead_id: 9,
            name: "Different Person",
            address: "35 Fictional Lane",
            conflicting_fields: ["full_name"],
          },
        ],
        warnings: [],
      },
    ],
  };
  responses["/workspace-merges"] = [job];
  responses["/workspace-merges/capabilities"] = {
    local_selection_available: false,
  };
  responses["/workspace-merges/test-review"] = job;
  mount(<WorkspaceBridge />);
  await userEvent.click(
    await screen.findByRole("button", { name: /synthetic.db/ }),
  );
  const field = await screen.findByLabelText("Decision for Legacy Example");
  expect(field).toHaveValue("");
  expect(
    screen.queryByRole("button", { name: "Approve selected local migration" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("textbox", { name: /full local path/ }),
  ).not.toBeInTheDocument();
  expect(requests.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  await userEvent.selectOptions(field, "link:9");
  expect(
    screen.getByRole("checkbox", { name: /Also fill empty local fields/ }),
  ).not.toBeChecked();
  expect(screen.getByText("Conflicting: full_name")).toBeInTheDocument();
  expect(
    screen.getByRole("textbox", { name: /Type MERGE REVIEWED RECORDS/ }),
  ).toHaveValue("");
});
