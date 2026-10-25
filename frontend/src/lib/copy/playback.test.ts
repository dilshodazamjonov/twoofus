import { describe, expect, it } from "vitest";

import { NOW, playback } from "@/test/fixtures";

import { describePlayback } from "./playback";

const base = { isMe: false, clientStale: false, nowMs: NOW };

describe("describePlayback", () => {
  it("shows a fresh playing song as live", () => {
    const view = describePlayback({ ...base, playback: playback() });
    expect(view).toMatchObject({ kind: "track", status: "Playing", live: true, stale: false });
  });

  it("shows paused without the listening pulse", () => {
    const view = describePlayback({ ...base, playback: playback({ status: "paused", is_playing: false }) });
    expect(view).toMatchObject({ kind: "track", status: "Paused", live: false });
  });

  it("never calls stale data 'Playing'", () => {
    const stale = describePlayback({
      ...base,
      playback: playback({ is_stale: true, detail_code: "provider_rate_limited", progress_ms: null }),
    });
    expect(stale.status).toMatch(/^Last confirmed/);
    expect(stale.live).toBe(false);
    expect(stale.stale).toBe(true);

    const offline = describePlayback({ ...base, clientStale: true, playback: playback() });
    expect(offline.status).toMatch(/^Last confirmed/);
    expect(offline.live).toBe(false);
  });

  it("is gentle about a partner who isn't sharing", () => {
    const view = describePlayback({
      ...base,
      playback: playback({ source: null, status: "private", detail_code: "sharing_off", track_title: null }),
    });
    expect(view.kind).toBe("private");
    expect(view.message).toBe("Not sharing");
    expect(view.tone).toBe("calm");
  });

  it("explains a private listening session", () => {
    const view = describePlayback({
      ...base,
      isMe: true,
      playback: playback({ status: "private", detail_code: "provider_private_session", track_title: null }),
    });
    expect(view.message).toBe("Private session");
  });

  it("keeps a stale private session private, and never blames sharing", () => {
    const view = describePlayback({
      ...base,
      isMe: true,
      playback: playback({ status: "private", detail_code: "provider_unreachable", is_stale: true, track_title: null }),
    });
    expect(view.kind).toBe("private");
    expect(view.status).toMatch(/^Last confirmed/);
    expect(view.message).toBe("Private session");
  });

  it("offers to connect only on my own card", () => {
    const notConnected = playback({ source: null, status: "not_connected", detail_code: "not_connected", track_title: null });
    expect(describePlayback({ ...base, isMe: true, playback: notConnected }).action).toEqual({
      label: "Connect",
      href: "/connect",
    });
    expect(describePlayback({ ...base, playback: notConnected }).action).toBeUndefined();
  });

  it("asks me (not my partner) to reconnect", () => {
    const reauth = playback({ status: "error", detail_code: "provider_reauth_required", track_title: null });
    const mine = describePlayback({ ...base, isMe: true, playback: reauth });
    expect(mine.action?.label).toBe("Reconnect Spotify");
    const theirs = describePlayback({ ...base, playback: reauth });
    expect(theirs.action).toBeUndefined();
    expect(theirs.message).toBe("Unavailable");
  });

  it("keeps non-music content private", () => {
    const view = describePlayback({
      ...base,
      playback: playback({ content_type: "episode", detail_code: "non_music_content", track_title: null }),
    });
    expect(view.kind).toBe("non_music");
    expect(view.message).toBe("Something other than music");
  });

  it("says when nothing is playing", () => {
    const idle = playback({ status: "idle", detail_code: "nothing_playing", track_title: null, is_playing: false });
    expect(describePlayback({ ...base, playback: idle }).message).toBe("Not playing");
  });

  it("explains temporary provider trouble", () => {
    const view = describePlayback({
      ...base,
      playback: playback({ status: "unavailable", detail_code: "provider_rate_limited", track_title: null }),
    });
    expect(view.message).toBe("Spotify asked to slow down");
    expect(view.tone).toBe("attention");
  });
});
