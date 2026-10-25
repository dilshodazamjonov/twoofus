// Service worker registration and the "new version available" signal.
// Registered only in production builds (a worker would fight the dev server).
import { useSyncExternalStore } from "react";

let waiting: ServiceWorker | null = null;
let reloadOnControllerChange = false;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

const UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000;

export function registerServiceWorker(): void {
  if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;

  navigator.serviceWorker.addEventListener("controllerchange", () => {
    // Only reload when the person asked for the update (never on first install).
    if (reloadOnControllerChange) window.location.reload();
  });

  navigator.serviceWorker
    .register("/sw.js", { scope: "/", updateViaCache: "none" })
    .then((registration) => {
      const watch = (worker: ServiceWorker) => {
        worker.addEventListener("statechange", () => {
          if (worker.state === "installed" && navigator.serviceWorker.controller) {
            waiting = worker;
            emit();
          }
        });
      };
      if (registration.waiting && navigator.serviceWorker.controller) {
        waiting = registration.waiting;
        emit();
      }
      if (registration.installing) watch(registration.installing);
      registration.addEventListener("updatefound", () => {
        if (registration.installing) watch(registration.installing);
      });
      // Installed apps can stay open for days: look for a new version when
      // they come back to the foreground, at most once an hour.
      let lastCheck = Date.now();
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible" && Date.now() - lastCheck > UPDATE_CHECK_INTERVAL_MS) {
          lastCheck = Date.now();
          registration.update().catch(() => undefined);
        }
      });
    })
    .catch(() => undefined); // no service worker: the app still works online
}

export function applyUpdate(): void {
  if (!waiting) return;
  reloadOnControllerChange = true;
  waiting.postMessage({ type: "SKIP_WAITING" });
}

export function useUpdateAvailable(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => waiting !== null,
    () => false,
  );
}
