import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const password = process.env.E2E_PASSWORD || "qa-only-password-2026!";
test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Workspace password").fill(password);
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Acquisitions overview" }),
  ).toBeVisible();
});

test("auth, fixture sync, database metrics and filtered navigation", async ({
  page,
}) => {
  await page.getByRole("link", { name: "Sync Status", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "REsimpli sync status" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sync now", exact: true }).click();
  await expect(
    page.getByText("Success", { exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("link", { name: "Dashboard", exact: true }).click();
  const total = page
    .locator(".metric-card")
    .filter({ hasText: "Total seller leads" });
  await expect(total.locator(".metric-value")).toHaveText("6");
  await total.click();
  await expect(
    page.getByRole("heading", { name: "Seller leads", exact: true }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(6);
  await page
    .getByRole("textbox", { name: "Search seller leads" })
    .fill("Morgan");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(
    page.getByRole("link", { name: /Morgan Parker/ }).first(),
  ).toBeVisible();
});

test("lead profile, grounded analysis, editable copy-only draft and DNC blocking", async ({
  page,
}) => {
  await page.goto("/leads?search=Morgan");
  await page
    .getByRole("link", { name: /Morgan Parker/ })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Morgan Parker" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Analysis & drafts" }).click();
  await expect(
    page.getByRole("heading", { name: "Evidence-based lead analysis" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Prepare a review-only draft" })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Editable draft" }),
  ).toContainText(/callback request/);
  await page
    .getByRole("textbox", { name: "Editable draft" })
    .fill(
      "Human-reviewed draft for the explicit callback request. No commitment.",
    );
  await page.getByRole("button", { name: "Save edits" }).click();
  await expect(page.getByText("Draft edits saved locally")).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy Draft" })).toBeVisible();
  await page.goto("/leads?search=Casey");
  await page
    .getByRole("link", { name: /Casey Reed/ })
    .first()
    .click();
  await page.getByRole("tab", { name: "Analysis & drafts" }).click();
  await expect(
    page.getByRole("button", { name: "Prepare a review-only draft" }),
  ).toBeDisabled();
  await expect(
    page.getByText("Do Not Contact: marketing follow-up drafts are blocked."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /send/i })).toHaveCount(0);
});

test("CSV import preview, rejection report, approval and repeat-file idempotency", async ({
  page,
}) => {
  await page.goto("/imports");
  const csv =
    "Full Name,Phone,Email,Property Address,City,State,DNC\nNora Example,2025550123,nora@example.test,700 E2E Example Road,Austin,TX,no\n,invalid,not-email,Missing,City,ZZ,maybe\n";
  await page.getByLabel("Upload lead file").setInputFiles({
    name: "e2e-legacy.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await expect(
    page.getByRole("heading", { name: "Column mapping & sheets" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Normalize & preview" }).click();
  await expect(
    page.getByRole("heading", { name: "Review normalized records" }),
  ).toBeVisible();
  await expect(page.getByText("Nora Example", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("checkbox", { name: "Select import row 3" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Select all new records" }).click();
  await page
    .getByRole("button", { name: "Review & approve local import" })
    .click();
  await page
    .getByRole("textbox", { name: "Type IMPORT LOCAL to confirm" })
    .fill("IMPORT LOCAL");
  await page.getByRole("button", { name: "Approve local writes" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.locator(".import-counts").filter({ hasText: "Imported locally" }),
  ).toBeVisible();
  const batchUrl = page.url();
  await page.goto("/imports");
  await page.getByLabel("Upload lead file").setInputFiles({
    name: "e2e-legacy-again.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await expect(page).toHaveURL(batchUrl);
  await page.goto("/leads?search=Nora");
  await expect(page.locator("tbody tr")).toHaveCount(1);
});

test("Excel workbook inspects multiple sheets and requires duplicate resolution", async ({
  page,
}) => {
  await page.goto("/imports");
  await page
    .getByLabel("Upload lead file")
    .setInputFiles("../examples/sample-seller-leads.xlsx");
  await expect(
    page.getByRole("checkbox", { name: /Seller leads/ }),
  ).toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: /Review candidates/ }),
  ).toBeChecked();
  await page.getByRole("button", { name: "Normalize & preview" }).click();
  await expect(
    page.getByRole("heading", { name: "Review normalized records" }),
  ).toBeVisible();
  await expect(
    page.getByText("Exact Duplicate", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Resolve duplicate row 2" }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review & approve local import" }),
  ).toBeDisabled();
});

test("daily follow-up create, reschedule, completion and cancellation persist locally", async ({
  page,
}) => {
  await page.goto("/leads?search=Morgan");
  await page
    .getByRole("link", { name: /Morgan Parker/ })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Schedule follow-up", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Why is a follow-up needed?" })
    .fill("E2E internal review task");
  await page.getByRole("button", { name: "Create local task" }).click();
  await page.getByRole("tab", { name: /^Follow-ups/ }).click();
  const task = page
    .locator(".followup-item")
    .filter({ hasText: "E2E internal review task" });
  await expect(task).toBeVisible();
  await task.getByRole("button", { name: "Reschedule" }).click();
  await page.getByLabel("New date and time").fill("2027-01-15T14:00");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Confirm reschedule" }).click();
  await task.getByRole("button", { name: "Complete", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Actual outcome" })
    .selectOption("Administrative / No Contact");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Confirm complete" }).click();
  await expect(task.getByText("Completed", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Schedule follow-up", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Why is a follow-up needed?" })
    .fill("E2E cancelled review task");
  await page.getByRole("button", { name: "Create local task" }).click();
  const cancelled = page
    .locator(".followup-item")
    .filter({ hasText: "E2E cancelled review task" });
  await cancelled.getByRole("button", { name: "Cancel follow-up" }).click();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Confirm cancel" }).click();
  await expect(cancelled.getByText("Cancelled", { exact: true })).toBeVisible();
  await page.goto("/followups?section=callbacks");
  await expect(
    page.getByRole("heading", { name: "Daily work queue" }),
  ).toBeVisible();
  await expect(page.getByText("Casey Reed", { exact: true })).toHaveCount(0);
});

test("appointments, reports and sync health are reachable with actual data", async ({
  page,
}) => {
  await page.goto("/appointments");
  await expect(
    page.getByRole("heading", { name: "Seller appointments" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Alex Rivera", exact: true }),
  ).toBeVisible();
  await page.goto("/reports");
  await expect(
    page.getByText("Recorded offer rate — all leads", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("NaN", { exact: false })).toHaveCount(0);
  await page.goto("/sync");
  await expect(
    page.getByText("Success", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("Not yet verified", { exact: true }),
  ).toBeVisible();
});

// Every route in the sidebar, so a new screen cannot ship unopened.
const ROUTES = [
  "/",
  "/leads",
  "/followups",
  "/appointments",
  "/imports",
  "/reports",
  "/insights",
  "/sync",
  "/settings",
  "/drafts",
  "/templates",
  "/skip-trace",
  "/briefing",
  "/safety",
];

test("all application routes render without browser exceptions and mobile has no page overflow", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  for (const route of ROUTES) {
    await page.goto(route);
    await expect(page.locator("main h1")).toBeVisible();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of ROUTES) {
    await page.goto(route);
    await expect(page.locator("main h1")).toBeVisible();
    expect(
      await page.evaluate(() => document.body.scrollWidth <= window.innerWidth),
    ).toBe(true);
  }
  await page.goto("/leads");
  await page
    .getByRole("link", { name: /Morgan Parker/ })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Morgan Parker", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(
    page.getByRole("link", { name: "Dashboard", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Dashboard", exact: true }),
  ).toBeInViewport();
  expect(errors).toEqual([]);
});

test("dashboard accessibility: named controls and no critical/serious WCAG violations", async ({
  page,
}) => {
  // Colour is measured on the settled page. An entrance animation at 95% opacity
  // lightens every label and reports contrast failures that do not exist.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await expect(
    page.locator(".metric-card").filter({ hasText: "Total seller leads" }),
  ).toBeVisible();
  await page.evaluate(() =>
    Promise.all(
      document.getAnimations().map((animation) => animation.finished.catch(() => {})),
    ),
  );
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const major = result.violations.filter((v) =>
    ["critical", "serious"].includes(v.impact || ""),
  );
  expect(
    // The measured colours travel with the failure: without them the report only
    // says "contrast" and someone has to guess which two values to change.
    major.map((v) => ({
      id: v.id,
      description: v.description,
      nodes: v.nodes.map((n) => `${n.target.join(" ")} :: ${n.failureSummary}`),
    })),
  ).toEqual([]);
});

test("keyboard command palette searches real seller records", async ({
  page,
}) => {
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Find your next move" });
  await expect(dialog).toBeVisible();
  const input = dialog.getByRole("textbox", { name: "Search workspace" });
  await expect(input).toBeFocused();
  await input.fill("Morgan");
  await dialog.getByRole("link", { name: /Morgan Parker/ }).click();
  await expect(
    page.getByRole("heading", { name: "Morgan Parker", exact: true }),
  ).toBeVisible();
  await expect(dialog).toHaveCount(0);
});

test("reduced-motion preference disables route and card animations", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Acquisitions overview" }),
  ).toBeVisible();
  const motion = await page.locator("main").evaluate((element) => ({
    name: getComputedStyle(element).animationName,
    duration: getComputedStyle(element).transitionDuration,
  }));
  expect(motion.name).toBe("none");
  expect(motion.duration).toBe("0s");
});

test("Groq redacted analysis requires individual approval before processing", async ({
  page,
}) => {
  test.skip(
    !process.env.E2E_CLOUD_FIXTURE,
    "Requires explicit synthetic no-network provider harness",
  );
  let executions = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/execute")) executions++;
  });
  await page.goto("/leads?search=Morgan");
  await page
    .getByRole("link", { name: /Morgan Parker/ })
    .first()
    .click();
  await page.getByRole("tab", { name: "Analysis & drafts" }).click();
  await page
    .getByRole("button", { name: "Analyze with Groq", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Review before Groq" });
  await expect(dialog).toContainText("This context has not been transmitted.");
  await expect(dialog.locator(".review-records")).not.toContainText("Morgan");
  await expect(dialog.locator(".review-records")).not.toContainText(
    "88 Sample Avenue",
  );
  await page.screenshot({
    path: "../docs/screenshots/groq-review-synthetic.png",
    fullPage: false,
    animations: "disabled",
  });
  const approve = dialog.getByRole("button", {
    name: "Approve & analyze with Groq",
  });
  await expect(approve).toBeDisabled();
  expect(executions).toBe(0);
  await dialog
    .getByRole("checkbox", {
      name: "I reviewed the selected redacted context and authorize this request to Groq.",
    })
    .check();
  await approve.click();
  await expect(dialog).toContainText(
    "AI proposal, not a verified source record.",
  );
  expect(executions).toBe(1);
  await dialog.getByRole("button", { name: "Close review" }).click();
  await expect(page.locator(".analysis-content")).toContainText(
    "groq:openai/gpt-oss-20b",
  );
});

test("Groq organized notes stay proposals until separately reviewed and saved", async ({
  page,
}) => {
  test.skip(
    !process.env.E2E_CLOUD_FIXTURE,
    "Requires explicit synthetic no-network provider harness",
  );
  await page.goto("/leads?search=Morgan");
  await page
    .getByRole("link", { name: /Morgan Parker/ })
    .first()
    .click();
  await page.getByRole("tab", { name: "Analysis & drafts" }).click();
  await page
    .getByRole("button", { name: "Organize notes", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Review before Groq" });
  await dialog
    .getByRole("checkbox", {
      name: "I reviewed the selected redacted context and authorize this request to Groq.",
    })
    .check();
  await dialog
    .getByRole("button", { name: "Approve & organize with Groq" })
    .click();
  const save = dialog.getByRole("button", {
    name: "Save as a separate local note",
  });
  await expect(save).toBeDisabled();
  await dialog
    .getByRole("checkbox", {
      name: "I verified this proposal against the original source.",
    })
    .check();
  await save.click();
  await expect(
    dialog.getByRole("button", { name: "Already saved locally" }),
  ).toBeDisabled();
  await dialog.getByRole("button", { name: "Close review" }).click();
  await page.getByRole("tab", { name: /Timeline/ }).click();
  await expect(
    page.getByText(
      /Human-reviewed AI-assisted organization \(original source notes preserved\)/,
    ),
  ).toBeVisible();
});

test("Groq draft fills personal placeholders locally and remains edit-copy only", async ({
  page,
}) => {
  test.skip(
    !process.env.E2E_CLOUD_FIXTURE,
    "Requires explicit synthetic no-network provider harness",
  );
  await page.goto("/leads?search=Morgan");
  await page
    .getByRole("link", { name: /Morgan Parker/ })
    .first()
    .click();
  await page.getByRole("tab", { name: "Analysis & drafts" }).click();
  await page
    .getByRole("button", { name: "Draft with Groq", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Review before Groq" });
  await expect(dialog.locator(".review-records")).not.toContainText("Morgan");
  await dialog
    .getByRole("checkbox", {
      name: "I reviewed the selected redacted context and authorize this request to Groq.",
    })
    .check();
  await dialog
    .getByRole("button", { name: "Approve & draft with Groq" })
    .click();
  const draft = dialog.getByRole("textbox", {
    name: "Groq-prepared draft · edit in the draft panel",
  });
  await expect(draft).toHaveValue(/Hi Morgan/);
  await expect(draft).toHaveValue(/88 Sample Avenue/);
  await expect(
    dialog.getByRole("button", { name: "Copy reviewed draft" }),
  ).toBeDisabled();
  await dialog
    .getByRole("checkbox", {
      name: "I reviewed this wording against the source facts.",
    })
    .check();
  await expect(
    dialog.getByRole("button", { name: "Copy reviewed draft" }),
  ).toBeEnabled();
  await dialog.getByRole("button", { name: "Close review" }).click();
  await expect(
    page.getByRole("textbox", { name: "Editable draft" }),
  ).toHaveValue(/Hi Morgan/);
  await expect(page.getByRole("button", { name: /send/i })).toHaveCount(0);
  await page.goto("/leads?search=Casey");
  await page
    .getByRole("link", { name: /Casey Reed/ })
    .first()
    .click();
  await page.getByRole("tab", { name: "Analysis & drafts" }).click();
  await expect(
    page.getByRole("button", { name: "Draft with Groq", exact: true }),
  ).toBeDisabled();
});

test("unified preparation persists review items without changing contact evidence", async ({
  page,
}) => {
  await page.goto("/leads?search=Morgan");
  await page
    .getByRole("link", { name: /Morgan Parker/ })
    .first()
    .click();
  const profilePath = new URL(page.url()).pathname;
  const before = await page.evaluate(async (path) => {
    const r = await fetch(`/api${path}`, {
      headers: {
        Authorization: `Bearer ${sessionStorage.getItem("acquisitions-session")}`,
      },
    });
    return r.json();
  }, profilePath);
  await page.getByRole("tab", { name: "Call preparation" }).click();
  await page.getByRole("button", { name: "Build local preparation" }).click();
  const reviewed = page.getByRole("checkbox", {
    name: /Confirm the actual reason for considering a sale/,
  });
  await reviewed.check();
  await page
    .getByLabel("Internal preparation notes: Motivation")
    .fill(
      "Internal preparation only; verify before relying on source motivation.",
    );
  await page.getByRole("button", { name: "Save preparation" }).click();
  await expect(
    page.getByText("Preparation saved; no contact was inferred", {
      exact: true,
    }),
  ).toBeVisible();
  const after = await page.evaluate(async (path) => {
    const r = await fetch(`/api${path}`, {
      headers: {
        Authorization: `Bearer ${sessionStorage.getItem("acquisitions-session")}`,
      },
    });
    return r.json();
  }, profilePath);
  expect(after.contact_status).toBe(before.contact_status);
  expect(after.last_contact_at).toBe(before.last_contact_at);
  expect(after.activities.length).toBe(before.activities.length);
  await page.reload();
  await page.getByRole("tab", { name: "Call preparation" }).click();
  await expect(reviewed).toBeChecked();
  await page.goto("/leads?search=Casey");
  await page
    .getByRole("link", { name: /Casey Reed/ })
    .first()
    .click();
  await page.getByRole("tab", { name: "Call preparation" }).click();
  await page.getByRole("button", { name: "Build local preparation" }).click();
  await expect(
    page.getByText(/internal record review only; no outreach script prepared/),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy opener" })).toHaveCount(
    0,
  );
});

test("unified property research has known references, no fabricated sales and mobile containment", async ({
  page,
}) => {
  await page.goto("/leads?search=Morgan");
  await page
    .getByRole("link", { name: /Morgan Parker/ })
    .first()
    .click();
  await page.getByRole("tab", { name: "Property research" }).click();
  // There is no MLS feed, and the panel says so instead of implying sold data exists.
  await expect(page.getByText("No MLS feed", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/Comparables here are the ones you entered yourself/),
  ).toBeVisible();
  await expect(page.locator(".research-subject")).toContainText("88 Sample Avenue");
  await expect(page.getByText("$185,000", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Zillow" })).toHaveAttribute(
    "href",
    "https://www.zillow.com/",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await expect(
    page.getByRole("button", { name: /send|dial|call now/i }),
  ).toHaveCount(0);
});

test("unified address-only compound CSV stores no invented owner and blocks drafts", async ({
  page,
}) => {
  await page.goto("/imports");
  const csv =
    'Property Address,Beds Baths and Sqft,MV\n"36 Fictional Lane, Austin, TX 78701",3 beds 2 baths 1800 sqft,250k Redfin\n';
  await page
    .getByLabel("Upload lead file")
    .setInputFiles({
      name: "property-only-unified.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(csv),
    });
  await page.getByRole("button", { name: "Normalize & preview" }).click();
  await expect(
    page.getByText("Owner unknown · property-only", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Select all new records" }).click();
  await page
    .getByRole("button", { name: "Review & approve local import" })
    .click();
  await page
    .getByRole("textbox", { name: "Type IMPORT LOCAL to confirm" })
    .fill("IMPORT LOCAL");
  await page.getByRole("button", { name: "Approve local writes" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.goto("/leads?search=36%20Fictional%20Lane");
  await page
    .getByRole("link", { name: /Owner identity unknown/ })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Owner identity unknown" }),
  ).toBeVisible();
  await expect(page.getByText("$250,000", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Analysis & drafts" }).click();
  await expect(
    page.getByRole("button", { name: "Prepare a review-only draft" }),
  ).toBeDisabled();
});

test("unified local database migration requires decisions and preserves historical artifacts", async ({
  page,
}) => {
  test.skip(
    !process.env.E2E_LEGACY_SOURCE,
    "Requires an isolated synthetic legacy DB from the QA runner",
  );
  await page.goto("/imports");
  await page.getByLabel(/full local path/).fill(process.env.E2E_LEGACY_SOURCE!);
  await page.getByRole("button", { name: "Prepare read-only review" }).click();
  const choice = page.getByLabel("Decision for Legacy Merge Example");
  await expect(choice).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Approve selected local migration" }),
  ).toHaveCount(0);
  await choice.selectOption("separate");
  await page
    .getByRole("textbox", { name: /Type MERGE REVIEWED RECORDS/ })
    .fill("MERGE REVIEWED RECORDS");
  await page
    .getByRole("button", { name: "Approve selected local migration" })
    .click();
  await expect(page.getByText(/Review complete. Both originals/)).toBeVisible();
  await page.goto("/leads?search=Legacy%20Merge%20Example");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page
    .getByRole("link", { name: /Legacy Merge Example/ })
    .first()
    .click();
  await expect(
    page.getByText("No verified contact evidence", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Example County", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Source records" }).click();
  await page
    .getByText("View original and normalized values (confidential)")
    .click();
  await expect(page.locator(".raw-data pre")).toContainText(
    "Human-edited historical draft, archived only.",
  );
  await page.goto("/imports");
  await page.getByLabel(/full local path/).fill(process.env.E2E_LEGACY_SOURCE!);
  await page.getByRole("button", { name: "Prepare read-only review" }).click();
  await expect(page.getByText(/Review complete. Both originals/)).toBeVisible();
});

test("a STOP reply blocks contact at once and only suppresses after a human confirms", async ({
  page,
}) => {
  await page.goto("/leads?search=Jordan");
  await page.getByRole("link", { name: /Jordan Ellis/ }).first().click();
  await expect(
    page.getByRole("heading", { name: "Jordan Ellis" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Analysis & drafts" }).click();
  await page
    .getByLabel("Seller reply text")
    .fill("STOP - please do not text me again");
  await page.getByRole("button", { name: "Record reply" }).click();
  await expect(
    page.getByText(/The cadence for this lead is paused/),
  ).toBeVisible();

  // The block is immediate; the suppression list is still a decision.
  await page.reload();
  await expect(page.getByText(/Do Not Contact/).first()).toBeVisible();
  await page.getByRole("tab", { name: "Analysis & drafts" }).click();
  await expect(
    page.getByText("Do Not Contact: marketing follow-up drafts are blocked."),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Suggested next actions" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Confirm" }).first().click();
  await expect(
    page.getByText(/Suggestion applied. Nothing was sent./),
  ).toBeVisible();

  await page.goto("/safety");
  await expect(
    page.getByRole("cell", { name: /2025550101/ }),
  ).toBeVisible();
  // Nothing in the workspace can send: there is no send control to press.
  await expect(page.getByRole("button", { name: /^send/i })).toHaveCount(0);
});

test("bulk restriction review unlocks a tier of drafts without sending anything", async ({
  page,
}) => {
  await page.goto("/imports");
  // Plain columns only: a distress-scored export asks the review screen for decisions
  // that this scenario is not about. Without a score the lead lands in tier P3.
  const csv =
    "Full Name,Phone,Property Address,City,State,ZIP,County,DNC\n" +
    "Nadia Tier,2025550188,4200 Tier Two Lane,Arlington,TX,76015,Tarrant,no\n";
  await page.getByLabel("Upload lead file").setInputFiles({
    name: "e2e-tier-p1.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await page.getByRole("button", { name: "Normalize & preview" }).click();
  await expect(
    page.getByRole("heading", { name: "Review normalized records" }),
  ).toBeVisible();
  await page
    .getByRole("row")
    .filter({ hasText: "Nadia Tier" })
    .getByRole("checkbox")
    .check();
  const approve = page.getByRole("button", {
    name: "Review & approve local import",
  });
  await expect(approve).toBeEnabled();
  await approve.click();
  await page
    .getByRole("textbox", { name: "Type IMPORT LOCAL to confirm" })
    .fill("IMPORT LOCAL");
  await page.getByRole("button", { name: "Approve local writes" }).click();
  // A dialog left open means the import was refused; say why instead of timing out.
  const stuck = page.getByRole("dialog");
  await stuck
    .waitFor({ state: "detached", timeout: 10000 })
    .catch(async () => {
      const screen = await page.evaluate(
        () => (document.querySelector("main") as HTMLElement).innerText,
      );
      throw new Error(`Import dialog still open: ${screen.slice(0, 3000)}`);
    });

  // A brand-new lead cannot be drafted until a person records a contact review.
  await page.goto("/drafts");
  await page.getByRole("combobox", { name: "Priority tier" }).selectOption("P3");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Generate drafts" }).click();
  await expect(
    page.getByText(/No lead in this selection can receive a draft|Blocked by a gate/),
  ).toBeVisible();

  await page.goto("/leads?search=Nadia");
  await page.getByRole("checkbox", { name: "Select Nadia Tier" }).check();
  await page
    .getByRole("button", { name: "Review contact restrictions" })
    .click();
  await page
    .getByRole("textbox", { name: /What did you check/ })
    .fill("Screened the vendor list for opt-outs before import on 2026-10-29.");
  await page
    .getByRole("textbox", { name: /Type REVIEW RESTRICTIONS/ })
    .fill("REVIEW RESTRICTIONS");
  await page.getByRole("button", { name: "Apply to 1 lead(s)" }).click();
  await expect(page.getByText(/1 reviewed/)).toBeVisible();
  await page.getByRole("button", { name: "Done" }).click();

  await page.goto("/drafts");
  await page.getByRole("combobox", { name: "Priority tier" }).selectOption("P3");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Generate drafts" }).click();
  await expect(page.getByText("Requested", { exact: true })).toBeVisible();
  await expect(page.getByText("Generated", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Nadia Tier" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^send/i })).toHaveCount(0);
});

test("skip-trace results only change the fields they matched, after the typed phrase", async ({
  page,
}) => {
  await page.goto("/imports");
  const propertyOnly =
    'Property Address,Beds Baths and Sqft,MV\n"4300 Skip Trace Lane, Arlington, TX 76015",3 beds 2 baths 1800 sqft,250k Redfin\n';
  await page.getByLabel("Upload lead file").setInputFiles({
    name: "e2e-skip-trace-source.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(propertyOnly),
  });
  await page.getByRole("button", { name: "Normalize & preview" }).click();
  await expect(
    page.getByRole("heading", { name: "Review normalized records" }),
  ).toBeVisible();
  await page
    .getByRole("row")
    .filter({ hasText: "4300 Skip Trace Lane" })
    .getByRole("checkbox")
    .check();
  const approve = page.getByRole("button", {
    name: "Review & approve local import",
  });
  await expect(approve).toBeEnabled();
  await approve.click();
  await page
    .getByRole("textbox", { name: "Type IMPORT LOCAL to confirm" })
    .fill("IMPORT LOCAL");
  await page.getByRole("button", { name: "Approve local writes" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.goto("/skip-trace");
  const results =
    "address,city,state,zip,owner_name,phone1\n" +
    "4300 Skip Trace Lane,Arlington,TX,76015,Marcia Owner,(202) 555-0177\n" +
    "9999 Unmatched Road,Nowhere,TX,70000,Nobody Real,(555) 555-5555\n";
  await page.getByLabel("Skip-trace results file").setInputFiles({
    name: "e2e-skip-trace-results.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(results),
  });
  await expect(page.getByText("1 matched", { exact: true })).toBeVisible();
  await expect(page.getByText("1 rejected", { exact: true })).toBeVisible();

  const apply = page.getByRole("button", { name: "Apply matched results" });
  await expect(apply).toBeDisabled();
  await page
    .getByRole("textbox", { name: /Type IMPORT LOCAL to apply/ })
    .fill("IMPORT LOCAL");
  await expect(apply).toBeEnabled();
  await apply.click();
  await expect(page.getByText(/1 lead\(s\) updated/)).toBeVisible();

  await page.goto("/leads?search=Marcia");
  await expect(
    page.getByRole("link", { name: /Marcia Owner/ }).first(),
  ).toBeVisible();
  await page.getByRole("link", { name: /Marcia Owner/ }).first().click();
  await expect(
    page.getByRole("heading", { name: "Marcia Owner" }),
  ).toBeVisible();
  await expect(page.getByText(/202/).first()).toBeVisible();
});
