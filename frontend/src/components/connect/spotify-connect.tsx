"use client";

import { useState } from "react";

import { SpotifyLogo } from "@/components/brand/spotify-logo";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";

const SPOTIFY_AUTHORIZE = "https://accounts.spotify.com/";

export function SpotifyConnect({ reconnect = false }: { reconnect?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const { authorization_url: url } = await api.spotifyAuthorize();
      if (!url.startsWith(SPOTIFY_AUTHORIZE)) throw new Error("unexpected authorisation URL");
      window.location.assign(url); // Spotify's own page; it sends you back here afterwards
    } catch (e) {
      setBusy(false);
      setError(e instanceof ApiError ? e.message : "Couldn't start the Spotify connection. Please try again.");
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <SpotifyLogo width={96} />
        <span className="text-sm text-muted">Official Spotify connection</span>
      </div>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <Button size="lg" onClick={() => void start()} loading={busy}>
        {reconnect ? "Reconnect Spotify" : "Continue to Spotify"}
      </Button>
    </div>
  );
}
