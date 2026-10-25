"use client";

import { X } from "lucide-react";
import { useState } from "react";

import { SpotifyLogo } from "@/components/brand/spotify-logo";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { ProviderName } from "@/lib/api/types";
import { songsPoller } from "@/lib/resources";
import { usePoller } from "@/lib/store/poller";
import { toast } from "@/lib/toast";

import { FindLink, SongRow } from "./song-row";

/** The playlist both members add to (from their recent songs) and either can trim. */
export function Playlist({ mine }: { mine: ProviderName | null }) {
  const songs = usePoller(songsPoller);
  const [removing, setRemoving] = useState<string | null>(null);
  const items = songs.data?.playlist;
  if (!items) return null;

  async function remove(id: string) {
    setRemoving(id);
    try {
      await api.removeFromPlaylist(id);
      songsPoller.refresh();
    } catch (error) {
      if (!(error instanceof ApiError && error.isUnauthenticated)) {
        toast("Couldn't remove it. Please try again.", "error");
      }
    } finally {
      setRemoving(null);
    }
  }

  return (
    <Card aria-labelledby="playlist-heading">
      <div className="flex items-center justify-between gap-3">
        <CardTitle id="playlist-heading">Playlist</CardTitle>
        {items.some((entry) => entry.song.provider === "spotify") ? <SpotifyLogo width={70} /> : null}
      </div>
      {items.length === 0 ? (
        <p className="mt-2 text-[0.95rem] text-muted">Add songs from Recent.</p>
      ) : (
        <ul aria-label="Playlist" className="mt-3 divide-y divide-line">
          {items.map((entry) => (
            <SongRow
              key={entry.id}
              song={entry.song}
              aside={
                <>
                  <FindLink song={entry.song} mine={mine} />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="size-11 shrink-0 px-0"
                    aria-label={`Remove ${entry.song.title}`}
                    onClick={() => void remove(entry.id)}
                    loading={removing === entry.id}
                    disabled={removing !== null}
                    icon={<X aria-hidden className="size-4" />}
                  />
                </>
              }
            />
          ))}
        </ul>
      )}
    </Card>
  );
}
