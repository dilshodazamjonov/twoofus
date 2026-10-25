"use client";

import { Unplug } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog } from "@/components/ui/dialog";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { ConnectionOut, DisconnectOut } from "@/lib/api/types";
import { formatDate, formatRelative } from "@/lib/format";
import { PROVIDERS } from "@/lib/providers";
import { nowPlayingPoller, providersResource } from "@/lib/resources";
import { useNow } from "@/lib/store/now";
import { toast } from "@/lib/toast";

const ERROR_TEXT: Record<string, string> = {
  provider_rate_limited: "asked us to slow down for a bit",
  provider_quota_exceeded: "reached this app's request limit for now",
  provider_unreachable: "didn't answer the last time we asked",
  provider_forbidden: "refused access (for Spotify: is this account on the app's User Management list?)",
  provider_reauth_required: "needs you to approve the connection again",
  provider_bad_response: "answered in an unexpected way",
  provider_not_configured: "isn't set up on this server",
};

/** What to say after disconnecting, depending on what the provider confirmed. */
export function disconnectMessage(label: string, revocation: DisconnectOut["provider_revocation"]): string {
  switch (revocation) {
    case "revoked":
      return `${label} disconnected. We deleted our copy, and ${label} confirmed the sign-in is cancelled.`;
    case "failed":
      return `${label} disconnected and our copy deleted. ${label} didn't confirm cancelling the sign-in; you can remove it in your Yandex ID settings (id.yandex.ru).`;
    case "not_supported":
      return `${label} disconnected and our copy deleted. To remove the permission at ${label} too, open spotify.com/account/apps.`;
    default:
      return `${label} disconnected. Our copy of its access was deleted.`;
  }
}

/** My connection and its health, with reconnect / disconnect. */
export function ConnectionStatus({ connection, onReconnect }: { connection: ConnectionOut; onReconnect: () => void }) {
  const now = useNow(30_000);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const provider = PROVIDERS[connection.provider];
  const needsReauth = connection.status === "reauth_required";
  const lastSuccess = connection.last_success_at ? Date.parse(connection.last_success_at) : null;

  async function disconnect() {
    setBusy(true);
    try {
      const result = await api.disconnect();
      setConfirming(false);
      await providersResource.load();
      nowPlayingPoller.refresh();
      toast(disconnectMessage(provider.label, result.provider_revocation), "success");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Couldn't disconnect. Please try again.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="font-display text-2xl font-semibold">{provider.label}</p>
        {needsReauth ? <Chip tone="warning">Needs reconnecting</Chip> : <Chip tone="sage">Connected</Chip>}
        {connection.provider === "demo" ? <Chip tone="warning">Demo</Chip> : null}
        {connection.provider === "yandex" ? <Chip>Experimental</Chip> : null}
      </div>
      <ul className="space-y-1 text-[0.95rem] text-muted">
        <li>Connected {formatDate(Date.parse(connection.authorized_at))}.</li>
        {lastSuccess !== null && now !== null ? <li>Last read {formatRelative(lastSuccess, now)}.</li> : null}
        {connection.last_error_code && ERROR_TEXT[connection.last_error_code] ? (
          <li>
            {provider.label} {ERROR_TEXT[connection.last_error_code]}.
          </li>
        ) : null}
        {connection.provider === "spotify" && connection.reauthorize_by ? (
          <li>Spotify asks you to approve again by {formatDate(Date.parse(connection.reauthorize_by))}.</li>
        ) : null}
      </ul>
      <div className="flex flex-wrap gap-3">
        <Button variant={needsReauth ? "primary" : "secondary"} onClick={onReconnect}>
          {needsReauth ? `Reconnect ${provider.label}` : "Reconnect or switch"}
        </Button>
        <Button variant="ghost" onClick={() => setConfirming(true)} icon={<Unplug aria-hidden className="size-4" />}>
          Disconnect
        </Button>
      </div>
      <Dialog
        open={confirming}
        onClose={() => setConfirming(false)}
        title={`Disconnect ${provider.label}?`}
      >
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={() => setConfirming(false)}>
            Keep it
          </Button>
          <Button variant="danger" loading={busy} onClick={() => void disconnect()}>
            Disconnect
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
