import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Toaster } from "@/components/ui/toaster";
import { clearMemberData } from "@/lib/resources";
import { fakeApi } from "@/test/api";

import { Tulips } from "./tulips";

const empty = { items: [], unseen_count: 0 };

function renderTulips() {
  return render(
    <>
      <Tulips partnerName="Sam" />
      <Toaster />
    </>,
  );
}

describe("Tulips", () => {
  beforeEach(() => clearMemberData());

  it("sends a tulip and confirms it", async () => {
    const user = userEvent.setup();
    const { calls } = fakeApi({
      "GET /api/v1/room/tulips": { body: empty },
      "POST /api/v1/room/tulips": { status: 201, body: { id: "t1", direction: "sent", created_at: "2026-10-25T12:00:00Z", is_new: false } },
    });
    renderTulips();
    await user.click(screen.getByRole("button", { name: "Send a tulip" }));
    expect(await screen.findByText("Tulip sent to Sam.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/v1/room/tulips")).toBe(true);
  });

  it("announces a tulip that arrived, once, and marks it seen", async () => {
    const received = {
      items: [{ id: "t9", direction: "received", created_at: "2026-10-25T12:00:00Z", is_new: true }],
      unseen_count: 1,
    };
    const { calls } = fakeApi({
      "GET /api/v1/room/tulips": { body: received },
      "POST /api/v1/room/tulips/seen": { body: { unseen_count: 0, items: [{ ...received.items[0], is_new: false }] } },
    });
    renderTulips();
    expect(await screen.findByText("Sam sent you a tulip.")).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/room/tulips/seen")).toBe(true));
  });
});
