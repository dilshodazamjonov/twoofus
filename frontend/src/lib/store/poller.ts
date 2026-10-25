// A shared, visibility-aware poller (used for now-playing and tulips).
//
// * One timer and at most one request in flight, however many components
//   subscribe; polling starts with the first subscriber and stops (aborting
//   any request) when the last one unmounts.
// * No traffic while the page is hidden. When it becomes visible again, or the
//   browser reports the connection is back, it refreshes at once if the data
//   is older than `refreshAfterMs`. navigator.onLine is only a hint (it can be
//   wrong): requests are still attempted, and failures back off.
// * Errors back off exponentially (5 s, 10 s, ... up to 60 s) and honour
//   Retry-After. A lost session (401) stops polling; the session store takes over.
import { useSyncExternalStore } from "react";

import { ApiError } from "@/lib/api/client";
import { asApiError, type ResourceState } from "./resource";

export type PollState<T> = ResourceState<T> & {
  /** Client time (ms) the last successful response arrived. */
  receivedAt: number | null;
  failures: number;
  /** The last attempt failed at the network level. */
  offline: boolean;
  /** True while the page is hidden (nothing is fetched then). */
  paused: boolean;
};

export type PollerOptions<T> = {
  fetcher: (signal: AbortSignal) => Promise<T>;
  /** Delay (ms) until the next poll after a success. */
  interval: (data: T) => number;
  /** On focus/visibility, refetch at once when the data is at least this old. */
  refreshAfterMs?: number;
  maxBackoffMs?: number;
};

export type Poller<T> = {
  getSnapshot: () => PollState<T>;
  getServerSnapshot: () => PollState<T>;
  subscribe: (listener: () => void) => () => void;
  refresh: () => void;
  reset: () => void;
};

const BASE_BACKOFF_MS = 5_000;

export function createPoller<T>(options: PollerOptions<T>): Poller<T> {
  const refreshAfterMs = options.refreshAfterMs ?? 10_000;
  const maxBackoffMs = options.maxBackoffMs ?? 60_000;
  const initial: PollState<T> = {
    data: undefined,
    error: undefined,
    status: "idle",
    refreshing: false,
    updatedAt: null,
    receivedAt: null,
    failures: 0,
    offline: false,
    paused: false,
  };
  let state = initial;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let controller: AbortController | null = null;
  let active = false;
  let lastInterval = 20_000;
  const listeners = new Set<() => void>();

  const emit = () => listeners.forEach((listener) => listener());
  const set = (next: Partial<PollState<T>>) => {
    state = { ...state, ...next };
    emit();
  };
  const isVisible = () => typeof document === "undefined" || document.visibilityState !== "hidden";

  function clearTimer() {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }

  function abortInflight() {
    controller?.abort();
    controller = null;
    if (state.refreshing) set({ refreshing: false });
  }

  function schedule(delayMs: number) {
    clearTimer();
    if (active) timer = setTimeout(() => void tick(), Math.max(0, delayMs));
  }

  async function tick(): Promise<void> {
    clearTimer();
    if (!active || controller) return;
    if (!isVisible()) {
      set({ paused: true });
      return; // resumes on visibilitychange
    }
    const mine = new AbortController();
    controller = mine;
    set({ refreshing: true, paused: false, status: state.data === undefined ? "loading" : state.status });
    try {
      const data = await options.fetcher(mine.signal);
      if (controller !== mine) return;
      controller = null;
      const now = Date.now();
      set({
        data,
        error: undefined,
        status: "ready",
        refreshing: false,
        updatedAt: now,
        receivedAt: now,
        failures: 0,
        offline: false,
      });
      lastInterval = options.interval(data);
      schedule(lastInterval + Math.round(Math.random() * 2_000)); // jitter: no lockstep
    } catch (raw) {
      if (controller !== mine) return; // stopped, reset or superseded
      controller = null;
      if (mine.signal.aborted) return;
      const error = asApiError(raw);
      const failures = state.failures + 1;
      set({
        error,
        status: state.data === undefined ? "error" : "ready",
        refreshing: false,
        failures,
        offline: error.isNetwork,
      });
      if (error.isUnauthenticated) {
        stop();
        return;
      }
      schedule(backoffDelay(error, failures, maxBackoffMs));
    }
  }

  function refreshIfDue() {
    if (!active) return;
    const age = state.receivedAt === null ? Infinity : Date.now() - state.receivedAt;
    if (age >= refreshAfterMs || state.error) void tick();
    else if (timer === null && controller === null) schedule(Math.max(0, lastInterval - age));
  }

  const onVisibility = () => {
    if (isVisible()) {
      set({ paused: false });
      refreshIfDue();
    } else {
      clearTimer();
      abortInflight();
      set({ paused: true });
    }
  };
  const onOnline = () => refreshIfDue();

  function start() {
    if (active) return;
    active = true;
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", refreshIfDue);
    window.addEventListener("online", onOnline);
    set({ paused: !isVisible() });
    refreshIfDue();
  }

  function stop() {
    active = false;
    clearTimer();
    abortInflight();
    if (typeof document !== "undefined") {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", refreshIfDue);
      window.removeEventListener("online", onOnline);
    }
  }

  const subscribe = (listener: () => void) => {
    listeners.add(listener);
    if (listeners.size === 1) start();
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) stop();
    };
  };
  const getSnapshot = () => state;
  const getServerSnapshot = () => initial;

  return {
    getSnapshot,
    getServerSnapshot,
    subscribe,
    refresh: () => {
      if (active) void tick();
    },
    reset: () => {
      const wasActive = active;
      stop();
      state = initial;
      emit();
      if (wasActive && listeners.size > 0) start();
    },
  };
}

/** Subscribe to a poller: polling runs while at least one component uses it. */
export function usePoller<T>(poller: Poller<T>): PollState<T> {
  return useSyncExternalStore(poller.subscribe, poller.getSnapshot, poller.getServerSnapshot);
}

export function backoffDelay(error: ApiError, failures: number, maxBackoffMs = 60_000): number {
  if (error.retryAfterSeconds !== null) {
    return Math.min(Math.max(error.retryAfterSeconds * 1000, BASE_BACKOFF_MS), 5 * 60_000);
  }
  return Math.min(maxBackoffMs, BASE_BACKOFF_MS * 2 ** Math.max(0, failures - 1));
}
