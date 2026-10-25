import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { clearMemberData } from "@/lib/resources";
import { fakeApi } from "@/test/api";

import { ForYou } from "./for-you";
import { Playlist } from "./playlist";

const yandexSong = {
  provider: "yandex",
  title: "Hotel California",
  artist_names: ["Eagles"],
  artwork_url: null,
  track_url: "https://music.yandex.ru/album/1/track/2",
  created_at: "2026-10-26T10:00:00Z",
};

describe("Songs shared on purpose", () => {
  beforeEach(() => clearMemberData());

  it("shows the song picked for me, with a way to find it on my own service", async () => {
    fakeApi({ "GET /api/v1/room/songs": { body: { for_me: yandexSong, from_me: null, playlist: [] } } });
    render(<ForYou partnerName="Sam" mine="spotify" />);
    expect(await screen.findByRole("heading", { name: "From Sam" })).toBeInTheDocument();
    const find = screen.getByRole("link", { name: /Find on Spotify/ });
    expect(find).toHaveAttribute("href", "https://open.spotify.com/search/Hotel%20California%20Eagles");
  });

  it("lists the playlist and lets either member remove a song", async () => {
    const user = userEvent.setup();
    const entry = { id: "p1", song: yandexSong, added_by_me: false };
    const { calls } = fakeApi({
      "GET /api/v1/room/songs": { body: { for_me: null, from_me: null, playlist: [entry] } },
      "DELETE /api/v1/room/songs/playlist/p1": { body: { for_me: null, from_me: null, playlist: [] } },
    });
    render(<Playlist mine="yandex" />);
    expect(await screen.findByText("Hotel California")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Find in Yandex Music/ })).toBeNull(); // already mine
    await user.click(screen.getByRole("button", { name: "Remove Hotel California" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});
