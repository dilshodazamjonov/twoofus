// The app's shared data: one store per backend resource, plus the session.

import { useSyncExternalStore } from "react";

import { onUnauthenticated } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { SessionOut } from "@/lib/api/types";
import { createPoller } from "@/lib/store/poller";
import { createResource } from "@/lib/store/resource";

export const configResource = createResource((signal) => api.config({ signal }));
export const sessionResource = createResource((signal) => api.session({ signal }));
export const roomResource = createResource((signal) => api.room({ signal }));
export const providersResource = createResource((signal) => api.providers({ signal }));
export const sharingResource = createResource((signal) => api.sharing({ signal }));
export const sessionsResource = createResource((signal) => api.sessions({ signal }));

/** Never faster than every 20 s (the backend caches upstream calls for 15-60 s). */
export function pollIntervalMs(pollAfterSeconds: number | undefined): number {
  return Math.min(Math.max(pollAfterSeconds ?? 20, 20), 60) * 1000;
}

export const nowPlayingPoller = createPoller({
  fetcher: (signal) => api.nowPlaying({ signal }),
  interval: (data) => pollIntervalMs(data.poll_after_seconds),
});

export const tulipsPoller = createPoller({
  fetcher: (signal) => api.tulips({ signal }),
  interval: () => 25_000,
});

/** The backend caches recent songs for 90 s; picks, playlist and answers change rarely. */
export const recentPoller = createPoller({
  fetcher: (signal) => api.recent({ signal }),
  interval: () => 90_000,
});

export const songsPoller = createPoller({
  fetcher: (signal) => api.songs({ signal }),
  interval: () => 60_000,
});

export const questionPoller = createPoller({
  fetcher: (signal) => api.question({ signal }),
  interval: () => 60_000,
});

/** Forget everything that belongs to the signed-in member. */
export function clearMemberData(): void {
  roomResource.reset();
  providersResource.reset();
  sharingResource.reset();
  sessionsResource.reset();
  nowPlayingPoller.reset();
  tulipsPoller.reset();
  recentPoller.reset();
  songsPoller.reset();
  questionPoller.reset();
}

// ----- session end (signed out elsewhere, expired, revoked) -------------------

type SessionEnd = { reason: "expired" | "signed_out" } | null;
let sessionEnd: SessionEnd = null;
const endListeners = new Set<() => void>();

function setSessionEnd(next: SessionEnd) {
  sessionEnd = next;
  endListeners.forEach((listener) => listener());
}

export function useSessionEnd(): SessionEnd {
  return useSyncExternalStore(
    (listener) => {
      endListeners.add(listener);
      return () => endListeners.delete(listener);
    },
    () => sessionEnd,
    () => null,
  );
}

const ANONYMOUS: SessionOut = {
  authenticated: false,
  csrf_token: "",
  user: null,
  session_expires_at: null,
  session_expired: false,
};

/** Apply a session returned by login / invitation acceptance / logout. */
export function applySession(session: SessionOut, reason: "signed_in" | "signed_out" = "signed_in"): void {
  clearMemberData();
  setSessionEnd(reason === "signed_out" ? { reason: "signed_out" } : null);
  sessionResource.mutate(session);
}

if (typeof window !== "undefined") {
  onUnauthenticated(() => {
    const wasSignedIn = sessionResource.getSnapshot().data?.authenticated === true;
    clearMemberData();
    if (wasSignedIn) {
      setSessionEnd({ reason: "expired" });
      sessionResource.mutate(ANONYMOUS);
    }
  });
}
