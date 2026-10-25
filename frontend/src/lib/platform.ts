// Device/installation facts, read on the client only (null while hydrating).
import { useSyncExternalStore } from "react";

export type Platform = {
  ios: boolean;
  /** Running as an installed home-screen app. */
  standalone: boolean;
  /** Mobile Safari specifically (other iOS browsers can also install since iOS 16.4 but label things differently). */
  iosSafari: boolean;
};

export function detectPlatform(nav: Pick<Navigator, "userAgent" | "maxTouchPoints"> & { platform?: string; standalone?: boolean }, standaloneQuery: boolean): Platform {
  const ua = nav.userAgent;
  const ios = /iPad|iPhone|iPod/.test(ua) || (nav.platform === "MacIntel" && nav.maxTouchPoints > 1);
  const iosSafari = ios && /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS|OPiOS|GSA\//.test(ua);
  return { ios, iosSafari, standalone: standaloneQuery || nav.standalone === true };
}

let cached: Platform | null = null;
const listeners = new Set<() => void>();

function snapshot(): Platform {
  if (cached) return cached;
  cached = detectPlatform(navigator as Navigator & { standalone?: boolean }, window.matchMedia("(display-mode: standalone)").matches);
  return cached;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const query = window.matchMedia("(display-mode: standalone)");
  const onChange = () => {
    cached = null;
    listeners.forEach((l) => l());
  };
  query.addEventListener("change", onChange);
  return () => {
    listeners.delete(listener);
    query.removeEventListener("change", onChange);
  };
}

export function usePlatform(): Platform | null {
  return useSyncExternalStore(subscribe, snapshot, () => null);
}

// ----- browser install prompt (Chromium only; Safari has no such event) -----

type InstallPromptEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

let deferredPrompt: InstallPromptEvent | null = null;
const installListeners = new Set<() => void>();

export function captureInstallPrompt(): () => void {
  const onPrompt = (event: Event) => {
    event.preventDefault(); // show our own, quieter button instead of the mini-infobar
    deferredPrompt = event as InstallPromptEvent;
    installListeners.forEach((l) => l());
  };
  const onInstalled = () => {
    deferredPrompt = null;
    installListeners.forEach((l) => l());
  };
  window.addEventListener("beforeinstallprompt", onPrompt);
  window.addEventListener("appinstalled", onInstalled);
  return () => {
    window.removeEventListener("beforeinstallprompt", onPrompt);
    window.removeEventListener("appinstalled", onInstalled);
  };
}

export function useInstallPrompt(): (() => Promise<boolean>) | null {
  const available = useSyncExternalStore(
    (listener) => {
      installListeners.add(listener);
      return () => installListeners.delete(listener);
    },
    () => deferredPrompt !== null,
    () => false,
  );
  if (!available) return null;
  return async () => {
    const prompt = deferredPrompt;
    if (!prompt) return false;
    deferredPrompt = null;
    installListeners.forEach((l) => l());
    await prompt.prompt();
    const choice = await prompt.userChoice;
    return choice.outcome === "accepted";
  };
}
