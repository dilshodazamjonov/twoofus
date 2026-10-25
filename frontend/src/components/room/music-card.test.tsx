import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { describePlayback } from "@/lib/copy/playback";
import { NOW, member, playback } from "@/test/fixtures";

import { MusicCard } from "./music-card";

function renderCard(overrides: Parameters<typeof member>[0] = {}, clientStale = false) {
  const m = member(overrides);
  const view = describePlayback({ playback: m.playback, isMe: m.is_me, clientStale, nowMs: NOW });
  return render(<MusicCard member={m} view={view} serverOffsetMs={0} partnerName="Alex" />);
}

describe("MusicCard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it("attributes Spotify with its logo and links back to the track", () => {
    renderCard();
    expect(screen.getByRole("heading", { name: "Sam" })).toBeInTheDocument();
    expect(screen.getByText("Playing")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Spotify" })).toHaveAttribute("src", "/brand/spotify/Full_Logo_Black_RGB.svg");
    const link = screen.getByRole("link", { name: /Play on Spotify/ });
    expect(link).toHaveAttribute("href", "https://open.spotify.com/track/123");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    const cover = screen.getByRole("img", { name: "Cover of Small Hours" });
    expect(cover).toHaveAttribute("referrerpolicy", "no-referrer");
  });

  it("labels the estimated progress honestly", () => {
    renderCard();
    const bar = screen.getByRole("progressbar", { name: "Position in the song" });
    expect(bar).toHaveAttribute("aria-valuetext", "About 1 minute 5 seconds of 3 minutes 34 seconds, estimated");
    expect(screen.getByText("estimated")).toBeInTheDocument();
  });

  it("shows stale data as last confirmed, without progress", () => {
    renderCard({ playback: playback({ is_stale: true, progress_ms: null, detail_code: "provider_unreachable" }) });
    expect(screen.queryByText("Playing")).not.toBeInTheDocument();
    expect(screen.getByText(/^Last confirmed/)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("names Yandex and marks DEMO as demo", () => {
    const { unmount } = renderCard({
      playback: playback({ source: "yandex", experimental: true, track_url: "https://music.yandex.ru/album/1/track/2" }),
    });
    expect(screen.getByText("Yandex Music")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open in Yandex Music/ })).toBeInTheDocument();
    unmount();

    renderCard({ playback: playback({ source: "demo", is_demo: true, track_url: null, artwork_url: "/demo/cover-1.svg" }) });
    expect(screen.getByText("Demo")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows a private partner without any song details", () => {
    renderCard({
      sharing_enabled: false,
      playback: playback({
        source: null,
        status: "private",
        detail_code: "sharing_off",
        track_title: null,
        artist_names: [],
        album: null,
        artwork_url: null,
        track_url: null,
      }),
    });
    expect(screen.getByText("Not sharing")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Cover/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Spotify" })).not.toBeInTheDocument();
  });

  it("tells me whether my own card is visible to my person", () => {
    renderCard({ is_me: true, display_name: "Alex", sharing_enabled: false });
    expect(screen.getByText(/Not shared/)).toBeInTheDocument();
  });
});
