import type { ProviderName } from "@/lib/api/types";

export type ProviderInfo = {
  name: ProviderName;
  label: string;
  /** Link-out text. Spotify requires wording like this (developer design guidelines). */
  listenLabel: string;
  official: boolean;
};

export const PROVIDERS: Record<ProviderName, ProviderInfo> = {
  spotify: { name: "spotify", label: "Spotify", listenLabel: "Play on Spotify", official: true },
  yandex: { name: "yandex", label: "Yandex Music", listenLabel: "Open in Yandex Music", official: false },
  demo: { name: "demo", label: "Demo", listenLabel: "", official: false },
};

/** What the Spotify connection may access, in plain words (scopes below). */
export const SPOTIFY_SCOPE_DESCRIPTION = "See the song you're playing and your recently played songs";
export const SPOTIFY_SCOPE = "user-read-currently-playing user-read-recently-played";

type LinkableSong = { provider: ProviderName; title: string; artist_names: string[]; track_url: string | null };

/**
 * Where to listen to a shared song: the song itself when it comes from your
 * own service, otherwise a search for it on yours.
 */
export function songLink(song: LinkableSong, mine: ProviderName | null): { href: string; label: string } | null {
  if (mine === null || mine === "demo" || mine === song.provider) {
    const label = PROVIDERS[song.provider].listenLabel;
    return song.track_url && label ? { href: song.track_url, label } : null;
  }
  const query = encodeURIComponent([song.title, ...song.artist_names.slice(0, 1)].join(" "));
  return mine === "spotify"
    ? { href: `https://open.spotify.com/search/${query}`, label: "Find on Spotify" }
    : { href: `https://music.yandex.ru/search?text=${query}`, label: "Find in Yandex Music" };
}
