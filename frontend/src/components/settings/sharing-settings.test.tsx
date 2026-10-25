import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { clearMemberData, configResource } from "@/lib/resources";
import { SHARING_NOTICE_VERSION } from "@/lib/sharing-notice";
import { fakeApi } from "@/test/api";

import { SharingSettings } from "./sharing-settings";

const config = {
  app_name: "JustTheTwoOfUs",
  environment: "test",
  demo_mode: false,
  demo_controls: false,
  providers: {},
  now_playing_ttl_seconds: 20,
  sharing_notice_version: SHARING_NOTICE_VERSION,
  api_version: "1",
};
const room = {
  id: "r",
  app_name: "JustTheTwoOfUs",
  capacity: 2,
  members: [
    { id: "1", display_name: "Alex", role: "owner", is_me: true, joined_at: "2026-10-25T10:00:00Z", sharing_enabled: false, provider: null },
    { id: "2", display_name: "Sam Lee", role: "partner", is_me: false, joined_at: "2026-10-25T11:00:00Z", sharing_enabled: true, provider: "yandex" },
  ],
  invitation: null,
};

function sharing(on: boolean, acknowledged: string | null) {
  return {
    share_now_playing: on,
    current_notice_version: SHARING_NOTICE_VERSION,
    notice_version_acknowledged: acknowledged,
    acknowledged_at: acknowledged ? "2026-10-25T12:00:00Z" : null,
    updated_at: "2026-10-25T12:00:00Z",
  };
}

describe("SharingSettings", () => {
  beforeEach(() => {
    clearMemberData();
    configResource.reset();
  });

  it("asks for informed consent before sharing, and stops instantly", async () => {
    const user = userEvent.setup();
    const { calls } = fakeApi({
      "GET /api/v1/config": { body: config },
      "GET /api/v1/room": { body: room },
      "GET /api/v1/me/sharing": { body: sharing(false, null) },
      "PUT /api/v1/me/sharing": ({ body }) => {
        const on = (body as { share_now_playing: boolean }).share_now_playing;
        return { body: sharing(on, SHARING_NOTICE_VERSION) };
      },
      "GET /api/v1/room/now-playing": { status: 401, body: { error: { code: "not_authenticated", message: "" } } },
    });
    render(<SharingSettings />);
    const toggle = await screen.findByRole("switch", { name: "Share my music with Sam" });
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(toggle).toHaveAttribute("aria-checked", "false");

    await user.click(toggle);
    expect(screen.getByRole("heading", { name: "Share your music?" })).toBeInTheDocument();
    expect(screen.getByText(/Sam will see the song you're playing/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false); // nothing changes before consent

    await user.click(screen.getByRole("button", { name: "Start sharing" }));
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body).toEqual({ share_now_playing: true, acknowledged_notice_version: SHARING_NOTICE_VERSION });

    await user.click(toggle); // turning off needs no dialog
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    expect(calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({
      share_now_playing: false,
      acknowledged_notice_version: null,
    });
  });

  it("refuses to switch on when app and server disagree about the notice", async () => {
    fakeApi({
      "GET /api/v1/config": { body: { ...config, sharing_notice_version: "2099-01-01" } },
      "GET /api/v1/room": { body: room },
      "GET /api/v1/me/sharing": { body: sharing(false, null) },
    });
    render(<SharingSettings />);
    expect(await screen.findByText("Please reload the app.")).toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeDisabled();
  });
});
