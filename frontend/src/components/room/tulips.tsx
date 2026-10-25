"use client";

import { useEffect, useRef, useState } from "react";

import { TulipIcon } from "@/components/brand/tulip-icon";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatRelative } from "@/lib/format";
import { tulipsPoller } from "@/lib/resources";
import { useNow } from "@/lib/store/now";
import { usePoller } from "@/lib/store/poller";
import { toast } from "@/lib/toast";

/**
 * Send a tulip, and hear about the ones that arrive: each is announced once,
 * then marked seen. The sender is never told whether a tulip was seen.
 */
export function Tulips({ partnerName }: { partnerName: string }) {
  const tulips = usePoller(tulipsPoller);
  const now = useNow(30_000);
  const [sending, setSending] = useState(false);
  const announced = useRef<Set<string> | null>(null);

  useEffect(() => {
    const items = tulips.data?.items;
    if (!items) return;
    if (announced.current === null) announced.current = new Set();
    const fresh = items.filter((t) => t.is_new && !announced.current?.has(t.id));
    if (fresh.length === 0) return;
    fresh.forEach((t) => announced.current?.add(t.id));
    toast(
      fresh.length === 1 ? `${partnerName} sent you a tulip.` : `${partnerName} sent you ${fresh.length} tulips.`,
      "tulip",
      6_000,
    );
    api
      .markTulipsSeen()
      .then(() => tulipsPoller.refresh())
      .catch(() => undefined); // retried on the next arrival
  }, [tulips.data, partnerName]);

  async function send() {
    setSending(true);
    try {
      await api.sendTulip();
      toast(`Tulip sent to ${partnerName}.`, "tulip");
      tulipsPoller.refresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 429) {
        toast(`Too many at once. Try again in ${Math.max(1, error.retryAfterSeconds ?? 30)} s.`, "info");
      } else if (!(error instanceof ApiError && error.isUnauthenticated)) {
        toast("Couldn't send it. Please try again.", "error");
      }
    } finally {
      setSending(false);
    }
  }

  const lastReceived = tulips.data?.items.find((t) => t.direction === "received");
  return (
    <div className="flex flex-col items-center gap-2">
      <Button
        size="lg"
        variant="soft"
        onClick={() => void send()}
        loading={sending}
        icon={sending ? undefined : <TulipIcon className="size-5" />}
      >
        Send a tulip
      </Button>
      {lastReceived && now !== null ? (
        <p className="text-sm text-muted">
          From {partnerName},{" "}
          <time dateTime={lastReceived.created_at}>{formatRelative(Date.parse(lastReceived.created_at), now)}</time>
        </p>
      ) : null}
    </div>
  );
}
