// "Are we offline?" from what actually happens, not only from navigator.onLine
// (which some browsers get wrong, e.g. it can stay false although requests
// work). Offline = the browser reported going offline, or our last request
// failed at the network level, and no request has reached the server since.
import { useSyncExternalStore } from "react";

let browserOffline = typeof navigator !== "undefined" && navigator.onLine === false;
let networkFailed = false;
let offline = browserOffline;
const listeners = new Set<() => void>();

function recompute() {
  const next = browserOffline || networkFailed;
  if (next !== offline) {
    offline = next;
    listeners.forEach((listener) => listener());
  }
}

/** Called by the API client after every request (not for aborted ones). */
export function noteRequestOutcome(reachedServer: boolean): void {
  networkFailed = !reachedServer;
  if (reachedServer) browserOffline = false;
  recompute();
}

if (typeof window !== "undefined") {
  window.addEventListener("offline", () => {
    browserOffline = true;
    recompute();
  });
  window.addEventListener("online", () => {
    browserOffline = false;
    recompute();
  });
}

export function useOffline(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => offline,
    () => false,
  );
}
