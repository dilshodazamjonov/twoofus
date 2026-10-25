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

/** What the Spotify connection may access, in plain words (scope: user-read-currently-playing). */
export const SPOTIFY_SCOPE_DESCRIPTION = "See the song you're playing right now";
export const SPOTIFY_SCOPE = "user-read-currently-playing";
