"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { firstName } from "@/lib/format";
import { configResource, nowPlayingPoller, roomResource, sharingResource } from "@/lib/resources";
import { SHARING_NOTICE_VERSION, sharingNotice } from "@/lib/sharing-notice";
import { useResource } from "@/lib/store/resource";
import { toast } from "@/lib/toast";

/**
 * "Share my music": off by default, separate from connecting a service.
 * Turning it on the first time (or after the notice changes) shows exactly
 * what the partner will see and needs an explicit "I understand".
 * Turning it off is one tap and takes effect immediately on the server.
 */
export function SharingSettings() {
  const sharing = useResource(sharingResource);
  const config = useResource(configResource);
  const room = useResource(roomResource);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const partner = room.data?.members.find((m) => !m.is_me) ?? null;
  const partnerName = partner ? firstName(partner.display_name) : null;
  const enabled = sharing.data?.share_now_playing ?? false;
  const serverVersion = config.data?.sharing_notice_version ?? sharing.data?.current_notice_version;
  const versionMismatch = serverVersion !== undefined && serverVersion !== SHARING_NOTICE_VERSION;
  const acknowledged = sharing.data?.notice_version_acknowledged === SHARING_NOTICE_VERSION;

  async function setSharing(next: boolean) {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.setSharing(next, next ? SHARING_NOTICE_VERSION : null);
      sharingResource.mutate(updated);
      nowPlayingPoller.refresh();
      void roomResource.load();
      setNoticeOpen(false);
      toast(
        next
          ? "Sharing is on."
          : "Sharing is off.",
        "success",
      );
    } catch (e) {
      setError(
        e instanceof ApiError && e.code === "sharing_notice_not_acknowledged"
          ? "The sharing notice changed. Please reload the app and read it again."
          : e instanceof ApiError
            ? e.message
            : "Couldn't change sharing. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  function onToggle(next: boolean) {
    if (next && !acknowledged) setNoticeOpen(true);
    else void setSharing(next);
  }

  const notice = sharingNotice(partnerName);

  return (
    <div id="sharing" className="scroll-mt-24">
      <Switch
        checked={enabled}
        onChange={onToggle}
        busy={busy || sharing.status === "loading"}
        disabled={versionMismatch || sharing.status !== "ready"}
        label={partnerName ? `Share my music with ${partnerName}` : "Share my music"}
      />
      {versionMismatch ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          Please reload the app.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <Dialog
        open={noticeOpen}
        onClose={() => setNoticeOpen(false)}
        title="Share your music?"
      >
        <ul className="space-y-3 text-[0.97rem]">
          {notice.map((line) => (
            <li key={line} className="flex gap-3">
              <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-accent" />
              <span>{line}</span>
            </li>
          ))}
        </ul>
        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={() => setNoticeOpen(false)}>
            Cancel
          </Button>
          <Button onClick={() => void setSharing(true)} loading={busy}>
            Start sharing
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
