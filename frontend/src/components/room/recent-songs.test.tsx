import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { Toaster } from "@/components/ui/toaster";
import { clearMemberData } from "@/lib/resources";
import { fakeApi } from "@/test/api";

import { RecentSongs } from "./recent-songs";

const songs = { for_me: null, from_me: null, playlist: [] };

function track(key: string, title: string) {
  return {
    key,
    title,
    artist_names: ["Juniper Lane"],
    artwork_url: null,
    track_url: `https://open.spotify.com/track/${key}`,
    played_at: new Date(Date.now() - 4 * 60_000).toISOString(),
    played_on: null,
  };
}

function member(isMe: boolean, state: string, tracks: unknown[] = []) {
  return { user_id: isMe ? "me" : "them", is_me: isMe, state, source: state === "ok" ? "spotify" : null, tracks };
}

describe("RecentSongs", () => {
  beforeEach(() => clearMemberData());

  it("shows both lists and sends one of my songs to the other member", async () => {
    const user = userEvent.setup();
    const { calls } = fakeApi({
      "GET /api/v1/room/recent": {
        body: { me: member(true, "ok", [track("mine1", "Paper Lanterns")]), partner: member(false, "ok", [track("hers1", "Window Seat")]) },
      },
      "PUT /api/v1/room/songs/pick": { body: songs },
      "GET /api/v1/room/songs": { body: songs },
    });
    render(
      <>
        <RecentSongs partnerName="Sam" />
        <Toaster />
      </>,
    );
    const theirs = await screen.findByRole("list", { name: "Sam's recent songs" });
    expect(within(theirs).getByText("Window Seat")).toBeInTheDocument();
    expect(within(theirs).queryByRole("button")).toBeNull(); // only my own songs can be shared

    await user.click(screen.getByRole("button", { name: "Share Paper Lanterns" }));
    await user.click(await screen.findByRole("button", { name: "For Sam" }));
    expect(await screen.findByText("Sent to Sam.")).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT" && c.path === "/api/v1/room/songs/pick")?.body).toEqual({ key: "mine1" }),
    );
  });

  it("hides what is not shared and asks Spotify again for an older grant", async () => {
    fakeApi({
      "GET /api/v1/room/recent": { body: { me: member(true, "needs_permission"), partner: member(false, "private") } },
    });
    render(<RecentSongs partnerName="Sam" />);
    expect(await screen.findByRole("button", { name: "Show my recent songs" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Sam's recent songs" })).toBeNull();
  });
});
