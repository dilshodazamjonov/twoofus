import { describe, expect, it } from "vitest";

import { parseInviteToken } from "./invite-token";

describe("parseInviteToken", () => {
  it("reads the token from the fragment", () => {
    expect(parseInviteToken("#token=test-fake-invite-xxxxx")).toBe("test-fake-invite-xxxxx");
  });

  it("rejects missing or malformed tokens", () => {
    expect(parseInviteToken("")).toBeNull();
    expect(parseInviteToken("#token=short")).toBeNull();
    expect(parseInviteToken("#token=<script>alert(1)</script>xxxxxxxx")).toBeNull();
  });
});
