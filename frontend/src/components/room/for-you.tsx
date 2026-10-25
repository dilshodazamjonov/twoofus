"use client";

import { ArrowUpRight } from "lucide-react";

import { buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/components/ui/cn";
import type { ProviderName } from "@/lib/api/types";
import { songLink } from "@/lib/providers";
import { songsPoller } from "@/lib/resources";
import { usePoller } from "@/lib/store/poller";

import { Artwork } from "./artwork";
import { ServiceMark } from "./song-row";

/** The song the other member picked for you, if any. */
export function ForYou({
  partnerName,
  mine,
  className,
}: {
  partnerName: string;
  mine: ProviderName | null;
  className?: string;
}) {
  const songs = usePoller(songsPoller);
  const song = songs.data?.for_me;
  if (!song) return null;
  const link = songLink(song, mine);
  const artists = song.artist_names.join(", ");

  return (
    <Card aria-labelledby="for-you-heading" className={cn("animate-fade-up", className)}>
      <div className="flex items-center gap-4">
        {song.track_url ? (
          <a href={song.track_url} target="_blank" rel="noopener noreferrer" className="shrink-0 rounded-[4px]">
            <Artwork src={song.artwork_url} alt={`Cover of ${song.title}`} className="w-20" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : (
          <Artwork src={song.artwork_url} alt={`Cover of ${song.title}`} className="w-20" />
        )}
        <div className="min-w-0 flex-1">
          <h2 id="for-you-heading" className="text-sm font-semibold text-muted">
            From {partnerName}
          </h2>
          <p className="mt-0.5 line-clamp-2 font-display text-[1.45rem] font-semibold leading-tight text-ink">{song.title}</p>
          {artists ? <p className="mt-0.5 truncate text-[0.95rem] text-ink/85">{artists}</p> : null}
        </div>
      </div>
      <footer className="mt-4 flex min-h-11 flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        <ServiceMark provider={song.provider} />
        {link ? (
          <a href={link.href} target="_blank" rel="noopener noreferrer" className={buttonClasses("secondary", "sm")}>
            {link.label}
            <ArrowUpRight aria-hidden className="size-4" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : null}
      </footer>
    </Card>
  );
}
