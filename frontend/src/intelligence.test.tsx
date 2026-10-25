import { beforeEach, it, expect, vi } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { CloudWorkbench, IntegrationSettings } from "./intelligence";
import type { IntegrationStatus, CloudReview, LeadProfile } from "./types";

const integrations: IntegrationStatus = {
  groq: {
    provider: "groq",
    enabled: true,
    key_configured: true,
    model: "openai/gpt-oss-20b",
    daily_limit: 30,
    used_today: 0,
    max_output_tokens: 3000,
    consent_mode: "redacted_review_each_request",
    external_data_flow: "Reviewed context only",
    automatic_processing: false,
    automatic_communication: false,
    crm_writes: false,
    validated: false,
    supported_models: [{ id: "openai/gpt-oss-20b", label: "GPT-OSS 20B" }],
  },
  resimpli: {
    key_configured: false,
    mode: "disabled",
    adapter_verified: false,
    adapter_configured: false,
    writes_enabled: false,
    validated: false,
    checked_at: null,
  },
  environment_overrides: { groq: false, resimpli: false },
  secret_storage: "Backend only",
  consent_policy: "redacted_review_each_request",
  automatic_communication: false,
};
const lead = {
  id: 1,
  full_name: "Morgan Parker",
  restriction_status: "reviewed_clear",
  do_not_contact: false,
  draft: null,
  draft_stale: false,
} as LeadProfile;
const preview: CloudReview = {
  id: "synthetic-review",
  lead_id: 1,
  purpose: "analyze",
  provider: "groq",
  model_id: "openai/gpt-oss-20b",
  state: "pending_review",
  payload_hash: "a".repeat(64),
  records: [
    {
      ref: "E001",
      text: "An explicit callback request is recorded.",
      label: "source contact outcome",
    },
  ],
  result: { constraints: { restriction: "reviewed_clear" }, redactions: 3 },
  usage: {},
  error: null,
  created_at: "2026-10-21T12:00:00Z",
  expires_at: "2026-10-21T12:15:00Z",
  started_at: null,
  completed_at: null,
};
let request: ReturnType<typeof vi.fn>;
function mount(children: ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false, gcTime: 0 } },
        })
      }
    >
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  request = vi.fn(async (input: string, init?: RequestInit) => {
    if (input === "/api/integrations")
      return new Response(JSON.stringify(integrations));
    if (input.endsWith("/cloud/requests")) return new Response("[]");
    if (input.endsWith("/cloud/preview"))
      return new Response(
        JSON.stringify({
          ...preview,
          purpose: JSON.parse(String(init?.body)).purpose,
        }),
      );
    if (input.endsWith("/execute"))
      return new Response(
        JSON.stringify({
          ...preview,
          state: "completed",
          result: {
            summary: {
              text: "Callback request is recorded.",
              evidence: ["E001"],
              quote: preview.records[0].text,
            },
            insight_id: 1,
          },
        }),
      );
    if (input === "/api/integrations/credentials")
      return new Response(JSON.stringify(integrations));
    return new Response("{}");
  });
  vi.stubGlobal("fetch", request);
});

it("requires approval before any cloud execution request", async () => {
  const user = userEvent.setup();
  mount(<CloudWorkbench lead={lead} />);
  const open = await screen.findByRole("button", {
    name: "Analyze with Groq",
  });
  await waitFor(() => expect(open).toBeEnabled());
  await user.click(open);
  const dialog = await screen.findByRole("dialog", {
    name: "Review before Groq",
  });
  const approve = within(dialog).getByRole("button", {
    name: "Approve & analyze with Groq",
  });
  expect(approve).toBeDisabled();
  expect(
    request.mock.calls.some((call) => String(call[0]).endsWith("/execute")),
  ).toBe(false);
  await user.click(
    within(dialog).getByRole("checkbox", {
      name: "I reviewed the selected redacted context and authorize this request to Groq.",
    }),
  );
  await user.click(approve);
  await waitFor(() =>
    expect(
      request.mock.calls.some((call) => String(call[0]).endsWith("/execute")),
    ).toBe(true),
  );
  const call = request.mock.calls.find((call) =>
    String(call[0]).endsWith("/execute"),
  )!;
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({
    confirmation: "SEND REVIEWED CONTEXT",
    selected_refs: ["E001"],
    force_refresh: false,
  });
  expect(
    request.mock.calls.every((call) => String(call[0]).startsWith("/api/")),
  ).toBe(true);
});

it("does not allow an approved but empty evidence selection", async () => {
  const user = userEvent.setup();
  mount(<CloudWorkbench lead={lead} />);
  const open = await screen.findByRole("button", {
    name: "Analyze with Groq",
  });
  await waitFor(() => expect(open).toBeEnabled());
  await user.click(open);
  const dialog = await screen.findByRole("dialog", {
    name: "Review before Groq",
  });
  await user.click(within(dialog).getByRole("button", { name: "Clear" }));
  await user.click(
    within(dialog).getByRole("checkbox", {
      name: "I reviewed the selected redacted context and authorize this request to Groq.",
    }),
  );
  expect(
    within(dialog).getByRole("button", { name: "Approve & analyze with Groq" }),
  ).toBeDisabled();
  expect(
    request.mock.calls.some((call) => String(call[0]).endsWith("/execute")),
  ).toBe(false);
});

it("keeps cloud draft preparation disabled for DNC profiles", async () => {
  mount(
    <CloudWorkbench
      lead={{
        ...lead,
        restriction_status: "do_not_contact",
        do_not_contact: true,
      }}
    />,
  );
  const draft = await screen.findByRole("button", {
    name: "Draft with Groq",
  });
  expect(draft).toBeDisabled();
});

it("clears replacement credentials after private backend save", async () => {
  const user = userEvent.setup();
  mount(<IntegrationSettings />);
  const input = await screen.findByLabelText(/^Replacement Groq API key/);
  const form = input.closest("form")!;
  const dummy = "gsk_SYNTHETIC_UNIT_TEST_ONLY_NOT_REAL";
  await user.type(input, dummy);
  await user.click(within(form).getByRole("checkbox"));
  await user.click(
    within(form).getByRole("button", { name: "Save private key" }),
  );
  await waitFor(() => expect(input).toHaveValue(""));
  const call = request.mock.calls.find(
    (call) => String(call[0]) === "/api/integrations/credentials",
  )!;
  expect(JSON.parse(String(call[1]?.body))).toMatchObject({
    provider: "groq",
    api_key: dummy,
    confirm_private_storage: true,
  });
  expect(screen.queryByText(dummy)).not.toBeInTheDocument();
  expect(localStorage.getItem("GROQ_API_KEY")).toBeNull();
});
