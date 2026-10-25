import { describe, expect, it } from "vitest";

import { disconnectMessage } from "./connection-status";

describe("disconnectMessage", () => {
  it("says what the provider confirmed", () => {
    expect(disconnectMessage("Yandex Music", "revoked")).toContain("confirmed the sign-in is cancelled");
    expect(disconnectMessage("Yandex Music", "failed")).toContain("id.yandex.ru");
    expect(disconnectMessage("Spotify", "not_supported")).toContain("spotify.com/account/apps");
    expect(disconnectMessage("Demo", "not_applicable")).toBe("Demo disconnected. Our copy of its access was deleted.");
  });
});
