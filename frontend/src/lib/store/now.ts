// A shared clock for relative times ("2 min ago") and estimated progress.
// It only ticks while something is subscribed and the page is visible, and
// returns null during server rendering/hydration (render a placeholder then).
import { useSyncExternalStore } from "react";

type Ticker = { now: number; listeners: Set<() => void>; timer: ReturnType<typeof setInterval> | null };

const tickers = new Map<number, Ticker>();

function ticker(granularityMs: number): Ticker {
  let entry = tickers.get(granularityMs);
  if (!entry) {
    entry = { now: Date.now(), listeners: new Set(), timer: null };
    tickers.set(granularityMs, entry);
  }
  return entry;
}

function update(entry: Ticker) {
  entry.now = Date.now();
  entry.listeners.forEach((listener) => listener());
}

function subscribeTo(granularityMs: number) {
  return (listener: () => void) => {
    const entry = ticker(granularityMs);
    entry.listeners.add(listener);
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        if (entry.timer) clearInterval(entry.timer);
        entry.timer = null;
      } else if (!entry.timer) {
        update(entry);
        entry.timer = setInterval(() => update(entry), granularityMs);
      }
    };
    if (entry.listeners.size === 1) {
      update(entry);
      if (document.visibilityState !== "hidden") {
        entry.timer = setInterval(() => update(entry), granularityMs);
      }
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      entry.listeners.delete(listener);
      if (entry.listeners.size === 0 && entry.timer) {
        clearInterval(entry.timer);
        entry.timer = null;
      }
    };
  };
}

const subscribers = new Map<number, (listener: () => void) => () => void>();

/** Current time in ms, refreshed every `granularityMs` while visible; null before hydration. */
export function useNow(granularityMs = 1000): number | null {
  let subscribe = subscribers.get(granularityMs);
  if (!subscribe) {
    subscribe = subscribeTo(granularityMs);
    subscribers.set(granularityMs, subscribe);
  }
  return useSyncExternalStore(
    subscribe,
    () => ticker(granularityMs).now,
    () => null,
  );
}
