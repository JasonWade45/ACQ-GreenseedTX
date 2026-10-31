import { describe, expect, it } from "vitest";
import type { FollowupWorkbenchItem } from "./types";
import { createMessage, getSellerName } from "./pages/FollowupHub";

function makeItem({
  fullName = "Maria Lopez",
  firstName = "Maria",
  lastName = "Lopez",
  sentCount = 0,
  lastActivity = null,
}: {
  fullName?: string;
  firstName?: string | null;
  lastName?: string | null;
  sentCount?: number;
  lastActivity?: FollowupWorkbenchItem["last_activity"];
} = {}): FollowupWorkbenchItem {
  return {
    lead: {
      full_name: fullName,
      first_name: firstName,
      last_name: lastName,
      properties: [
        {
          street_address: "6021 Driscoll Ln",
          city: "Aubrey",
          state: "TX",
          zip_code: "76227",
        },
      ],
    },
    last_activity: lastActivity,
    followup: null,
    sent_count: sentCount,
  } as unknown as FollowupWorkbenchItem;
}

describe("follow-up identity and message copy", () => {
  it("uses recorded seller names and does not mistake Owner for a real name", () => {
    expect(getSellerName(makeItem().lead)).toBe("Maria Lopez");
    expect(
      getSellerName(
        makeItem({ fullName: "Owner", firstName: null, lastName: null }).lead,
      ),
    ).toBeNull();
    expect(
      getSellerName(
        makeItem({ fullName: "Owner", firstName: "Maria", lastName: "Lopez" }).lead,
      ),
    ).toBe("Maria Lopez");
    expect(
      getSellerName(
        makeItem({
          fullName: "Owner — 1320 Beech Chapel Rd",
          firstName: "Owner",
          lastName: null,
        }).lead,
      ),
    ).toBeNull();
    expect(
      createMessage(
        makeItem({
          fullName: "Owner — 1320 Beech Chapel Rd",
          firstName: "Owner",
          lastName: null,
        }),
      ).startsWith("Hi there,\n"),
    ).toBe(true);
  });

  it("greets the seller before naming the property and uses the approved first-touch identity", () => {
    const message = createMessage(makeItem());
    expect(message.startsWith("Hi Maria,")).toBe(true);
    expect(message.indexOf("GreenSeedTX LLC")).toBeLessThan(
      message.indexOf("6021 Driscoll Ln, Aubrey, TX, 76227"),
    );
    expect(message).toContain("I’m Jason Wade, the Acquisition Manager");
    expect(message).toContain("GreenSeedTX LLC");
    expect(message).toContain("Would you be open to selling the property at 6021 Driscoll Ln");
    expect(message).not.toContain("still interested");
  });

  it("keeps Jason's name out of later touches and asks whether they are still interested", () => {
    const message = createMessage(makeItem({ sentCount: 1 }));
    expect(message).toContain("GreenSeedTX LLC");
    expect(message).toContain("Are you still interested in selling the property at 6021 Driscoll Ln");
    expect(message).not.toContain("Jason Wade");
    expect(message).not.toContain("Acquisition Manager");
  });

  it("keeps the still-interested question while using recorded outbound context", () => {
    const message = createMessage(makeItem({
      sentCount: 1,
      lastActivity: {
        id: 2,
        external_id: null,
        lead_id: 1,
        activity_type: "message",
        direction: "outbound",
        outcome: null,
        occurred_at: "2026-10-30T12:00:00Z",
        recorded_at: "2026-10-30T12:00:00Z",
        source: "followup_hub",
        summary: "Initial outreach recorded",
        source_metadata: { followup_hub_touch: true },
      },
    }));
    expect(message).toContain("checking back on my last message");
    expect(message).toContain("Are you still interested in selling the property at 6021 Driscoll Ln");
  });
});
