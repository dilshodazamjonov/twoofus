import { describe, expect, it } from "vitest";

import { safeNextPath } from "./safe-next";

describe("safeNextPath", () => {
  it.each([
    ["/room", "/room"],
    ["/settings?tab=1", "/settings?tab=1"],
    ["/connect/x", "/connect/x"],
  ])("allows our own page %s", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([null, "", "//evil.example", "https://evil.example/room", "/\\evil.example", "/api/v1/me", "/roomy", "javascript:alert(1)"])(
    "falls back for %s",
    (input) => {
      expect(safeNextPath(input)).toBe("/room");
    },
  );
});
