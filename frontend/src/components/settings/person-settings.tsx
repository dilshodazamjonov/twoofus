"use client";

import { Copy, Link2, Share2 } from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { InvitationCreatedOut } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { roomResource } from "@/lib/resources";
import { useResource } from "@/lib/store/resource";
import { toast } from "@/lib/toast";

/** The partner, or (for the owner) the one-time invitation that brings them in. */
export function PersonSettings() {
  const room = useResource(roomResource);
  const [created, setCreated] = useState<InvitationCreatedOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const me = room.data?.members.find((m) => m.is_me);
  const partner = room.data?.members.find((m) => !m.is_me);
  const isOwner = me?.role === "owner";
  const pending = room.data?.invitation?.pending ?? false;

  if (partner) {
    return (
      <p className="text-[0.97rem]">
        <strong className="font-semibold">{partner.display_name}</strong> joined on{" "}
        {formatDate(Date.parse(partner.joined_at))}.
      </p>
    );
  }
  if (!isOwner) return <p className="text-muted">Only the owner can invite.</p>;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      setCreated(await api.createInvitation());
      void roomResource.load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't create an invitation.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    setBusy(true);
    try {
      await api.revokeInvitation();
      setCreated(null);
      await roomResource.load();
      toast("Invitation cancelled.", "success");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't cancel the invitation.");
    } finally {
      setBusy(false);
    }
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      toast("Link copied.", "success");
    } catch {
      toast("Couldn't copy. Select the link and copy it.", "info");
    }
  }

  async function share(url: string) {
    try {
      await navigator.share({ url });
    } catch {
      // closed the share sheet: nothing to do
    }
  }

  return (
    <div className="space-y-4">
      {created ? (
        <div className="space-y-3 rounded-2xl border border-line bg-surface-2 p-4">
          <p className="break-all rounded-xl bg-surface px-3 py-2 font-mono text-sm" aria-label="Invitation link">
            {created.invite_url}
          </p>
          <p className="text-sm text-muted">
            Works once, until {formatDateTime(Date.parse(created.expires_at))}. Shown only now.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => void copy(created.invite_url)} icon={<Copy aria-hidden className="size-4" />}>
              Copy link
            </Button>
            {typeof navigator !== "undefined" && "share" in navigator ? (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void share(created.invite_url)}
                icon={<Share2 aria-hidden className="size-4" />}
              >
                Share…
              </Button>
            ) : null}
          </div>
        </div>
      ) : pending ? (
        <p className="text-[0.97rem] text-muted">
          An invitation is pending until{" "}
          {room.data?.invitation?.expires_at ? formatDateTime(Date.parse(room.data.invitation.expires_at)) : "soon"}.
        </p>
      ) : null}
      {error ? <Alert tone="error">{error}</Alert> : null}
      <div className="flex flex-wrap gap-2">
        <Button
          variant={created ? "secondary" : "primary"}
          onClick={() => void create()}
          loading={busy && !created}
          icon={<Link2 aria-hidden className="size-4" />}
        >
          {pending || created ? "Create a new link" : "Create invitation link"}
        </Button>
        {pending || created ? (
          <Button variant="ghost" onClick={() => void revoke()} disabled={busy}>
            Cancel invitation
          </Button>
        ) : null}
      </div>
    </div>
  );
}
