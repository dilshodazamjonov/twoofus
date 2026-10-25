// Invitation links carry the token in the URL *fragment* (/invite#token=...),
// which browsers never send to any server, so it stays out of logs.
import { useSyncExternalStore } from "react";

export function parseInviteToken(hash: string): string | null {
  const params = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  const token = params.get("token")?.trim() ?? "";
  return /^[A-Za-z0-9_-]{16,256}$/.test(token) ? token : null;
}

function subscribe(listener: () => void) {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
}

/** undefined while rendering on the server / hydrating, then the token or null. */
export function useInviteToken(): string | null | undefined {
  return useSyncExternalStore(
    subscribe,
    () => parseInviteToken(window.location.hash),
    () => undefined,
  );
}
