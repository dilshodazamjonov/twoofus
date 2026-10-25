"use client";

import type { PlaybackOut } from "@/lib/api/types";
import { formatDuration, formatDurationSpoken } from "@/lib/format";
import { useNow } from "@/lib/store/now";

/**
 * Position in the song. Paused: the confirmed position. Playing: an *estimate*
 * (last confirmed position + time since the provider was asked), labelled as
 * such, frozen at the end of the song until the next check confirms what's next.
 * Never shown for stale data (the backend sends no progress then).
 */
export function PlaybackProgress({ playback, serverOffsetMs }: { playback: PlaybackOut; serverOffsetMs: number }) {
  const playing = playback.status === "playing";
  const now = useNow(playing ? 1000 : 60_000);
  const { progress_ms: progress, duration_ms: duration, fetched_at: fetchedAt } = playback;
  if (progress === null || duration === null || duration <= 0 || !fetchedAt || playback.is_stale) return null;

  const elapsed = playing && now !== null ? Math.max(0, now + serverOffsetMs - Date.parse(fetchedAt)) : 0;
  const position = Math.min(duration, progress + elapsed);
  const ended = playing && position >= duration;
  const percent = (position / duration) * 100;
  const spoken = `${playing ? "About " : ""}${formatDurationSpoken(position)} of ${formatDurationSpoken(duration)}${playing ? ", estimated" : ""}`;

  return (
    <div className="mt-4">
      <div
        role="progressbar"
        aria-label="Position in the song"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration / 1000)}
        aria-valuenow={Math.round(position / 1000)}
        aria-valuetext={spoken}
        className="h-1.5 overflow-hidden rounded-full bg-surface-2"
      >
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-1000 ease-linear"
          style={{ width: `${percent}%`, opacity: playing ? 1 : 0.55 }}
        />
      </div>
      <div className="mt-1.5 flex items-center justify-between text-xs tabular-nums text-muted" aria-hidden="true">
        <span>
          {ended ? "Checking what's next…" : `${playing ? "≈ " : ""}${formatDuration(position)}`}
          {playing && !ended ? <span className="ml-1 italic">estimated</span> : null}
        </span>
        <span>{formatDuration(duration)}</span>
      </div>
    </div>
  );
}
