import type { MemberNowPlayingOut, PlaybackOut, RoomNowPlayingOut } from "@/lib/api/types";

export const NOW = Date.parse("2026-10-25T12:00:00Z");

export function playback(overrides: Partial<PlaybackOut> = {}): PlaybackOut {
  return {
    source: "spotify",
    status: "playing",
    detail_code: null,
    content_type: "track",
    track_title: "Paper Lanterns",
    artist_names: ["Juniper Lane"],
    album: "Small Hours",
    artwork_url: "https://i.scdn.co/image/abc",
    track_url: "https://open.spotify.com/track/123",
    duration_ms: 214_000,
    progress_ms: 60_000,
    is_playing: true,
    fetched_at: new Date(NOW - 5_000).toISOString(),
    last_changed_at: null,
    is_stale: false,
    is_demo: false,
    experimental: false,
    ...overrides,
  };
}

export function member(overrides: Partial<MemberNowPlayingOut> = {}): MemberNowPlayingOut {
  return {
    user_id: "00000000-0000-4000-8000-000000000002",
    display_name: "Sam",
    is_me: false,
    sharing_enabled: true,
    playback: playback(),
    ...overrides,
  };
}

export function roomNowPlaying(overrides: Partial<RoomNowPlayingOut> = {}): RoomNowPlayingOut {
  return {
    generated_at: new Date(NOW).toISOString(),
    poll_after_seconds: 20,
    me: member({ user_id: "00000000-0000-4000-8000-000000000001", display_name: "Alex", is_me: true }),
    partner: member(),
    partner_joined: true,
    ...overrides,
  };
}
