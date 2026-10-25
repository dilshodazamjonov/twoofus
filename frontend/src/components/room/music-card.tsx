"use client";

import { ArrowUpRight, Eye, EyeOff, Lock, Moon, Music2, Plug, Podcast, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { SpotifyLogo } from "@/components/brand/spotify-logo";
import { buttonClasses } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { cn } from "@/components/ui/cn";
import type { MemberNowPlayingOut, PlaybackOut } from "@/lib/api/types";
import type { CardView } from "@/lib/copy/playback";
import { firstName } from "@/lib/format";
import { PROVIDERS } from "@/lib/providers";

import { Artwork } from "./artwork";
import { PlaybackProgress } from "./playback-progress";

type MusicCardProps = {
  member: MemberNowPlayingOut;
  view: CardView;
  serverOffsetMs: number;
  /** For my own card: the partner's first name (who would see it). */
  partnerName?: string | null;
};

export function MusicCard({ member, view, serverOffsetMs, partnerName }: MusicCardProps) {
  const playback = member.playback;
  const name = firstName(member.display_name);
  const headingId = `card-${member.user_id}`;
  const showTrack = view.kind === "track" && playback.track_title !== null;

  return (
    <article
      aria-labelledby={headingId}
      className={cn(
        "relative flex flex-col rounded-[1.75rem] border bg-surface p-5 shadow-card transition-colors sm:p-6",
        view.live ? "border-accent/25" : "border-line",
      )}
    >
      <header className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden="true"
            className={cn(
              "inline-flex size-11 shrink-0 items-center justify-center rounded-full font-display text-xl font-semibold",
              member.is_me ? "bg-sage-soft text-sage-ink" : "bg-accent-soft text-accent-text",
            )}
          >
            {name.slice(0, 1).toUpperCase()}
          </span>
          <h2 id={headingId} className="truncate font-display text-2xl font-semibold leading-tight">
            {name}
          </h2>
        </div>
        {view.status ? <StatusPill view={view} /> : null}
      </header>

      <div className="mt-5 flex-1">
        {showTrack ? (
          <TrackDetails playback={playback} stale={view.stale} serverOffsetMs={serverOffsetMs} />
        ) : (
          <StateMessage view={view} />
        )}
        {view.action ? (
          <Link href={view.action.href} className={buttonClasses("soft", "sm", "mt-4")}>
            {view.action.label}
          </Link>
        ) : null}
      </div>

      <CardFooter playback={playback} showLink={showTrack} />
      {member.is_me ? <SharingLine sharing={member.sharing_enabled} partnerName={partnerName ?? null} /> : null}
    </article>
  );
}

function StatusPill({ view }: { view: CardView }) {
  return (
    <p
      className={cn(
        "inline-flex shrink-0 items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold",
        view.live
          ? "bg-accent-soft text-accent-text"
          : view.tone === "attention"
            ? "bg-warning-soft text-warning-ink"
            : "bg-surface-2 text-muted",
      )}
    >
      <span aria-hidden="true" className="relative inline-flex size-2">
        {view.live ? <span className="absolute inset-0 animate-soft-pulse rounded-full bg-accent" /> : null}
        <span className={cn("relative inline-flex size-2 rounded-full", view.live ? "bg-accent" : "bg-current opacity-50")} />
      </span>
      {view.status}
    </p>
  );
}

function TrackDetails({
  playback,
  stale,
  serverOffsetMs,
}: {
  playback: PlaybackOut;
  stale: boolean;
  serverOffsetMs: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const title = playback.track_title ?? "";
  const artists = playback.artist_names.join(", ");
  const coverAlt = playback.album ? `Cover of ${playback.album}` : `Cover of ${title}`;
  return (
    // Re-mounts (and gently fades in) whenever the song changes.
    // Stale data dims only the text: artwork is never altered (Spotify's rules).
    <div key={`${title}|${artists}`} className="animate-fade-up">
      <div className="flex gap-4">
        <Artwork src={playback.artwork_url} alt={coverAlt} className="w-[6.5rem] sm:w-32" />
        {/* Long titles are clamped; tapping shows the full text (metadata must stay reachable).
            The visible text is the button's name (WCAG 2.5.3); screen readers always get it in full. */}
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className={cn("min-w-0 flex-1 rounded-lg text-left", stale && "opacity-75")}
        >
          <span className={cn("block font-display text-[1.55rem] font-semibold leading-[1.12] text-ink", !expanded && "line-clamp-3")}>
            {title}
          </span>
          {artists ? (
            <span className={cn("mt-1.5 block text-[0.95rem] text-ink/85", !expanded && "line-clamp-2")}>{artists}</span>
          ) : null}
          {playback.album ? (
            <span className={cn("mt-0.5 block text-sm text-muted", !expanded && "line-clamp-1")}>{playback.album}</span>
          ) : null}
        </button>
      </div>
      <PlaybackProgress playback={playback} serverOffsetMs={serverOffsetMs} />
    </div>
  );
}

const STATE_ICONS: Record<CardView["kind"], ReactNode> = {
  track: <Music2 aria-hidden className="size-6" />,
  non_music: <Podcast aria-hidden className="size-6" />,
  idle: <Moon aria-hidden className="size-6" />,
  private: <Lock aria-hidden className="size-6" />,
  not_connected: <Plug aria-hidden className="size-6" />,
  unavailable: <TriangleAlert aria-hidden className="size-6" />,
  error: <TriangleAlert aria-hidden className="size-6" />,
};

function StateMessage({ view }: { view: CardView }) {
  return (
    <div className="flex items-center gap-4">
      <span
        className={cn(
          "inline-flex size-[6.5rem] shrink-0 items-center justify-center rounded-[4px] sm:w-32 lg:rounded-[8px]",
          view.tone === "attention" ? "bg-warning-soft text-warning-ink" : "bg-surface-2 text-muted",
        )}
      >
        {STATE_ICONS[view.kind]}
      </span>
      {view.message ? <p className="text-[1.02rem] leading-snug text-ink">{view.message}</p> : null}
    </div>
  );
}

function CardFooter({ playback, showLink }: { playback: PlaybackOut; showLink: boolean }) {
  if (!playback.source) return null;
  const provider = PROVIDERS[playback.source];
  return (
    <footer className="mt-5 flex min-h-11 flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
      <div className="flex items-center gap-2">
        {playback.source === "spotify" ? (
          <SpotifyLogo width={84} />
        ) : playback.source === "yandex" ? (
          <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink">
            <Music2 aria-hidden className="size-4" />
            {provider.label}
          </span>
        ) : null}
        {playback.is_demo ? <Chip tone="warning">Demo</Chip> : null}
      </div>
      {showLink && playback.track_url && provider.listenLabel ? (
        <a
          href={playback.track_url}
          target="_blank"
          rel="noopener noreferrer"
          className={buttonClasses("secondary", "sm")}
        >
          {provider.listenLabel}
          <ArrowUpRight aria-hidden className="size-4" />
          <span className="sr-only">(opens {provider.label})</span>
        </a>
      ) : null}
    </footer>
  );
}

function SharingLine({ sharing, partnerName }: { sharing: boolean; partnerName: string | null }) {
  return (
    <p className="mt-3 flex items-center gap-2 text-sm text-muted">
      {sharing ? <Eye aria-hidden className="size-4 shrink-0" /> : <EyeOff aria-hidden className="size-4 shrink-0" />}
      <span>
        {sharing ? (partnerName ? `Visible to ${partnerName}` : "Shared") : "Not shared"}
        {" · "}
        <Link href="/connect#sharing" className="font-medium text-accent-text underline-offset-4 hover:underline">
          {sharing ? "Change" : "Share"}
        </Link>
      </span>
    </p>
  );
}
