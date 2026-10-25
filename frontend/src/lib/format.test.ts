import { describe, expect, it } from "vitest";

import { firstName, formatDuration, formatDurationSpoken, formatRelative } from "./format";

describe("format", () => {
  it("formats durations", () => {
    expect(formatDuration(187_000)).toBe("3:07");
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(3_725_000)).toBe("1:02:05");
    expect(formatDurationSpoken(187_000)).toBe("3 minutes 7 seconds");
    expect(formatDurationSpoken(60_000)).toBe("1 minute");
    expect(formatDurationSpoken(1_000)).toBe("1 second");
  });

  it("formats relative times", () => {
    const now = Date.parse("2026-10-25T12:00:00Z");
    expect(formatRelative(now - 10_000, now, "en")).toBe("just now");
    expect(formatRelative(now - 3 * 60_000, now, "en")).toBe("3 min. ago");
    expect(formatRelative(now - 2 * 3_600_000, now, "en")).toBe("2 hr. ago");
    expect(formatRelative(now - 26 * 3_600_000, now, "en")).toBe("yesterday");
    expect(formatRelative(now + 5_000, now, "en")).toBe("just now"); // clock skew never shows "in 5 s"
  });

  it("shortens names", () => {
    expect(firstName("  Sam   Lee ")).toBe("Sam");
  });
});
