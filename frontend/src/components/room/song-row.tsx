"use client";

import { Music2, Search } from "lucide-react";
import type { ReactNode } from "react";

import { SpotifyLogo } from "@/components/brand/spotify-logo";
import type { ProviderName } from "@/lib/api/types";
import { PROVIDERS, songLink } from "@/lib/providers";

import { Artwork } from "./artwork";

type Song = { title: string; artist_names: string[]; artwork_url: string | null; track_url: string | null };

/**
 * One song in a list: cover, title, artists. The song links to its own
 * service (Spotify's rules: its covers and titles always link back to it).
 */
export function SongRow({ song, aside }: { song: Song; aside?: ReactNode }) {
  const artists = song.artist_names.join(", ");
  const body = (
    <>
      <Artwork src={song.artwork_url} alt="" className="w-11 lg:rounded-[4px]" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[0.97rem] font-medium text-ink">{song.title}</span>
        {artists ? <span className="block truncate text-sm text-muted">{artists}</span> : null}
      </span>
    </>
  );
  return (
    <li className="flex min-h-15 items-center gap-2 py-1.5">
      {song.track_url ? (
        <a
          href={song.track_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex min-w-0 flex-1 items-center gap-3 rounded-lg"
        >
          {body}
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      ) : (
        <span className="flex min-w-0 flex-1 items-center gap-3">{body}</span>
      )}
      {aside}
    </li>
  );
}

/** Spotify's logo next to its content; a plain label for Yandex Music. */
export function ServiceMark({ provider }: { provider: ProviderName | null }) {
  if (provider === "spotify") return <SpotifyLogo width={70} />;
  if (provider === "yandex") {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink">
        <Music2 aria-hidden className="size-4" />
        {PROVIDERS.yandex.label}
      </span>
    );
  }
  return null;
}

/** A search for a song from the other service, on your own. */
export function FindLink({
  song,
  mine,
}: {
  song: Song & { provider: ProviderName };
  mine: ProviderName | null;
}) {
  const link = song.provider !== mine ? songLink(song, mine) : null;
  if (!link || link.href === song.track_url) return null;
  return (
    <a
      href={link.href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${link.label}: ${song.title}`}
      title={link.label}
      className="inline-flex size-11 shrink-0 items-center justify-center rounded-full text-accent-text hover:bg-accent-soft/60"
    >
      <Search aria-hidden className="size-4" />
    </a>
  );
}
