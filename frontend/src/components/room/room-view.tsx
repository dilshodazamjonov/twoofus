"use client";

import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { MemberNowPlayingOut, RoomNowPlayingOut } from "@/lib/api/types";
import { describePlayback, type CardView } from "@/lib/copy/playback";
import { firstName, formatClock, formatRelative } from "@/lib/format";
import { nowPlayingPoller, pollIntervalMs, roomResource } from "@/lib/resources";
import { useNow } from "@/lib/store/now";
import { usePoller, type PollState } from "@/lib/store/poller";
import { useResource } from "@/lib/store/resource";

import { InviteCard } from "./invite-card";
import { MusicCard } from "./music-card";
import { Tulips } from "./tulips";

export function RoomView() {
  const nowPlaying = usePoller(nowPlayingPoller);
  const room = useResource(roomResource);
  const now = useNow(15_000);
  const data = nowPlaying.data;

  if (!data) {
    return nowPlaying.status === "error" ? <LoadError onRetry={() => nowPlayingPoller.refresh()} /> : <RoomSkeleton />;
  }

  const intervalMs = pollIntervalMs(data.poll_after_seconds);
  const receivedAt = nowPlaying.receivedAt ?? 0;
  // Server minus client clock, so estimates don't depend on the phone's clock being right.
  const serverOffsetMs = Date.parse(data.generated_at) - receivedAt;
  const clientStale = now !== null && now - receivedAt > Math.max(2 * intervalMs, 60_000);
  const serverNow = (now ?? receivedAt) + serverOffsetMs;

  const me = data.me;
  const partner = data.partner;
  const partnerName = partner ? firstName(partner.display_name) : null;
  const describe = (member: MemberNowPlayingOut): CardView =>
    describePlayback({
      playback: member.playback,
      isMe: member.is_me,
      clientStale,
      nowMs: serverNow,
    });
  const partnerView = partner ? describe(partner) : null;
  const isOwner = room.data?.members.find((m) => m.is_me)?.role === "owner";

  return (
    <div className="space-y-6 md:space-y-8">
      <h1 className="sr-only">Now playing</h1>
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 md:gap-8">
        {partner && partnerView ? (
          <MusicCard member={partner} view={partnerView} serverOffsetMs={serverOffsetMs} />
        ) : null}
        <MusicCard member={me} view={describe(me)} serverOffsetMs={serverOffsetMs} partnerName={partnerName} />
        {partner ? null : (
          <InviteCard isOwner={isOwner} invitationPending={room.data?.invitation?.pending ?? false} />
        )}
      </div>

      <SongChangeAnnouncer partner={partner} view={partnerView} />
      <FreshnessLine state={nowPlaying} now={now} clientStale={clientStale} />
      {partnerName ? <Tulips partnerName={partnerName} /> : null}
    </div>
  );
}

/** Tells screen readers when the partner's song changes (and nothing else). */
function SongChangeAnnouncer({ partner, view }: { partner: MemberNowPlayingOut | null; view: CardView | null }) {
  const [message, setMessage] = useState("");
  const last = useRef<string | null>(null);
  const title = partner?.playback.track_title ?? null;
  const live = view?.kind === "track" && !view.stale;
  const key = live && title ? `${title}|${partner?.playback.artist_names.join(",")}` : null;

  useEffect(() => {
    if (key === last.current) return;
    const first = last.current === null;
    last.current = key;
    if (first || !key || !partner) return;
    const text = `${firstName(partner.display_name)} is now listening to ${title}${
      partner.playback.artist_names.length ? ` by ${partner.playback.artist_names.join(", ")}` : ""
    }.`;
    const timer = window.setTimeout(() => setMessage(text), 0);
    return () => window.clearTimeout(timer);
  }, [key, partner, title]);

  return (
    <p className="sr-only" aria-live="polite">
      {message}
    </p>
  );
}

function FreshnessLine({
  state,
  now,
  clientStale,
}: {
  state: PollState<RoomNowPlayingOut>;
  now: number | null;
  clientStale: boolean;
}) {
  const checked = state.receivedAt;
  const failing = state.error !== undefined && !state.error.isUnauthenticated;
  return (
    <div className="flex items-center justify-center gap-3 text-center text-sm text-muted">
      <span>
        {failing || clientStale ? (
          state.offline ? (
            "Offline"
          ) : (
            "Can't reach the server"
          )
        ) : checked && now !== null ? (
          <>
            Updated{" "}
            <time dateTime={new Date(checked).toISOString()} title={formatClock(checked)}>
              {formatRelative(checked, now)}
            </time>
          </>
        ) : (
          "Checking…"
        )}
      </span>
      {failing ? (
        <Button variant="ghost" size="sm" onClick={() => nowPlayingPoller.refresh()} icon={<RefreshCw aria-hidden className="size-4" />}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

function RoomSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-5 md:grid-cols-2 md:gap-8" role="status" aria-busy="true" aria-label="Loading">
      {[0, 1].map((i) => (
        <div key={i} className="rounded-[1.75rem] border border-line bg-surface p-6 shadow-card">
          <div className="flex items-center gap-3">
            <Skeleton className="size-11 rounded-full" />
            <Skeleton className="h-6 w-32" />
          </div>
          <div className="mt-6 flex gap-4">
            <Skeleton className="size-[6.5rem] rounded-[4px] sm:size-32" />
            <div className="flex-1 space-y-3">
              <Skeleton className="h-6 w-4/5" />
              <Skeleton className="h-4 w-3/5" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function LoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <h1 className="font-display text-3xl font-semibold">Couldn&apos;t load</h1>
      <Button className="mt-6" onClick={onRetry} icon={<RefreshCw aria-hidden className="size-4" />}>
        Try again
      </Button>
    </div>
  );
}
