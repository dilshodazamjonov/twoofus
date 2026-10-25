// What a music card says in every state. Pure, so it is unit-tested.
// One short line per state; stale data is never presented as current.
import type { PlaybackOut } from "@/lib/api/types";
import { formatRelative } from "@/lib/format";
import { PROVIDERS } from "@/lib/providers";

export type CardKind = "track" | "non_music" | "idle" | "private" | "not_connected" | "unavailable" | "error";

export type CardView = {
  kind: CardKind;
  /** Status in the card's corner ("Playing", "Paused", "Last confirmed …"). */
  status?: string;
  /** Show the "listening" pulse: genuinely playing and fresh. */
  live: boolean;
  /** Data is not current: never present it as playing now. */
  stale: boolean;
  /** One short line for states without a song. */
  message?: string;
  action?: { label: string; href: string };
  tone: "calm" | "attention";
};

export type DescribeInput = {
  playback: PlaybackOut;
  isMe: boolean;
  /** Our own polling has not succeeded for a while. */
  clientStale: boolean;
  /** Client clock, corrected to server time. */
  nowMs: number;
};

function serviceName(playback: PlaybackOut): string {
  return playback.source ? PROVIDERS[playback.source].label : "The music service";
}

function troubleReason(playback: PlaybackOut, clientStale: boolean): string {
  const service = serviceName(playback);
  switch (playback.detail_code) {
    case "provider_rate_limited":
      return `${service} asked to slow down`;
    case "provider_quota_exceeded":
      return `${service} request limit reached`;
    case "provider_unreachable":
      return `${service} isn't responding`;
    default:
      return clientStale ? "Can't reach the server" : `${service} isn't responding`;
  }
}

export function describePlayback({ playback, isMe, clientStale, nowMs }: DescribeInput): CardView {
  const service = serviceName(playback);
  const fetchedAt = playback.fetched_at ? Date.parse(playback.fetched_at) : null;
  const stale = playback.is_stale || clientStale;
  const confirmed = fetchedAt !== null ? `Last confirmed ${formatRelative(fetchedAt, nowMs)}` : "Not confirmed";

  switch (playback.status) {
    case "playing":
    case "paused": {
      if (playback.detail_code === "non_music_content" || playback.detail_code === "incomplete_metadata") {
        return {
          kind: "non_music",
          status: stale ? confirmed : playback.status === "playing" ? "Playing" : "Paused",
          live: playback.status === "playing" && !stale,
          stale,
          message: playback.detail_code === "non_music_content" ? "Something other than music" : "Unknown track",
          tone: "calm",
        };
      }
      if (stale) {
        return { kind: "track", status: confirmed, live: false, stale: true, tone: "attention" };
      }
      return {
        kind: "track",
        status: playback.status === "playing" ? "Playing" : "Paused",
        live: playback.status === "playing",
        stale: false,
        tone: "calm",
      };
    }
    case "idle":
      return {
        kind: "idle",
        status: stale ? confirmed : undefined,
        live: false,
        stale,
        message: "Not playing",
        tone: "calm",
      };
    case "private":
      if (playback.detail_code === "sharing_off") {
        return { kind: "private", live: false, stale: false, message: "Not sharing", tone: "calm" };
      }
      // A private listening session at the provider (possibly last confirmed a while ago).
      return {
        kind: "private",
        status: stale ? confirmed : undefined,
        live: false,
        stale,
        message: "Private session",
        tone: "calm",
      };
    case "not_connected":
      return {
        kind: "not_connected",
        live: false,
        stale: false,
        message: "Not connected",
        action: isMe ? { label: "Connect", href: "/connect" } : undefined,
        tone: "calm",
      };
    case "unavailable":
      return {
        kind: "unavailable",
        live: false,
        stale,
        message: troubleReason(playback, clientStale),
        tone: "attention",
      };
    case "error":
    default:
      return describeError(playback, isMe, service);
  }
}

function describeError(playback: PlaybackOut, isMe: boolean, service: string): CardView {
  const base = { kind: "error" as const, live: false, stale: false, tone: "attention" as const };
  if (!isMe) return { ...base, message: "Unavailable" };
  switch (playback.detail_code) {
    case "provider_reauth_required":
      return {
        ...base,
        message: "Reconnect needed",
        action: { label: `Reconnect ${service}`, href: "/connect" },
      };
    case "provider_forbidden":
      return { ...base, message: `${service} refused access` };
    case "provider_not_configured":
      return { ...base, message: `${service} isn't set up on this server` };
    default:
      return { ...base, message: `${service} error, retrying` };
  }
}
