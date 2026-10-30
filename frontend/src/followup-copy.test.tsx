import { describe, expect, it } from "vitest";
import type { FollowupWorkbenchItem } from "./types";
import { createMessage, getSellerName } from "./pages/FollowupHub";

function makeItem({
  fullName = "Maria Lopez",
  firstName = "Maria",
  lastName = "Lopez",
  sentCount = 0,
}: {
  fullName?: string;
  firstName?: string | null;
  lastName?: string | null;
  sentCount?: number;
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
    last_activity: null,
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

  it("keeps Jason's name out of later touches", () => {
    const message = createMessage(makeItem({ sentCount: 1 }));
    expect(message).toContain("GreenSeedTX LLC");
    expect(message).toContain("Are you still interested in selling the property at 6021 Driscoll Ln");
    expect(message).not.toContain("Jason Wade");
    expect(message).not.toContain("Acquisition Manager");
  });
});
