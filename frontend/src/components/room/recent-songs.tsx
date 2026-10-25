"use client";

import { Ellipsis, ListPlus, Send } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { MemberRecentOut, RecentTrackOut } from "@/lib/api/types";
import { formatDay, formatRelative } from "@/lib/format";
import { recentPoller, songsPoller } from "@/lib/resources";
import { useNow } from "@/lib/store/now";
import { usePoller } from "@/lib/store/poller";
import { toast } from "@/lib/toast";

import { ServiceMark, SongRow } from "./song-row";

/**
 * Each member's last few songs (the partner's only while they share). Your
 * own songs can be sent to the other member or added to the playlist.
 */
export function RecentSongs({ partnerName }: { partnerName: string | null }) {
  const recent = usePoller(recentPoller);
  const now = useNow(60_000);
  const data = recent.data;
  if (!data || now === null) return null;

  const partner = data.partner?.state === "ok" && data.partner.tracks.length > 0 ? data.partner : null;
  const me = data.me.state === "ok" && data.me.tracks.length > 0 ? data.me : null;
  const askPermission = data.me.state === "needs_permission";
  if (!partner && !me && !askPermission) return null;

  return (
    <Card aria-labelledby="recent-heading">
      <CardTitle id="recent-heading">Recent</CardTitle>
      <div className="mt-3 space-y-5">
        {partner && partnerName ? <SongList name={partnerName} recent={partner} now={now} /> : null}
        {me ? (
          <SongList name="You" recent={me} now={now} partnerName={partnerName} mine />
        ) : askPermission ? (
          <AllowRecent />
        ) : null}
      </div>
    </Card>
  );
}

function SongList({
  name,
  recent,
  now,
  partnerName = null,
  mine = false,
}: {
  name: string;
  recent: MemberRecentOut;
  now: number;
  partnerName?: string | null;
  mine?: boolean;
}) {
  const [chosen, setChosen] = useState<RecentTrackOut | null>(null);
  return (
    <div>
      <div className="flex min-h-8 items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-muted">{name}</h3>
        <ServiceMark provider={recent.source} />
      </div>
      <ul aria-label={mine ? "Your recent songs" : `${name}'s recent songs`} className="divide-y divide-line">
        {recent.tracks.map((track) => (
          <SongRow
            key={track.key}
            song={track}
            aside={
              <>
                <PlayedWhen track={track} now={now} />
                {mine ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="size-11 shrink-0 px-0"
                    aria-label={`Share ${track.title}`}
                    onClick={() => setChosen(track)}
                    icon={<Ellipsis aria-hidden className="size-5" />}
                  />
                ) : null}
              </>
            }
          />
        ))}
      </ul>
      {chosen ? <ShareSong track={chosen} partnerName={partnerName} onClose={() => setChosen(null)} /> : null}
    </div>
  );
}

function PlayedWhen({ track, now }: { track: RecentTrackOut; now: number }) {
  const label = track.played_at
    ? formatRelative(Date.parse(track.played_at), now)
    : track.played_on
      ? formatDay(track.played_on, now)
      : null;
  if (!label) return null;
  return (
    <time dateTime={track.played_at ?? track.played_on ?? undefined} className="shrink-0 text-xs text-muted">
      {label}
    </time>
  );
}

function ShareSong({
  track,
  partnerName,
  onClose,
}: {
  track: RecentTrackOut;
  partnerName: string | null;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState<"pick" | "playlist" | null>(null);

  async function share(kind: "pick" | "playlist") {
    setBusy(kind);
    try {
      if (kind === "pick") await api.pickSong(track.key);
      else await api.addToPlaylist(track.key);
      songsPoller.refresh();
      toast(kind === "pick" ? `Sent to ${partnerName}.` : "Added to the playlist.", "success");
      onClose();
    } catch (error) {
      if (error instanceof ApiError && error.isUnauthenticated) return;
      toast(error instanceof ApiError && error.status === 409 ? error.message : "Couldn't do that. Please try again.", "error");
      recentPoller.refresh();
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog open onClose={onClose} title={track.title} description={track.artist_names.join(", ")}>
      <div className="flex flex-col gap-3 sm:flex-row">
        {partnerName ? (
          <Button
            onClick={() => void share("pick")}
            loading={busy === "pick"}
            disabled={busy !== null}
            icon={<Send aria-hidden className="size-4" />}
          >
            For {partnerName}
          </Button>
        ) : null}
        <Button
          variant="secondary"
          onClick={() => void share("playlist")}
          loading={busy === "playlist"}
          disabled={busy !== null}
          icon={<ListPlus aria-hidden className="size-4" />}
        >
          Add to playlist
        </Button>
      </div>
    </Dialog>
  );
}

/** A Spotify grant from before recent songs: one tap asks Spotify again. */
function AllowRecent() {
  const [busy, setBusy] = useState(false);

  async function allow() {
    setBusy(true);
    try {
      const { authorization_url: url } = await api.spotifyAuthorize();
      window.location.assign(url); // Spotify's own page; it sends you back afterwards
    } catch {
      setBusy(false);
      toast("Couldn't reach Spotify. Please try again.", "error");
    }
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-muted">You</h3>
      <Button variant="soft" size="sm" className="mt-2" onClick={() => void allow()} loading={busy}>
        Show my recent songs
      </Button>
    </div>
  );
}
